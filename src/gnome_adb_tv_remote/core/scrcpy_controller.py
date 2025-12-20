"""
ScrcpyController - Low-latency input injection using scrcpy-server.

This module pushes scrcpy-server to the Android device and communicates with it
directly via a socket connection, achieving ~35-70ms latency.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# scrcpy control message types
SC_CONTROL_MSG_TYPE_INJECT_KEYCODE = 0
SC_CONTROL_MSG_TYPE_INJECT_TEXT = 1
SC_CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT = 2
SC_CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT = 3
SC_CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON = 4
SC_CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL = 5
SC_CONTROL_MSG_TYPE_EXPAND_SETTINGS_PANEL = 6
SC_CONTROL_MSG_TYPE_COLLAPSE_PANELS = 7
SC_CONTROL_MSG_TYPE_GET_CLIPBOARD = 8
SC_CONTROL_MSG_TYPE_SET_CLIPBOARD = 9
SC_CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE = 10
SC_CONTROL_MSG_TYPE_ROTATE_DEVICE = 11

# Key event actions
AKEY_EVENT_ACTION_DOWN = 0
AKEY_EVENT_ACTION_UP = 1

# Android keycodes (subset for TV remote + keyboard input)
AKEYCODE_MAP = {
    # Navigation
    "KEYCODE_DPAD_UP": 19,
    "KEYCODE_DPAD_DOWN": 20,
    "KEYCODE_DPAD_LEFT": 21,
    "KEYCODE_DPAD_RIGHT": 22,
    "KEYCODE_DPAD_CENTER": 23,
    # System
    "KEYCODE_BACK": 4,
    "KEYCODE_HOME": 3,
    "KEYCODE_MENU": 82,
    # Volume
    "KEYCODE_VOLUME_UP": 24,
    "KEYCODE_VOLUME_DOWN": 25,
    "KEYCODE_VOLUME_MUTE": 164,
    # Power
    "KEYCODE_POWER": 26,
    # Media
    "KEYCODE_MEDIA_PLAY_PAUSE": 85,
    "KEYCODE_MEDIA_STOP": 86,
    "KEYCODE_MEDIA_NEXT": 87,
    "KEYCODE_MEDIA_PREVIOUS": 88,
    "KEYCODE_MEDIA_REWIND": 89,
    "KEYCODE_MEDIA_FAST_FORWARD": 90,
    # Apps
    "KEYCODE_ALL_APPS": 284,
    "KEYCODE_TV": 170,
    "KEYCODE_TV_INPUT": 178,
    # Keyboard input
    "KEYCODE_ENTER": 66,
    "KEYCODE_DEL": 67,  # Backspace
    "KEYCODE_FORWARD_DEL": 112,  # Delete
    "KEYCODE_TAB": 61,
    "KEYCODE_SPACE": 62,
    "KEYCODE_ESCAPE": 111,
}


class ScrcpyError(Exception):
    """Base exception for scrcpy-related errors."""


class ScrcpyConnectionError(ScrcpyError):
    """Failed to connect to scrcpy-server."""


class ScrcpyServerController:
    """
    Direct communication with scrcpy-server on the device.

    This approach communicates directly with scrcpy-server without running
    the full scrcpy desktop client. This means NO WINDOW is opened, and we
    get the lowest latency possible.

    Architecture:
    1. Push scrcpy-server to device
    2. Start server via app_process
    3. Setup ADB port forwarding to server's control socket
    4. Send control messages directly over the socket
    """

    # Server version we're compatible with
    SCRCPY_VERSION = "3.1"
    DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server"

    def __init__(
        self,
        adb_client: Any,
    ) -> None:
        self._adb = adb_client
        self._host = adb_client.host
        self._port = 5555  # Default ADB port
        self._control_socket: Optional[socket.socket] = None
        self._connected = False
        self._server_started = False
        self._forward_port: Optional[int] = None
        self._lock = threading.Lock()
        self._on_disconnect: Optional[Callable[[], None]] = None
        self._shell_process: Optional[subprocess.Popen] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def set_disconnect_handler(self, handler: Optional[Callable[[], None]]) -> None:
        """Set a callback to be invoked when connection is lost."""
        self._on_disconnect = handler

    def connect(self, timeout: float = 10.0) -> None:
        """
        Connect to scrcpy-server on the device.
        """
        with self._lock:
            if self._connected:
                return

            try:
                # 1. Ensure server is on device using adb_shell (authorized)
                self._ensure_server_on_device()

                # 2. Start server
                self._start_server()

                # 3. Setup forwarding and connect
                self._setup_connection()

                self._connected = True
                logger.info("Connected to scrcpy-server (low-latency input enabled)")

            except Exception as e:
                self._cleanup()
                raise ScrcpyConnectionError(f"Failed to connect: {e}") from e

    def disconnect(self) -> None:
        """Disconnect from scrcpy-server."""
        with self._lock:
            self._cleanup()

    def _cleanup(self) -> None:
        self._connected = False

        # Close control socket
        if self._control_socket:
            try:
                self._control_socket.close()
            except Exception:
                pass
            self._control_socket = None

        # Terminate server process (if any)
        if self._shell_process:
            try:
                self._shell_process.terminate()
                self._shell_process.wait(timeout=2.0)
            except Exception:
                try:
                    self._shell_process.kill()
                except Exception:
                    pass
            self._shell_process = None

        # Remove port forwarding
        if self._forward_port:
            try:
                adb = self._find_adb()
                subprocess.run([adb, "forward", "--remove", f"tcp:{self._forward_port}"], capture_output=True)
            except Exception:
                pass
            self._forward_port = None

        self._server_started = False

    def _find_local_server(self) -> Optional[Path]:
        """Find the local scrcpy-server file."""
        candidates = [
            Path("/app/share/scrcpy/scrcpy-server"),  # Flatpak
            Path("/usr/share/scrcpy/scrcpy-server"),  # System
            Path("/usr/local/share/scrcpy/scrcpy-server"),  # Local install
        ]

        for path in candidates:
            if path.exists():
                return path

        return None

    def _find_adb(self) -> str:
        """Find the adb executable."""
        candidates = ["/app/bin/adb", "adb"]
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                return path
            if os.path.isabs(candidate) and os.path.isfile(candidate):
                return candidate
        raise ScrcpyError("adb not found")

    def _ensure_server_on_device(self) -> None:
        """Push scrcpy-server to device if needed."""
        local_server = self._find_local_server()
        if not local_server:
            raise ScrcpyError("scrcpy-server not found locally")

        logger.info(f"Pushing scrcpy-server to {self.DEVICE_SERVER_PATH}")
        # Use adb_shell for fast, authorized push
        self._adb.device.push(str(local_server), self.DEVICE_SERVER_PATH)

    def _start_server(self) -> None:
        """Start scrcpy-server on the device."""
        # We use the adb CLI to start the server in a way that we can keep it alive.
        # We need to set ADB_VENDOR_KEYS so the CLI is authorized.
        from .keystore import get_adb_key_paths
        keys = get_adb_key_paths()
        env = os.environ.copy()
        env["ADB_VENDOR_KEYS"] = str(keys.private_key)
        
        adb = self._find_adb()
        
        # Ensure CLI is connected
        subprocess.run([adb, "connect", f"{self._host}:{self._port}"], capture_output=True, env=env, timeout=5)

        # Kill any existing scrcpy-server instances to avoid "Address already in use"
        logger.info("Cleaning up any existing scrcpy-server instances on device...")
        subprocess.run([adb, "-s", f"{self._host}:{self._port}", "shell", "pkill", "-f", "scrcpy-server"], capture_output=True, env=env, timeout=5)
        # Also try killall just in case pkill isn't available
        subprocess.run([adb, "-s", f"{self._host}:{self._port}", "shell", "killall", "scrcpy-server"], capture_output=True, env=env, timeout=5)
        time.sleep(0.5)

        # Arguments for v3.1: tunnel_forward=true means it listens on device abstract socket 'scrcpy'
        # We don't background with '&' here; we use Popen to keep it alive as a child process.
        server_cmd = [
            adb, "-s", f"{self._host}:{self._port}", "shell",
            f"CLASSPATH={self.DEVICE_SERVER_PATH}", "app_process", "/", "com.genymobile.scrcpy.Server",
            self.SCRCPY_VERSION,
            "tunnel_forward=true", "video=false", "audio=false", "control=true",
            "cleanup=true", "power_off_on_close=false", "log_level=warn"
        ]

        logger.info(f"Starting scrcpy-server on device: {' '.join(server_cmd)}")
        self._shell_process = subprocess.Popen(
            server_cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
        )
        
        # Give the server a moment to start and create its socket
        time.sleep(1.5)
        
        # Check if it crashed immediately
        if self._shell_process.poll() is not None:
            err = self._shell_process.stderr.read().decode() if self._shell_process.stderr else "Unknown error"
            raise ScrcpyError(f"scrcpy-server exited immediately: {err}")
            
        self._server_started = True

    def _setup_connection(self) -> None:
        """Setup ADB forwarding and connect to control socket."""
        # Find a free local port
        self._forward_port = self._find_free_port()

        # Setup port forwarding using the adb CLI.
        from .keystore import get_adb_key_paths
        keys = get_adb_key_paths()
        env = os.environ.copy()
        env["ADB_VENDOR_KEYS"] = str(keys.private_key)
        
        adb = self._find_adb()
        
        # Setup the forward
        result = subprocess.run([
            adb, "-s", f"{self._host}:{self._port}",
            "forward", f"tcp:{self._forward_port}", "localabstract:scrcpy"
        ], capture_output=True, env=env, timeout=5)
        
        if result.returncode != 0:
            raise ScrcpyError(f"Failed to setup port forward: {result.stderr.decode()}")

        # Give forwarding a moment to establish
        time.sleep(0.5)

        # Connect to the forwarded port
        self._control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._control_socket.settimeout(5.0)

        # Retry connection a few times as server may take a moment
        for attempt in range(5):
            try:
                self._control_socket.connect(("127.0.0.1", self._forward_port))
                break
            except (ConnectionRefusedError, socket.timeout):
                if attempt < 4:
                    time.sleep(0.5)
                else:
                    raise ScrcpyError("Could not connect to scrcpy-server socket")

        # Set socket to non-blocking for better responsiveness
        self._control_socket.setblocking(False)
        self._control_socket.settimeout(1.0)

        # Read initial device info
        self._read_device_info()

    def _read_device_info(self) -> None:
        """Read initial device info from server."""
        # scrcpy-server sends device name (64 bytes, null-padded)
        if self._control_socket:
            try:
                data = self._control_socket.recv(64)
                if data:
                    device_name = data.rstrip(b'\x00').decode('utf-8', errors='replace')
                    logger.info(f"Connected to device: {device_name}")
            except socket.timeout:
                # No initial data is OK for some server configurations
                pass
            except Exception as e:
                logger.debug(f"No device info received: {e}")

    def _find_free_port(self) -> int:
        """Find a free local port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _run_adb_cmd(self, args: list) -> str:
        """Deprecated, but kept for compatibility if needed."""
        adb = self._find_adb()
        cmd = [adb, "-s", f"{self._host}:{self._port}"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout

    def send_keycode(self, keycode_name: str) -> None:
        """
        Send a key event (down + up) to the device.

        Args:
            keycode_name: Android keycode name (e.g., "KEYCODE_DPAD_UP")
        """
        keycode = AKEYCODE_MAP.get(keycode_name)
        if keycode is None:
            logger.warning(f"Unknown keycode: {keycode_name}")
            return

        # Send key down then key up
        self._send_key_event(keycode, AKEY_EVENT_ACTION_DOWN)
        self._send_key_event(keycode, AKEY_EVENT_ACTION_UP)

    def _send_key_event(self, keycode: int, action: int) -> None:
        """Send a key event control message."""
        if not self._connected or not self._control_socket:
            return

        # Control message format for key event:
        # - type (1 byte): SC_CONTROL_MSG_TYPE_INJECT_KEYCODE = 0
        # - action (1 byte): AKEY_EVENT_ACTION_DOWN=0 or UP=1
        # - keycode (4 bytes, big-endian)
        # - repeat (4 bytes, big-endian)
        # - metastate (4 bytes, big-endian)
        msg = struct.pack(
            ">BBIII",
            SC_CONTROL_MSG_TYPE_INJECT_KEYCODE,
            action,
            keycode,
            0,  # repeat
            0,  # metastate
        )

        try:
            self._control_socket.sendall(msg)
        except Exception as e:
            logger.error(f"Failed to send key event: {e}")
            self._connected = False
            if self._on_disconnect:
                self._on_disconnect()

    def send_text(self, text: str) -> None:
        """
        Send text input to the device.

        Args:
            text: Text string to send
        """
        if not self._connected or not self._control_socket:
            return

        # Encode text as UTF-8
        text_bytes = text.encode("utf-8")
        text_len = len(text_bytes)

        # Control message format for text:
        # - type (1 byte): SC_CONTROL_MSG_TYPE_INJECT_TEXT = 1
        # - length (4 bytes, big-endian)
        # - text (variable length)
        msg = struct.pack(
            ">BI",
            SC_CONTROL_MSG_TYPE_INJECT_TEXT,
            text_len,
        ) + text_bytes

        try:
            self._control_socket.sendall(msg)
        except Exception as e:
            logger.error(f"Failed to send text: {e}")
            self._connected = False
            if self._on_disconnect:
                self._on_disconnect()

