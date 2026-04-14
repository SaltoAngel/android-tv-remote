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
from typing import Any, Callable, Optional

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
    "KEYCODE_SLEEP": 223,
    "KEYCODE_WAKEUP": 224,
    # Media
    "KEYCODE_MEDIA_PLAY_PAUSE": 85,
    "KEYCODE_MEDIA_STOP": 86,
    "KEYCODE_MEDIA_NEXT": 87,
    "KEYCODE_MEDIA_PREVIOUS": 88,
    "KEYCODE_MEDIA_REWIND": 89,
    "KEYCODE_MEDIA_FAST_FORWARD": 90,
    "KEYCODE_MEDIA_PLAY": 126,
    "KEYCODE_MEDIA_PAUSE": 127,
    "KEYCODE_MEDIA_RECORD": 130,
    # Apps & TV
    "KEYCODE_ALL_APPS": 284,
    "KEYCODE_TV": 170,
    "KEYCODE_TV_INPUT": 178,
    "KEYCODE_SETTINGS": 176,
    "KEYCODE_INFO": 165,
    "KEYCODE_GUIDE": 172,
    # Channels
    "KEYCODE_CHANNEL_UP": 166,
    "KEYCODE_CHANNEL_DOWN": 167,
    # Assistant
    "KEYCODE_ASSIST": 219,
    # Accessibility
    "KEYCODE_CAPTIONS": 175,
    # Keyboard input
    "KEYCODE_ENTER": 66,
    "KEYCODE_DEL": 67,  # Backspace
    "KEYCODE_FORWARD_DEL": 112,  # Delete
    "KEYCODE_TAB": 61,
    "KEYCODE_SPACE": 62,
    "KEYCODE_ESCAPE": 111,
    # Numpad (0-9 for channel input)
    "KEYCODE_0": 7,
    "KEYCODE_1": 8,
    "KEYCODE_2": 9,
    "KEYCODE_3": 10,
    "KEYCODE_4": 11,
    "KEYCODE_5": 12,
    "KEYCODE_6": 13,
    "KEYCODE_7": 14,
    "KEYCODE_8": 15,
    "KEYCODE_9": 16,
    # Colored keys (Teletext/HbbTV)
    "KEYCODE_PROG_RED": 183,
    "KEYCODE_PROG_GREEN": 184,
    "KEYCODE_PROG_YELLOW": 185,
    "KEYCODE_PROG_BLUE": 186,
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
    2. Start server via app_process (nohup)
    3. Setup dedicated native AdbDeviceTcp client
    4. Send control messages directly over localabstract stream
    """

    # Server version we're compatible with
    SCRCPY_VERSION = "3.1"
    DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server"

    def __init__(
        self,
        adb_client: 'Any',
    ) -> None:
        self._adb = adb_client
        self._host = adb_client.host
        self._port = 5555  # Default ADB port
        
        # ADB clients/devices for isolated streams
        self._server_client: 'Optional[Any]' = None
        self._server_thread: 'Optional[threading.Thread]' = None
        
        self._scrcpy_client: 'Optional[Any]' = None
        self._scrcpy_device: 'Optional[Any]' = None
        self._adb_info: 'Optional[Any]' = None
        
        self._connected = False
        self._server_started = False
        self._lock = threading.Lock()
        self._on_disconnect: Optional[Callable[[], None]] = None

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
                # 1. Ensure server is on device using main adb_shell connection
                self._ensure_server_on_device()

                # 2. Start server via async nohup shell command
                self._start_server()

                # 3. Setup dedicated ADB client and localabstract connection
                self._setup_connection()

                self._connected = True
                logger.info("Connected to scrcpy-server (low-latency adb_shell input enabled)")

            except Exception as e:
                self._cleanup()
                raise ScrcpyConnectionError(f"Failed to connect: {e}") from e

    def disconnect(self) -> None:
        """Disconnect from scrcpy-server."""
        with self._lock:
            self._cleanup()

    def _cleanup(self) -> None:
        self._connected = False

        if self._scrcpy_device and self._adb_info:
            try:
                self._scrcpy_device._clse(self._adb_info)
            except Exception:
                pass
            self._adb_info = None

        if self._scrcpy_client:
            try:
                self._scrcpy_client.disconnect()
            except Exception:
                pass
            self._scrcpy_client = None
            self._scrcpy_device = None

        if self._server_client:
            try:
                self._server_client.disconnect()
            except Exception:
                pass
            self._server_client = None

        # Give thread a moment to finish cleanly
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=1.0)
            self._server_thread = None

        if self._server_started:
            try:
                self._adb.shell("pkill -f scrcpy-server")
                self._adb.shell("pkill -f com.genymobile.scrcpy.Server")
            except Exception:
                pass

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

    def _ensure_server_on_device(self) -> None:
        """Push scrcpy-server to device if needed."""
        local_server = self._find_local_server()
        if not local_server:
            raise ScrcpyError("scrcpy-server not found locally")

        logger.info(f"Pushing scrcpy-server to {self.DEVICE_SERVER_PATH}")
        # Use adb_shell for fast, authorized push
        self._adb.device.push(str(local_server), self.DEVICE_SERVER_PATH)

    def _start_server(self) -> None:
        """Start scrcpy-server on the device synchronously in a background thread."""
        from .adb_client import AdbTcpClient
        
        # Kill any existing scrcpy-server instances to avoid socket conflicts
        logger.info("Cleaning up any existing scrcpy-server instances on device...")
        try:
            self._adb.shell("pkill -f scrcpy-server")
            self._adb.shell("pkill -f com.genymobile.scrcpy.Server")
            self._adb.shell("killall scrcpy-server")
        except Exception:
            pass
        time.sleep(0.1)

        # We establish a dedicated ADB connection just to keep the server running,
        # perfectly mimicking the behavior of subprocess.Popen holding a cli adb shell.
        logger.info("Establishing dedicated ADB connection to host scrcpy-server process...")
        self._server_client = AdbTcpClient(self._host, port=self._port, timeout_s=5.0)
        self._server_client.connect()

        # The command runs synchronously in the shell. Closing the ADB stream terminates it.
        server_cmd = (
            f"CLASSPATH={self.DEVICE_SERVER_PATH} app_process / com.genymobile.scrcpy.Server "
            f"{self.SCRCPY_VERSION} tunnel_forward=true video=false audio=false control=true "
            f"clipboard_autosync=false cleanup=true power_off_on_close=false log_level=warn"
        )

        def _server_worker(client: Any, cmd: str) -> None:
            try:
                # This will block as long as the server is running natively!
                client.shell(cmd)
                logger.info("Scrcpy server execution finished (shell channel closed).")
            except Exception as e:
                logger.debug(f"Scrcpy server thread exited: {e}")

        logger.info("Starting scrcpy-server process in daemon thread...")
        self._server_thread = threading.Thread(
            target=_server_worker, 
            args=(self._server_client, server_cmd), 
            daemon=True
        )
        self._server_thread.start()
        
        # Give the server a moment to start and create its socket
        time.sleep(1.0)
        self._server_started = True

    def _setup_connection(self) -> None:
        """Setup independent ADB connection and connect to control socket."""
        from .adb_client import AdbTcpClient

        logger.info("Establishing dedicated ADB connection for scrcpy stream...")
        self._scrcpy_client = AdbTcpClient(self._host, port=self._port, timeout_s=5.0)
        
        try:
            self._scrcpy_client.connect()
        except Exception as e:
            raise ScrcpyError(f"Failed to create secondary scrcpy ADB connection: {e}")
            
        self._scrcpy_device = self._scrcpy_client._device

        # Try connecting to the abstract socket. Retry polling for 3 seconds.
        for attempt in range(30):
            try:
                # Open native ADB multiplexed stream to abstract socket
                self._adb_info = self._scrcpy_device._open(
                    b"localabstract:scrcpy", 
                    transport_timeout_s=2.0, 
                    read_timeout_s=2.0, 
                    timeout_s=2.0
                )
                break
            except Exception as e:
                # Let's catch any exceptions from adb_shell
                if attempt < 29:
                    time.sleep(0.1)
                else:
                    raise ScrcpyError(f"Could not open localabstract:scrcpy stream: {e}")

        # Read initial device info
        self._read_device_info()

    def _read_device_info(self) -> None:
        """Read initial device info from server."""
        from adb_shell import constants
        
        if self._scrcpy_device and self._adb_info:
            try:
                # The server automatically sends a 64 bytes device name across the control socket
                old_timeout = self._adb_info.read_timeout_s
                self._adb_info.read_timeout_s = 1.0  # Temporarily lower timeout
                
                cmd, data = self._scrcpy_device._read_until([constants.WRTE, constants.CLSE], self._adb_info)
                
                if cmd == constants.WRTE and data:
                    device_name = data.rstrip(b'\\x00').decode('utf-8', errors='replace')
                    logger.info(f"Connected to device: {device_name}")
                
                # Restore timeout
                self._adb_info.read_timeout_s = old_timeout
            except Exception as e:
                logger.debug(f"No device info received: {e}")

    def _scrcpy_send(self, payload: bytes) -> None:
        """Send a raw byte payload to the scrcpy control socket directly via ADB WRTE."""
        from adb_shell.adb_device import AdbMessage
        from adb_shell import constants
        
        if not self._connected or not self._scrcpy_device or not self._adb_info:
            return

        # Prepare WRTE packet
        msg = AdbMessage(constants.WRTE, self._adb_info.local_id, self._adb_info.remote_id, payload)

        try:
            self._scrcpy_device._io_manager.send(msg, self._adb_info)
            # Wait for OKAY acknowledgement
            cmd, data = self._scrcpy_device._read_until([constants.OKAY, constants.CLSE], self._adb_info)
            
            if cmd == constants.CLSE:
                raise ScrcpyConnectionError("Received CLSE from scrcpy stream while writing.")
                
        except Exception as e:
            logger.error(f"Failed to send scrcpy packet: {e}")
            self._connected = False
            if self._on_disconnect:
                self._on_disconnect()

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

    def send_key_down(self, keycode_name: str) -> None:
        """
        Send only a key down event to the device.
        
        Used for long-press functionality - call send_key_up after desired delay.

        Args:
            keycode_name: Android keycode name (e.g., "KEYCODE_DPAD_CENTER")
        """
        keycode = AKEYCODE_MAP.get(keycode_name)
        if keycode is None:
            logger.warning(f"Unknown keycode: {keycode_name}")
            return
        self._send_key_event(keycode, AKEY_EVENT_ACTION_DOWN)

    def send_key_up(self, keycode_name: str) -> None:
        """
        Send only a key up event to the device.
        
        Used to complete a long-press started with send_key_down.

        Args:
            keycode_name: Android keycode name (e.g., "KEYCODE_DPAD_CENTER")
        """
        keycode = AKEYCODE_MAP.get(keycode_name)
        if keycode is None:
            logger.warning(f"Unknown keycode: {keycode_name}")
            return
        self._send_key_event(keycode, AKEY_EVENT_ACTION_UP)

    def send_long_press(self, keycode_name: str, duration_ms: int = 600) -> None:
        """
        Send a long-press event to the device.
        
        This sends key down, waits for the specified duration, then sends key up.
        Android typically recognizes a long-press after ~500ms.
        
        Note: This is a blocking call. For non-blocking long-press, use
        send_key_down followed by a delayed send_key_up in your application.

        Args:
            keycode_name: Android keycode name (e.g., "KEYCODE_DPAD_CENTER")
            duration_ms: How long to hold the key, in milliseconds (default 600ms)
        """
        keycode = AKEYCODE_MAP.get(keycode_name)
        if keycode is None:
            logger.warning(f"Unknown keycode: {keycode_name}")
            return
        
        self._send_key_event(keycode, AKEY_EVENT_ACTION_DOWN)
        time.sleep(duration_ms / 1000.0)
        self._send_key_event(keycode, AKEY_EVENT_ACTION_UP)

    def _send_key_event(self, keycode: int, action: int) -> None:
        """Send a key event control message."""
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
        self._scrcpy_send(msg)

    def send_text(self, text: str) -> None:
        """
        Send text input to the device.

        Args:
            text: Text string to send
        """
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
        self._scrcpy_send(msg)

    def expand_notification_panel(self) -> None:
        """
        Expand the notification panel on the device.
        
        This opens the notification/quick settings panel on Android TV.
        """
        # Control message format for expand notification panel:
        # - type (1 byte): SC_CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL = 5
        msg = struct.pack(">B", SC_CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL)
        self._scrcpy_send(msg)
