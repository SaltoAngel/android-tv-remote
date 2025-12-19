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

    def send_keyevent(self, keycode: str) -> None:
        # `keycode` should be like "KEYCODE_HOME" or "KEYCODE_DPAD_UP"
        self.shell(f"input keyevent {keycode}")

    def send_text(self, text: str) -> None:
        # `input text` expects certain characters escaped; keep MVP simple.
        safe = text.replace(" ", "%s")
        self.shell(f'input text "{safe}"')


