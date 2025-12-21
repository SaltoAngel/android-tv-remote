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


class AdbTcpClient:
    def __init__(self, host: str, *, port: int = 5555, timeout_s: float = 8.0) -> None:
        self._host = host
        self._port = port
        self._timeout_s = timeout_s
        self._device = None

    @property
    def host(self) -> str:
        return self._host

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
        manufacturer = self.shell("getprop ro.product.manufacturer").stdout.strip()
        model = self.shell("getprop ro.product.model").stdout.strip()
        version = self.shell("getprop ro.build.version.release").stdout.strip()

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



