"""
ADB TCP Client for connecting to Android devices over the network.

Provides a high-level interface for connecting to Android devices via 
ADB-over-TCP (port 5555), handling RSA key authentication, and executing
shell commands.
"""

from __future__ import annotations

from dataclasses import dataclass

from .keystore import ensure_adb_keys_exist


class AdbAuthRequiredError(RuntimeError):
    """Raised when the device requires the user to authorize the RSA key."""


class AdbConnectError(RuntimeError):
    """Raised when we couldn't connect/authenticate to the device."""


@dataclass(frozen=True)
class ShellResult:
    stdout: str


@dataclass(frozen=True)
class DeviceInfo:
    manufacturer: str
    model: str
    version: str


@dataclass
class AppInfo:
    """Information about an installed or running app."""
    package_name: str
    label: str  # Human-readable app name
    is_active: bool = False  # Whether this app is currently in foreground
    icon_path: str | None = None  # Path to cached icon file


class AdbTcpClient:
    def __init__(self, host: str, *, port: int = 5555, timeout_s: float = 8.0) -> None:
        self._host = host
        self._port = port
        self._timeout_s = timeout_s
        self._device = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def connected(self) -> bool:
        """Check if the client is currently connected to a device."""
        return self._device is not None

    def connect(self) -> None:
        """Connect and authenticate to ADB-over-TCP.

        This is blocking and should be run in a worker thread.
        """
        from adb_shell.adb_device import AdbDeviceTcp  # type: ignore
        from adb_shell.auth.sign_pythonrsa import PythonRSASigner  # type: ignore

        try:
            from adb_shell.exceptions import (  # type: ignore
                AdbConnectionError,
                AdbTimeoutError,
                DeviceAuthError,
            )
        except Exception:  # pragma: no cover
            AdbConnectionError = Exception  # type: ignore
            AdbTimeoutError = Exception  # type: ignore
            DeviceAuthError = Exception  # type: ignore

        keys = ensure_adb_keys_exist()
        # adb-shell's docs show reading these as text (not bytes)
        pub = keys.public_key.read_text(encoding="utf-8")
        priv = keys.private_key.read_text(encoding="utf-8")
        signer = PythonRSASigner(pub, priv)

        try:
            dev = AdbDeviceTcp(self._host, self._port, default_transport_timeout_s=float(self._timeout_s))
        except TypeError:
            dev = AdbDeviceTcp(self._host, self._port, default_timeout_s=float(self._timeout_s))

        try:
            dev.connect(rsa_keys=[signer], auth_timeout_s=1.0)
        except DeviceAuthError as e:
            raise AdbAuthRequiredError("Authorize this computer on the TV, then retry.") from e
        except (AdbTimeoutError, AdbConnectionError) as e:
            raise AdbConnectError(str(e) or "ADB connection failed") from e
        except Exception as e:
            msg = str(e)
            if "unauthorized" in msg.lower() or "auth" in msg.lower():
                raise AdbAuthRequiredError("Authorize this computer on the TV, then retry.") from e
            raise AdbConnectError(msg or "ADB connection failed") from e

        self._device = dev

    def disconnect(self) -> None:
        dev = self._device
        self._device = None
        if not dev:
            return
        try:
            dev.close()
        except Exception:
            pass

    def get_device_info(self) -> DeviceInfo:
        """Retrieve basic device information via getprop.

        This is blocking and should be run in a worker thread.
        """
        # Combine commands to save RTT
        # We use a separator that unlikely to be in the output
        sep = "|||"
        cmd = f"getprop ro.product.manufacturer; echo '{sep}'; getprop ro.product.model; echo '{sep}'; getprop ro.build.version.release"
        
        output = self.shell(cmd).stdout
        parts = output.split(sep)
        
        manufacturer = parts[0].strip() if len(parts) > 0 else "Unknown"
        model = parts[1].strip() if len(parts) > 1 else "Android Device"
        version = parts[2].strip() if len(parts) > 2 else "Unknown"

        return DeviceInfo(
            manufacturer=manufacturer or "Unknown",
            model=model or "Android Device",
            version=version or "Unknown",
        )

    @property
    def device(self):
        return self._device

    def shell(self, command: str) -> ShellResult:
        dev = self._device
        if not dev:
            raise AdbConnectError("Not connected")
        out = dev.shell(command)  # adb-shell returns a decoded string by default
        return ShellResult(stdout=str(out) if out is not None else "")

    def get_current_app(self) -> str | None:
        """Get the currently focused app's package name.

        Returns:
            Package name of the current foreground app, or None if unavailable.
        """
        result = self.shell("dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'")
        # Parse: mResumedActivity: ActivityRecord{... com.package.name/... ...}
        import re
        match = re.search(r'ActivityRecord\{[^ ]+ [^ ]+ ([^/]+)/', result.stdout)
        if match:
            return match.group(1)
        return None

    def get_recent_apps(self, limit: int = 10) -> list[AppInfo]:
        """Get list of recently used apps.

        Args:
            limit: Maximum number of apps to return.

        Returns:
            List of AppInfo for recently used apps, most recent first.
        """
        import re
        result = self.shell("dumpsys activity recents")
        current_app = self.get_current_app()

        # Parse: * Recent #N: Task{... A=uid:package.name ...} or I=package.name/...
        pattern = r'\* Recent #\d+:.*?(?:A=\d+:([^\s}]+)|I=([^/\s]+))'
        matches = re.findall(pattern, result.stdout)

        seen = set()
        apps: list[AppInfo] = []
        for match in matches:
            pkg = match[0] or match[1]
            if pkg and pkg not in seen:
                seen.add(pkg)
                label = self._get_app_label(pkg)
                apps.append(AppInfo(
                    package_name=pkg,
                    label=label,
                    is_active=(pkg == current_app)
                ))
                if len(apps) >= limit:
                    break
        return apps

    def get_installed_apps(self, third_party_only: bool = True) -> list[AppInfo]:
        """Get list of installed apps.

        Args:
            third_party_only: If True, only return user-installed apps.

        Returns:
            List of AppInfo for installed apps.
        """
        flag = "-3" if third_party_only else ""
        result = self.shell(f"pm list packages {flag}")
        current_app = self.get_current_app()

        apps: list[AppInfo] = []
        for line in result.stdout.strip().split('\n'):
            if line.startswith("package:"):
                pkg = line[8:].strip()
                if pkg:
                    label = self._get_app_label(pkg)
                    apps.append(AppInfo(
                        package_name=pkg,
                        label=label,
                        is_active=(pkg == current_app)
                    ))

        # Sort by label
        apps.sort(key=lambda a: a.label.lower())
        return apps

    def _get_app_label(self, package_name: str) -> str:
        """Get human-readable app label from package name.

        Falls back to package name if label cannot be retrieved.
        """
        # Known app mappings for common TV apps
        KNOWN_APPS = {
            # Streaming
            "com.google.android.youtube.tv": "YouTube",
            "com.google.android.youtube.tvmusic": "YouTube Music",
            "com.netflix.ninja": "Netflix",
            "com.amazon.amazonvideo.livingroom": "Prime Video",
            "com.disney.disneyplus": "Disney+",
            "com.hbo.hbonow": "HBO Max",
            "com.apple.atve.androidtv.appletv": "Apple TV",
            "com.spotify.tv.android": "Spotify",
            "com.plexapp.android": "Plex",
            "com.stremio.one": "Stremio",
            "org.videolan.vlc": "VLC",
            "com.mxtech.videoplayer.ad": "MX Player",
            "com.kodi": "Kodi",
            # Turkish services
            "com.digiturk.iq.mobil": "beIN CONNECT",
            "com.turkcell.ott": "Turkcell TV+",
            "com.blutv.androidtv": "BluTV",
            "com.exxen.exxen": "Exxen",
            "com.gain.androidtv": "Gain",
            "com.tabii.android": "Tabii",
            # Utilities
            "org.localsend.localsend_app": "LocalSend",
            "com.phlox.tvwebbrowser": "TV Bro",
            "nextapp.fx": "FX Explorer",
            "com.apkmirror.helper.prod": "APKMirror",
            "com.bp.box": "BePlayer",
            # System
            "com.google.android.apps.tv.launcherx": "Home",
            "com.android.tv.settings": "Settings",
            "com.google.android.tvlauncher": "Android TV Home",
            "com.google.android.katniss": "Google App",
            "com.google.android.videos": "Google TV",
        }

        # Check known apps first
        if package_name in KNOWN_APPS:
            return KNOWN_APPS[package_name]

        # Try to extract meaningful name from package
        parts = package_name.split('.')
        if len(parts) >= 2:
            # Try different strategies
            # Strategy 1: Use last meaningful part
            name = parts[-1]
            
            # Skip generic endings, try second-to-last
            generic_endings = {'android', 'tv', 'app', 'mobile', 'mobil', 'client', 'prod', 'one'}
            if name.lower() in generic_endings and len(parts) >= 3:
                name = parts[-2]
                # If still generic, combine last two
                if name.lower() in generic_endings and len(parts) >= 4:
                    name = f"{parts[-3]} {parts[-2]}"
            
            # Clean up the name
            name = name.replace('_', ' ').replace('-', ' ')
            
            # Handle camelCase
            import re
            name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
            
            # Capitalize each word
            name = ' '.join(word.capitalize() for word in name.split())
            
            return name
        
        return package_name

    def launch_app(self, package_name: str) -> bool:
        """Launch an app by package name.

        Args:
            package_name: The package name of the app to launch.

        Returns:
            True if launch command was sent successfully.
        """
        # Use monkey to launch the main activity
        result = self.shell(f"monkey -p {package_name} -c android.intent.category.LEANBACK_LAUNCHER 1 2>/dev/null || monkey -p {package_name} -c android.intent.category.LAUNCHER 1")
        return "Events injected" in result.stdout or "No activities found" not in result.stdout

    def get_app_icon(self, package_name: str) -> bytes | None:
        """Extract app icon from APK.

        Args:
            package_name: The package name of the app.

        Returns:
            Icon data as PNG bytes, or None if extraction failed.
        """
        import base64

        # Get APK path
        result = self.shell(f"pm path {package_name}")
        if not result.stdout or "package:" not in result.stdout:
            return None

        apk_path = result.stdout.split("package:")[1].strip().split('\n')[0]

        # Common icon paths to try (highest resolution first)
        icon_paths = [
            "res/mipmap-xxxhdpi-v4/ic_launcher.png",
            "res/mipmap-xxhdpi-v4/ic_launcher.png",
            "res/mipmap-xhdpi-v4/ic_launcher.png",
            "res/mipmap-hdpi-v4/ic_launcher.png",
            "res/mipmap-mdpi-v4/ic_launcher.png",
            "res/drawable-xxxhdpi-v4/ic_launcher.png",
            "res/drawable-xxhdpi-v4/ic_launcher.png",
            "res/drawable-xhdpi-v4/ic_launcher.png",
            "res/drawable-hdpi-v4/ic_launcher.png",
            # Banner icons for TV apps
            "res/drawable-xhdpi/banner.png",
            "res/drawable/banner.png",
            "res/mipmap-xhdpi-v4/ic_launcher_foreground.png",
            # Round icons
            "res/mipmap-xxxhdpi-v4/ic_launcher_round.png",
            "res/mipmap-xxhdpi-v4/ic_launcher_round.png",
        ]

        for icon_path in icon_paths:
            # Try to extract icon and encode as base64
            result = self.shell(f"unzip -p '{apk_path}' '{icon_path}' 2>/dev/null | base64")
            if result.stdout and len(result.stdout.strip()) > 100:
                try:
                    icon_data = base64.b64decode(result.stdout.strip())
                    # Verify it's valid PNG (starts with PNG magic bytes)
                    if icon_data[:4] == b'\x89PNG':
                        return icon_data
                except Exception:
                    continue

        return None


    def is_paired_silent(self) -> bool:
        """Check if the device is paired without triggering the auth prompt.

        This mimics the handshake process but aborts before sending the Public Key
        if authentication fails, preventing the TV from showing the permission dialog.
        """
        from adb_shell.adb_device import AdbDeviceTcp, AdbMessage, constants  # type: ignore
        from adb_shell.auth.sign_pythonrsa import PythonRSASigner  # type: ignore

        # Attempt to import internal _AdbTransactionInfo (adb-shell < 0.2.0 compatibility?)
        # Current flatpak has 0.4.4 so it should be there or handled.
        try:
            from adb_shell.adb_device import _AdbTransactionInfo  # type: ignore
        except ImportError:
            class _AdbTransactionInfo:  # type: ignore
                def __init__(self, *args):
                    self.transport_timeout_s = 5.0
                    self.read_timeout_s = 5.0

        keys = ensure_adb_keys_exist()
        pub = keys.public_key.read_text(encoding="utf-8")
        priv = keys.private_key.read_text(encoding="utf-8")
        signer = PythonRSASigner(pub, priv)
        rsa_keys = [signer]

        # Use short timeout for check
        timeout = 2.0

        try:
            try:
                device = AdbDeviceTcp(self._host, self._port, default_transport_timeout_s=timeout)
            except TypeError:
                device = AdbDeviceTcp(self._host, self._port, default_timeout_s=timeout)

            # Access internals
            manager = device._io_manager
            transport = manager._transport
            banner = device._banner
            if not banner:
                import socket
                banner = socket.gethostname().encode()

            # Create transaction info
            try:
                 adb_info = _AdbTransactionInfo(None, None, timeout, timeout, None)
            except TypeError:
                # Some versions might have different signature for _AdbTransactionInfo
                # But creating a dummy object with required attributes is safer if constructor varies
                pass
            
            # If constructor failed or we want to be safe with duck typing:
            if 'adb_info' not in locals():
                class MockInfo:
                    def __init__(self, t):
                        self.transport_timeout_s = t
                        self.read_timeout_s = t
                adb_info = MockInfo(timeout)


            # 1. Connect transport
            transport.connect(adb_info.transport_timeout_s)

            # 2. Send CNXN
            msg = AdbMessage(constants.CNXN, constants.VERSION, constants.MAX_ADB_DATA, b'host::%s\0' % banner)
            manager._send(msg, adb_info)

            # 3. Read response
            cmd, arg0, maxdata, banner2 = manager._read_expected_packet_from_device([constants.AUTH, constants.CNXN], adb_info)

            if cmd == constants.CNXN:
                return True

            if cmd != constants.AUTH:
                return False

            # 4. Device needs auth. Try signing.
            for rsa_key in rsa_keys:
                if arg0 != constants.AUTH_TOKEN:
                    return False
                
                signed_token = rsa_key.Sign(banner2)
                msg = AdbMessage(constants.AUTH, constants.AUTH_SIGNATURE, 0, signed_token)
                manager._send(msg, adb_info)

                try:
                    cmd, arg0, maxdata, banner2 = manager._read_expected_packet_from_device([constants.CNXN, constants.AUTH], adb_info)
                except Exception:
                    return False

                if cmd == constants.CNXN:
                    return True
                
                # If AUTH again, signature rejected. Stop here.
                if cmd == constants.AUTH:
                    return False
            
            return False

        except Exception:
            # Connection failed, timeout, or other error -> assume not paired / not available
            return False
        finally:
            try:
                if 'transport' in locals():
                    transport.close()
            except Exception:
                pass



