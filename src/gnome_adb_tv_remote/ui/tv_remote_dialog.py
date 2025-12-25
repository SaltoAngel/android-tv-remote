"""
TV Remote Dialog for controlling external TV device.

This module provides the TvRemoteDialog class, a modal dialog that displays
a d-pad interface for controlling a separate TV device when the Input button
is used with an external TV IP configured.
"""

from __future__ import annotations

import logging
import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..core.adb_client import AdbAuthRequiredError, AdbConnectError, AdbTcpClient, DeviceInfo  # noqa: E402
from .preferences_dialog import get_action_tooltip, _load_shortcuts_dict  # noqa: E402

logger = logging.getLogger(__name__)

# Path to material icons
def get_icons_dir():
    # Check Flatpak path first
    flatpak_path = "/app/share/io.github.erenseymen.android-tv-remote/icons/material"
    if os.path.exists(flatpak_path):
        return flatpak_path
    # Fallback to local development path
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/icons/material"))

ICONS_DIR = get_icons_dir()

# CSS for compact button layout
BUTTON_CSS = """
button.tv-remote-button {
    padding: 12px;
    min-width: 80px;
    min-height: 80px;
}

button.tv-remote-button image {
    -gtk-icon-style: symbolic;
}
"""

# D-pad keycodes
DPAD_KEYCODES = {
    "KEYCODE_DPAD_UP": "dpad-up",
    "KEYCODE_DPAD_DOWN": "dpad-down",
    "KEYCODE_DPAD_LEFT": "dpad-left",
    "KEYCODE_DPAD_RIGHT": "dpad-right",
    "KEYCODE_DPAD_CENTER": "dpad-center",
}


