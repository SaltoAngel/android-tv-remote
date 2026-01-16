"""
ADB TCP Client for connecting to Android devices over the network.

Provides a high-level interface for connecting to Android devices via 
ADB-over-TCP (port 5555), handling RSA key authentication, and executing
shell commands.
"""

from __future__ import annotations

import base64
import re
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




@dataclass(frozen=True)
class DeviceStatus:
    """Current status of the connected device."""
    screen_on: bool
    volume_level: int  # 0-100 percentage
    volume_max: int  # Maximum volume level
    battery_level: int | None  # 0-100 percentage, None if not available (TV)
    battery_charging: bool | None  # None if not available
    memory_used_mb: int
    memory_total_mb: int
    storage_used_gb: float
    storage_total_gb: float


@dataclass(frozen=True)
class MediaInfo:
    """Information about the currently playing media."""
    title: str | None  # Track/video title
    artist: str | None  # Artist/channel name
    album: str | None  # Album name (if available)
    package_name: str | None  # App playing the media
    playback_state: str  # "Playing", "Paused", or "Stopped"
    position_ms: int  # Current playback position in milliseconds
    duration_ms: int  # Total duration in milliseconds (0 if unknown)


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
        match = re.search(r'ActivityRecord\{[^ ]+ [^ ]+ ([^/]+)/', result.stdout)
        if match:
            return match.group(1)
        return None


    def get_power_state(self) -> bool:
        """Check if the device screen is on.

        Returns:
            True if screen is on, False otherwise.
        """
        result = self.shell("dumpsys power | grep 'Display Power'")
        # Look for "Display Power: state=ON" or similar
        return "state=ON" in result.stdout.upper()

    def get_volume_level(self) -> tuple[int, int, bool]:
        """Get the current volume level for media stream.

        Returns:
            Tuple of (current_volume, max_volume, is_muted).
        """
        result = self.shell("dumpsys audio | sed -n '/- STREAM_MUSIC:/,/- STREAM_/p' | head -10")
        
        # Parse output like:
        # - STREAM_MUSIC:
        #    Muted: false
        #    Min: 0
        #    Max: 15
        #    streamVolume:6
        #    Current: 2 (speaker): 8, 400 (hdmi): 6, ...
        #    Devices: hdmi
        current = 0
        max_vol = 15  # Default for most Android TVs
        is_muted = False
        active_device = None
        current_line = ""
        stream_volume = None
        
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith("Muted:"):
                is_muted = line.split(":")[1].strip().lower() == "true"
            elif line.startswith("Max:"):
                try:
                    max_vol = int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.startswith("streamVolume:"):
                # Fallback value: streamVolume:6
                try:
                    stream_volume = int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.startswith("Current:"):
                current_line = line
            elif line.startswith("Devices:"):
                # Get active device: "Devices: hdmi" or "Devices: speaker"
                try:
                    active_device = line.split(":")[1].strip()
                except (ValueError, IndexError):
                    pass
        
        # Parse current volume based on active device
        if current_line and active_device:
            # Map device names to their IDs in the Current line
            # Common mappings: speaker=2, headset=4, headphone=8, bt_a2dp=80, hdmi=400
            device_patterns = [
                f"({active_device}):",  # e.g., "(hdmi):" or "(speaker):"
            ]
            for pattern in device_patterns:
                if pattern in current_line:
                    try:
                        parts = current_line.split(pattern)
                        if len(parts) > 1:
                            current = int(parts[1].split(",")[0].strip())
                            break
                    except (ValueError, IndexError):
                        pass
        
        # Use streamVolume as fallback if we couldn't parse the current volume
        if current == 0 and stream_volume is not None:
            current = stream_volume
        
        return (current, max_vol, is_muted)

    def get_media_session_info(self) -> MediaInfo | None:
        """Get information about the currently playing media.

        Parses dumpsys media_session to extract playback state and metadata.

        Returns:
            MediaInfo if media is playing, None if no active session.
        """
        result = self.shell("dumpsys media_session")
        
        # Initialize values
        package_name: str | None = None
        playback_state = "Stopped"
        position_ms = 0
        title: str | None = None
        artist: str | None = None
        album: str | None = None
        active_session = False
        
        for line in result.stdout.split('\n'):
            line = line.strip()
            
            # Find active session package
            # Format: starboard com.google.android.youtube.tv/starboard (userId=0)
            if 'active=true' in line:
                active_session = True
            
            # Package name is on the session line
            if '/starboard' in line or ('package=' in line):
                # Try to extract package from "package=com.xxx"
                pkg_match = re.search(r'package=([^\s]+)', line)
                if pkg_match:
                    package_name = pkg_match.group(1)
                else:
                    # Try format: com.package.name/activityName
                    pkg_match = re.search(r'\s([a-z][a-z0-9_.]+)/', line)
                    if pkg_match:
                        package_name = pkg_match.group(1)
            
            # Parse playback state
            # Format: state=PlaybackState {state=3, position=29480, ...}
            if 'state=PlaybackState' in line:
                # state: 0=None, 1=Stopped, 2=Paused, 3=Playing, 4=FastForward, 5=Rewind
                state_match = re.search(r'state=(\d+)', line.split('PlaybackState')[1])
                if state_match:
                    state_code = int(state_match.group(1))
                    if state_code == 3:
                        playback_state = "Playing"
                    elif state_code == 2:
                        playback_state = "Paused"
                    else:
                        playback_state = "Stopped"
                
                # Parse position
                pos_match = re.search(r'position=(\d+)', line)
                if pos_match:
                    position_ms = int(pos_match.group(1))
            
            # Parse metadata
            # Format: metadata: size=5, description=Title, Artist, Album
            if 'metadata:' in line and 'description=' in line:
                desc_match = re.search(r'description=(.+)$', line)
                if desc_match:
                    description = desc_match.group(1)
                    # Split by comma - format is "Title, Artist, Album" or "Title, Artist, null"
                    parts = [p.strip() for p in description.split(',')]
                    if len(parts) >= 1 and parts[0] and parts[0].lower() != 'null':
                        title = parts[0]
                    if len(parts) >= 2 and parts[1] and parts[1].lower() != 'null':
                        artist = parts[1]
                    if len(parts) >= 3 and parts[2] and parts[2].lower() != 'null':
                        album = parts[2]
        
        # Return None if no active media session
        if not active_session or playback_state == "Stopped":
            return None
        
        return MediaInfo(
            title=title,
            artist=artist,
            album=album,
            package_name=package_name,
            playback_state=playback_state,
            position_ms=position_ms,
            duration_ms=0,  # Duration not available in dumpsys output
        )

    def has_tv_input_support(self) -> bool:
        """Check if the device has hardware TV input support (HDMI, tuner, etc.).
        
        This determines whether the device is a real TV with input switching capability
        versus a streaming box like Mi Box that doesn't have physical inputs.
        
        Returns:
            True if device has hardware TV inputs, False otherwise.
        """
        try:
            result = self.shell("dumpsys tv_input")
            output = result.stdout
            lines = output.split('\n')
            
            # Check for hardware input indicators in the output
            # Real TVs have entries like:
            # - org.droidtv.hdmiService
            # - org.droidtv.tunerservice
            # - mHardwareInputIdMap with INDENTED entries (not just the header)
            # - HW\d+ patterns
            
            # Check for hardware input map entries
            # The header looks like: "mHardwareInputIdMap: deviceId -> inputId"
            # Real entries are INDENTED below and look like: "    1 -> org.droidtv..."
            for i, line in enumerate(lines):
                if "mHardwareInputIdMap:" in line:
                    # Check if there are indented entries after the header
                    for j in range(i + 1, min(i + 10, len(lines))):
                        next_line = lines[j]
                        # Stop if we hit the next section (mHdmiInputIdMap or mInputMap)
                        if next_line.strip().startswith("mHdmi") or next_line.strip().startswith("mInputMap"):
                            break
                        # Check for indented entry with "->" (like "    1 -> org.droidtv...")
                        # These entries start with whitespace (indented) and contain " -> "
                        if next_line.startswith("    ") and " -> " in next_line:
                            return True
                    break
            
            # Check for mHdmiInputIdMap entries with actual device mappings
            for i, line in enumerate(lines):
                if "mHdmiInputIdMap:" in line:
                    for j in range(i + 1, min(i + 10, len(lines))):
                        next_line = lines[j]
                        # Stop if we hit the next section
                        if next_line.strip().startswith("mInputMap") or next_line.strip().startswith("mHardware"):
                            break
                        # Check for indented entry
                        if next_line.startswith("    ") and " -> " in next_line:
                            return True
                    break
            
            # Alternative check: Look for hardware service packages
            # These are specific to TVs with physical inputs
            hardware_services = [
                "org.droidtv.hdmiService",
                "org.droidtv.tunerservice", 
                "org.droidtv.scartService",
                "org.droidtv.componentService",
            ]
            
            for service in hardware_services:
                if service in output:
                    # Found a hardware input service - this is a real TV
                    return True
            
            
            # Check for HW device entries (pattern like /HW9, /HW10)
            # These indicate physical hardware inputs
            if re.search(r'/HW\d+', output):
                return True
            
            return False
            
        except Exception:
            # If we can't check, assume no support
            return False

    def get_device_status(self) -> DeviceStatus:
        """Get comprehensive device status in a single call.

        This combines multiple shell commands for efficiency.
        """
        # Combine commands to reduce RTT
        sep = "|||STATUS_SEP|||"
        cmd = f"""
dumpsys power | grep 'Display Power'; echo '{sep}'
dumpsys audio | sed -n '/- STREAM_MUSIC:/,/- STREAM_/p' | head -10; echo '{sep}'
dumpsys battery; echo '{sep}'
cat /proc/meminfo | head -3; echo '{sep}'
df -h /data | tail -1
"""
        result = self.shell(cmd)
        parts = result.stdout.split(sep)
        
        # Parse power state
        screen_on = "state=ON" in (parts[0] if len(parts) > 0 else "").upper()
        
        # Parse volume (same logic as get_volume_level)
        current_vol, max_vol = 0, 15
        if len(parts) > 1:
            audio_output = parts[1]
            active_device = None
            current_line = ""
            stream_volume = None
            
            for line in audio_output.split('\n'):
                line = line.strip()
                if line.startswith("Max:"):
                    try:
                        max_vol = int(line.split(":")[1].strip())
                    except (ValueError, IndexError):
                        pass
                elif line.startswith("streamVolume:"):
                    try:
                        stream_volume = int(line.split(":")[1].strip())
                    except (ValueError, IndexError):
                        pass
                elif line.startswith("Current:"):
                    current_line = line
                elif line.startswith("Devices:"):
                    try:
                        active_device = line.split(":")[1].strip()
                    except (ValueError, IndexError):
                        pass
            
            # Parse current volume based on active device
            if current_line and active_device:
                pattern = f"({active_device}):"
                if pattern in current_line:
                    try:
                        vol_parts = current_line.split(pattern)
                        if len(vol_parts) > 1:
                            current_vol = int(vol_parts[1].split(",")[0].strip())
                    except (ValueError, IndexError):
                        pass
            
            # Use streamVolume as fallback
            if current_vol == 0 and stream_volume is not None:
                current_vol = stream_volume
        
        # Parse battery (may not be available on TVs)
        battery_level = None
        battery_charging = None
        if len(parts) > 2:
            battery_output = parts[2]
            for line in battery_output.split('\n'):
                line = line.strip()
                if line.startswith("level:"):
                    try:
                        battery_level = int(line.split(":")[1].strip())
                    except (ValueError, IndexError):
                        pass
                elif line.startswith("status:"):
                    # 2 = charging, 5 = full
                    try:
                        status = int(line.split(":")[1].strip())
                        battery_charging = status in (2, 5)
                    except (ValueError, IndexError):
                        pass
        
        # Parse memory
        mem_total_mb, mem_used_mb = 0, 0
        if len(parts) > 3:
            mem_output = parts[3]
            mem_free = 0
            for line in mem_output.split('\n'):
                if "MemTotal:" in line:
                    try:
                        # MemTotal: 1234567 kB
                        mem_total_mb = int(line.split()[1]) // 1024
                    except (ValueError, IndexError):
                        pass
                elif "MemAvailable:" in line or "MemFree:" in line:
                    try:
                        mem_free = int(line.split()[1]) // 1024
                    except (ValueError, IndexError):
                        pass
            mem_used_mb = mem_total_mb - mem_free
        
        # Parse storage
        storage_used_gb, storage_total_gb = 0.0, 0.0
        if len(parts) > 4:
            storage_output = parts[4].strip()
            # Format: /dev/... 32G 12G 20G 38% /data
            storage_parts = storage_output.split()
            if len(storage_parts) >= 4:
                try:
                    total_str = storage_parts[1]
                    used_str = storage_parts[2]
                    # Parse values like "32G", "12G", "500M"
                    storage_total_gb = self._parse_size_to_gb(total_str)
                    storage_used_gb = self._parse_size_to_gb(used_str)
                except (ValueError, IndexError):
                    pass
        
        return DeviceStatus(
            screen_on=screen_on,
            volume_level=current_vol,
            volume_max=max_vol,
            battery_level=battery_level,
            battery_charging=battery_charging,
            memory_used_mb=mem_used_mb,
            memory_total_mb=mem_total_mb,
            storage_used_gb=storage_used_gb,
            storage_total_gb=storage_total_gb,
        )

    def _parse_size_to_gb(self, size_str: str) -> float:
        """Parse size string like '32G', '500M', '1.5T' to GB."""
        size_str = size_str.strip().upper()
        if not size_str:
            return 0.0
        
        multipliers = {'K': 1/1024/1024, 'M': 1/1024, 'G': 1, 'T': 1024}
        unit = size_str[-1]
        if unit in multipliers:
            try:
                return float(size_str[:-1]) * multipliers[unit]
            except ValueError:
                return 0.0
        try:
            return float(size_str)
        except ValueError:
            return 0.0



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
            adb_info = None
            try:
                adb_info = _AdbTransactionInfo(None, None, timeout, timeout, None)
            except TypeError:
                # Some versions might have different signature for _AdbTransactionInfo
                pass
            
            # If constructor failed, use a mock object with required attributes
            if adb_info is None:
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