class TvRemoteDialog(Adw.Window):
    """Modal dialog for controlling external TV device with d-pad."""

    def __init__(self, parent: Gtk.Window, tv_ip: str, settings: Gio.Settings) -> None:
        super().__init__(
            transient_for=parent,
            modal=True,
            title="TV Remote",
            default_width=280,
            default_height=280,
        )
        
        self._tv_ip = tv_ip
        self._settings = settings
        self._tv_client: AdbTcpClient | None = None
        self._connected = False
        self._key_map: dict[int, str] = {}
        self._device_info: DeviceInfo | None = None
        self._title_widget: Adw.WindowTitle | None = None
        
        self._build_ui()
        self._load_dpad_shortcuts()
        
        # Connect to TV in background
        self._connect_to_tv_async()
        
        # Add keyboard controller for shortcuts and Escape
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)
        
        self.connect("close-request", self._on_close_request)

    def _on_close_request(self, *_args) -> bool:
        """Disconnect from TV and close the dialog."""
        self._disconnect_from_tv()
        self.hide()
        return True

    def _on_key_pressed(self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, _state: Gdk.ModifierType) -> bool:
        """Handle keyboard shortcuts for d-pad and Escape key."""
        # Escape closes the dialog
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        
        # Handle d-pad shortcuts
        lower_keyval = Gdk.keyval_to_lower(keyval)
        keycode = self._key_map.get(keyval) or self._key_map.get(lower_keyval)
        
        if keycode and keycode in DPAD_KEYCODES:
            # Flash the button
            self._flash_button(keycode)
            # Send command to TV
            self._send_keycode_to_tv(keycode)
            return True
        
        return False

    def _load_dpad_shortcuts(self) -> None:
        """Load d-pad keyboard shortcuts from settings."""
        from .preferences_dialog import ACTION_TO_KEYCODE, gdk_name_to_keyval
        
        shortcuts = _load_shortcuts_dict(self._settings)
        
        # Build keyval -> keycode mapping for d-pad only
        self._key_map = {}
        dpad_actions = ["dpad-up", "dpad-down", "dpad-left", "dpad-right", "dpad-center"]
        
        for action in dpad_actions:
            keycode = ACTION_TO_KEYCODE.get(action)
            if keycode is None:
                continue
            key_names = shortcuts.get(action, [])
            for key_name in key_names:
                keyval = gdk_name_to_keyval(key_name)
                if keyval is not None:
                    self._key_map[keyval] = keycode

    def _connect_to_tv_async(self) -> None:
        """Connect to TV device in background thread."""
        def worker():
            try:
                client = AdbTcpClient(self._tv_ip, port=5555, timeout_s=5.0)
                client.connect()
                # Get device info after connection
                device_info = client.get_device_info()
                GLib.idle_add(self._on_tv_connected, client, device_info)
            except AdbAuthRequiredError:
                GLib.idle_add(self._on_tv_connection_failed, f"TV {self._tv_ip} requires authorization. Please pair first.")
            except AdbConnectError as e:
                GLib.idle_add(self._on_tv_connection_failed, f"Failed to connect to TV {self._tv_ip}: {str(e)}")
            except Exception as e:
                logger.error(f"Error connecting to TV {self._tv_ip}: {e}")
                GLib.idle_add(self._on_tv_connection_failed, f"Error connecting to TV")
        
        threading.Thread(target=worker, name="tv-connect", daemon=True).start()

    def _on_tv_connected(self, client: AdbTcpClient, device_info: DeviceInfo) -> None:
        """Called when TV connection succeeds."""
        self._tv_client = client
        self._connected = True
        self._device_info = device_info
        # Update subtitle with device name
        if self._title_widget:
            device_name = GLib.markup_escape_text(f"{device_info.manufacturer} {device_info.model}")
            self._title_widget.set_subtitle(device_name)

    def _on_tv_connection_failed(self, message: str) -> None:
        """Called when TV connection fails."""
        # Connection failed - dialog will still work but commands won't be sent
        pass

    def _disconnect_from_tv(self) -> None:
        """Disconnect from TV device."""
        if self._tv_client:
            try:
                self._tv_client.disconnect()
            except Exception:
                pass
            self._tv_client = None
        self._connected = False

    def _send_keycode_to_tv(self, keycode: str) -> None:
        """Send keycode to TV device."""
        if not self._connected or not self._tv_client:
            return
        
        # Store reference to client for thread safety
        client = self._tv_client
        
        def worker():
            try:
                # Send keycode using ADB shell
                # Map keycode name to numeric value
                keycode_map = {
                    "KEYCODE_DPAD_UP": 19,
                    "KEYCODE_DPAD_DOWN": 20,
                    "KEYCODE_DPAD_LEFT": 21,
                    "KEYCODE_DPAD_RIGHT": 22,
                    "KEYCODE_DPAD_CENTER": 23,
                }
                keycode_num = keycode_map.get(keycode)
                if keycode_num is not None and client:
                    client.shell(f"input keyevent {keycode_num}")
            except Exception as e:
                logger.error(f"Failed to send keycode {keycode} to TV: {e}")
                GLib.idle_add(self._on_tv_connection_failed, "Connection lost")
                GLib.idle_add(self._disconnect_from_tv)
        
        threading.Thread(target=worker, name="tv-keycode", daemon=True).start()

    def _flash_button(self, keycode: str) -> None:
        """Flash the button corresponding to the keycode."""
        btn = self._keycode_buttons.get(keycode)
        if not btn:
            return
        # Add a CSS class for the "pressed" state
        btn.add_css_class("suggested-action")

        # Remove the class after a short delay
        def remove_flash():
            btn.remove_css_class("suggested-action")
            return False  # Don't repeat

        GLib.timeout_add(150, remove_flash)

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        self._title_widget = Adw.WindowTitle(title="TV Remote", subtitle=self._tv_ip)
        header.set_title_widget(self._title_widget)
        toolbar_view.add_top_bar(header)

        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(BUTTON_CSS.encode())
        self.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_valign(Gtk.Align.CENTER)
        content.set_halign(Gtk.Align.CENTER)

        # D-pad grid
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_halign(Gtk.Align.CENTER)
        grid.set_valign(Gtk.Align.CENTER)

        # Map to store keycode -> button
        self._keycode_buttons: dict[str, Gtk.Button] = {}

        # D-pad buttons
        self._add_key_button("Up", "KEYCODE_DPAD_UP", 1, 0, grid, icon_name="keyboard_arrow_up-symbolic.svg")
        self._add_key_button("Left", "KEYCODE_DPAD_LEFT", 0, 1, grid, icon_name="keyboard_arrow_left-symbolic.svg")
        self._add_key_button("Enter", "KEYCODE_DPAD_CENTER", 1, 1, grid, icon_name="fiber_manual_record-symbolic.svg")
        self._add_key_button("Right", "KEYCODE_DPAD_RIGHT", 2, 1, grid, icon_name="keyboard_arrow_right-symbolic.svg")
        self._add_key_button("Down", "KEYCODE_DPAD_DOWN", 1, 2, grid, icon_name="keyboard_arrow_down-symbolic.svg")

        content.append(grid)

        toolbar_view.set_content(content)

    def _add_key_button(self, label: str, keycode: str, col: int, row: int, grid: Gtk.Grid, icon_name: str | None = None) -> None:
        """Add a key button to the grid."""
        btn = Gtk.Button()
        btn.add_css_class("tv-remote-button")
        btn.set_tooltip_text(label)
        btn.set_hexpand(True)
        btn.set_vexpand(True)
        
        btn.connect("clicked", lambda *_: self._send_keycode_to_tv(keycode))
        
        # Create icon or label
        if icon_name:
            if icon_name.endswith(".svg"):
                path = os.path.join(ICONS_DIR, icon_name)
                if os.path.exists(path):
                    file = Gio.File.new_for_path(path)
                    gicon = Gio.FileIcon.new(file)
                    image = Gtk.Image.new_from_gicon(gicon)
                    image.set_pixel_size(24)
                    btn.set_child(image)
                else:
                    btn.set_label(label)
            else:
                image = Gtk.Image.new_from_icon_name(icon_name)
                image.set_pixel_size(24)
                btn.set_child(image)
        else:
            btn.set_label(label)
        
        grid.attach(btn, col, row, 1, 1)
        self._keycode_buttons[keycode] = btn

