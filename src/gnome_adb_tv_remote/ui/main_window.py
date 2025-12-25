"""
Main Application Window.

This module contains the MainWindow class which serves as the primary window
for the TV Remote application. It coordinates device connections, remote control
input, and integrates with the scrcpy-server for low-latency input injection.
"""

from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..core.adb_client import AdbAuthRequiredError, AdbConnectError, AdbTcpClient, DeviceInfo  # noqa: E402
from ..core.scrcpy_controller import (  # noqa: E402
    ScrcpyServerController,
    ScrcpyConnectionError,
    ScrcpyError,
)
from .device_dialog import DeviceDialog  # noqa: E402
from .preferences_dialog import (  # noqa: E402
    PreferencesDialog,
    load_shortcuts_from_settings,
    get_focus_keyboard_keys,
    get_search_keys,
)
from .remote_panel import RemotePanel  # noqa: E402
from .info_dialog import InfoDialog  # noqa: E402
from .app_launcher_dialog import AppLauncherDialog  # noqa: E402
from .app_switcher_dialog import AppSwitcherDialog  # noqa: E402
from .tv_remote_dialog import TvRemoteDialog  # noqa: E402

logger = logging.getLogger(__name__)



class MainWindow(Adw.ApplicationWindow):
    """Main application window for TV Remote.
    
    Handles:
    - Device connection lifecycle (ADB and scrcpy-server)
    - Keyboard shortcut processing
    - Coordination between UI components (RemotePanel, DeviceDialog, PreferencesDialog)
    - Window state persistence
    """

    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="TV Remote")

        self._connected_ip: str | None = None
        self._adb: AdbTcpClient | None = None
        self._scrcpy: ScrcpyServerController | None = None
        self._connect_thread: threading.Thread | None = None
        self._connect_silent: bool = False
        self._device_dialog: DeviceDialog | None = None
        self._preferences_dialog: PreferencesDialog | None = None
        self._info_dialog: InfoDialog | None = None
        self._app_launcher_dialog: AppLauncherDialog | None = None
        self._app_switcher_dialog: AppSwitcherDialog | None = None
        self._tv_remote_dialog: TvRemoteDialog | None = None

        # Initialize GSettings
        self._settings = Gio.Settings.new("io.github.erenseymen.android-tv-remote")

        # Load window size
        width = self._settings.get_int("window-width")
        height = self._settings.get_int("window-height")
        self.set_default_size(width, height)
        if self._settings.get_boolean("window-is-maximized"):
            self.maximize()

        self.connect("close-request", self._on_close_request)

        # Load keyboard shortcuts from settings
        self._key_map: dict[int, str] = {}
        self._focus_keyboard_keys: list[int] = []
        self._search_keys: list[int] = []
        self.reload_shortcuts()

        self._build_ui()
        self._create_actions()
        self._remote_panel.set_handlers(
            on_keyevent=self._on_remote_keyevent,
            on_text=self._on_remote_text,
            on_volume_change=self._on_volume_change,
        )
        
        # Track current volume for slider changes
        self._current_volume: int = 0
        self._remote_panel.update_tooltips(self._settings)
        # Update Power button tooltip
        self.reload_shortcuts()
        
        # Load last connected IP and auto-connect
        self._auto_connect_last_ip()

    def _on_close_request(self, *_args) -> bool:
        """Save window state before closing."""
        is_maximized = self.is_maximized()

        if not is_maximized:
            width = self.get_width()
            height = self.get_height()
            self._settings.set_int("window-width", width)
            self._settings.set_int("window-height", height)

        self._settings.set_boolean("window-is-maximized", is_maximized)

        return False  # allow closing

    def reload_shortcuts(self) -> None:
        """Reload keyboard shortcuts from settings."""
        self._key_map = load_shortcuts_from_settings(self._settings)
        self._focus_keyboard_keys = get_focus_keyboard_keys(self._settings)
        self._search_keys = get_search_keys(self._settings)
        # Update button tooltips
        if hasattr(self, "_remote_panel"):
            self._remote_panel.update_tooltips(self._settings)
        # Update Power button tooltip
        if hasattr(self, "_power_button"):
            from .preferences_dialog import get_action_tooltip
            power_tooltip = get_action_tooltip("power", self._settings)
            if power_tooltip:
                self._power_button.set_tooltip_text(f"Power ({power_tooltip})")
            else:
                self._power_button.set_tooltip_text("Power")

    def _build_ui(self) -> None:
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self._toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        toolbar_view.add_top_bar(header)

        # Devices button in top bar
        devices_btn = Gtk.Button(icon_name="video-display-symbolic")
        devices_btn.set_tooltip_text("Manage devices")
        devices_btn.connect("clicked", self._on_devices_clicked)
        header.pack_start(devices_btn)

        # Info button in top bar
        info_btn = Gtk.Button(icon_name="help-about-symbolic")
        info_btn.set_tooltip_text("Instructions")
        info_btn.connect("clicked", self._on_info_clicked)
        header.pack_start(info_btn)

        # Power button in header bar
        self._power_button = Gtk.Button(icon_name="system-shutdown-symbolic")
        self._power_button.add_css_class("power-button")
        self._power_button.connect("clicked", lambda *_: self._on_remote_keyevent("KEYCODE_POWER"))
        header.pack_start(self._power_button)

        # Apply CSS for power button hover effect (red on hover)
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string("""
            button.power-button:hover {
                background-color: #e74c3c;
                color: white;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Preferences button
        prefs_btn = Gtk.Button(icon_name="preferences-system-symbolic")
        prefs_btn.set_tooltip_text("Configure Shortcuts")
        prefs_btn.connect("clicked", self._on_preferences_clicked)
        header.pack_end(prefs_btn)

        # App Launcher button
        self._app_launcher_btn = Gtk.Button(icon_name="view-app-grid-symbolic")
        self._app_launcher_btn.set_tooltip_text("Applications (Ctrl+A)")
        self._app_launcher_btn.connect("clicked", self._on_app_launcher_clicked)
        self._app_launcher_btn.set_sensitive(False)
        header.pack_end(self._app_launcher_btn)

        # App Switcher button
        self._app_switcher_btn = Gtk.Button(icon_name="view-paged-symbolic")
        self._app_switcher_btn.set_tooltip_text("Switch App (Ctrl+Tab)")
        self._app_switcher_btn.connect("clicked", self._on_app_switcher_clicked)
        self._app_switcher_btn.set_sensitive(False)
        header.pack_end(self._app_switcher_btn)


        # Content (remote)
        self._remote_panel = RemotePanel()
        toolbar_view.set_content(self._remote_panel)

        # Keyboard shortcuts controller
        # Use CAPTURE phase to catch keys before they're consumed by focused widgets
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        self._set_connected(False)

    def _on_devices_clicked(self, *_args) -> None:
        if self._device_dialog is None:
            self._device_dialog = DeviceDialog(self)
        else:
            self._device_dialog.update_last_ip()
        self._device_dialog.present()

    def _on_preferences_clicked(self, *_args) -> None:
        if self._preferences_dialog is None:
            self._preferences_dialog = PreferencesDialog(self)
        self._preferences_dialog.present(self)

    def _on_info_clicked(self, *_args) -> None:
        if self._info_dialog is None:
            self._info_dialog = InfoDialog(self)
        self._info_dialog.present()

    def _on_app_launcher_clicked(self, *_args) -> None:
        """Open the app launcher dialog."""
        if not self._adb or not self._adb.connected:
            self._toast("Not connected to a device.")
            return
        self._app_launcher_dialog = AppLauncherDialog(
            self._adb,
            on_launch=self._on_app_launch
        )
        self._app_launcher_dialog.present(self)

    def _on_app_switcher_clicked(self, *_args) -> None:
        """Open the app switcher dialog."""
        if not self._adb or not self._adb.connected:
            self._toast("Not connected to a device.")
            return
        self._app_switcher_dialog = AppSwitcherDialog(
            self._adb,
            on_switch=self._on_app_launch
        )
        self._app_switcher_dialog.present(self)

    def _on_app_launch(self, package_name: str) -> None:
        """Launch an app on the TV."""
        if not self._adb:
            return

        def worker():
            try:
                success = self._adb.launch_app(package_name)
                if success:
                    GLib.idle_add(self._toast, f"Launching {package_name.split('.')[-1]}...")
                else:
                    GLib.idle_add(self._toast, "Failed to launch app.")
            except Exception as e:
                logger.error(f"Failed to launch app: {e}")
                GLib.idle_add(self._toast, "Failed to launch app.")

        threading.Thread(target=worker, daemon=True).start()

    def _auto_connect_last_ip(self) -> None:
        """Load the last successfully connected IP address from settings and auto-connect."""
        last_ip = self._settings.get_string("last-connected-ip")
        if last_ip:
            # Automatically attempt connection after UI is fully initialized
            GLib.idle_add(lambda: self._connect_ip(last_ip, silent=True))

    def _save_last_ip(self, ip: str) -> None:
        """Save the successfully connected IP address to settings."""
        self._settings.set_string("last-connected-ip", ip)

    def _create_actions(self) -> None:
        connect_ip = Gio.SimpleAction.new("connect_ip", GLib.VariantType.new("s"))
        connect_ip.connect("activate", self._on_connect_ip_action)
        self.add_action(connect_ip)

        disconnect = Gio.SimpleAction.new("disconnect", None)
        disconnect.connect("activate", self._on_disconnect)
        self.add_action(disconnect)

    def _toast(self, text: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=text))

    def _set_connected(self, connected: bool, ip: str | None = None, *, scrcpy_ready: bool = False) -> None:
        self._connected_ip = ip if connected else None
        # Only enable buttons when scrcpy is ready
        self._remote_panel.set_sensitive(connected and scrcpy_ready)
        # App launcher/switcher buttons depend on ADB connection (not scrcpy)
        self._app_launcher_btn.set_sensitive(connected)
        self._app_switcher_btn.set_sensitive(connected)
        if not connected:
            self._remote_panel.update_device_info(None, None)
            # Cleanup scrcpy when disconnected
            if self._scrcpy:
                try:
                    self._scrcpy.disconnect()
                except Exception:
                    pass
                self._scrcpy = None

    def _on_connect_ip_action(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        """Handler for the connect_ip action."""
        ip = parameter.get_string()
        self._connect_ip(ip, silent=False)

    def _connect_ip_address(self, ip: str) -> None:
        """Called by DeviceDialog to initiate connection."""
        self._connect_ip(ip, silent=False)

    def _connect_ip(self, ip: str, *, silent: bool = False) -> None:
        """Connect to the given IP address.
        
        Args:
            ip: The IP address to connect to.
            silent: If True, suppress "Connecting..." notification (for auto-connect).
        """
        if not ip:
            return

        if self._connect_thread:
            if not silent:
                self._toast("Already connecting…")
            return

        # If already connected to another device, disconnect first.
        if self._adb:
            try:
                self._adb.disconnect()
            except Exception:
                pass
            self._adb = None
            self._set_connected(False)

        if not silent:
            self._toast(f"Connecting to {ip}:5555…")
        self._connect_silent = silent
        self._remote_panel.set_connection_status("Connecting…")
        client = AdbTcpClient(ip, port=5555, timeout_s=8.0)

        def worker() -> None:
            try:
                try:
                    client.connect()
                    # Get device info immediately after connection
                    device_info = client.get_device_info()
                except AdbAuthRequiredError as e:
                    GLib.idle_add(self._on_connect_failed_ui, str(e) or "Authorization required")
                    return
                except AdbConnectError as e:
                    GLib.idle_add(self._on_connect_failed_ui, str(e) or "Connection failed")
                    return
                except Exception as e:  # pragma: no cover
                    GLib.idle_add(self._on_connect_failed_ui, str(e) or "Connection failed")
                    return

                GLib.idle_add(self._on_connect_success_ui, ip, client, device_info)
            finally:
                GLib.idle_add(self._on_connect_done_ui)

        self._connect_thread = threading.Thread(target=worker, name="adb-connect", daemon=True)
        self._connect_thread.start()

    def _on_connect_success_ui(self, ip: str, client: AdbTcpClient, device_info: DeviceInfo) -> None:
        self._adb = client
        self._set_connected(True, ip=ip)
        self._remote_panel.update_device_info(device_info, ip)
        self._save_last_ip(ip)
        if not self._connect_silent:
            self._toast(f"Successfully connected to {ip}!")
        self._connect_silent = False

        # Start scrcpy in background for low-latency input
        self._start_scrcpy_async(ip)


    def _start_scrcpy_async(self, ip: str) -> None:
        """Start scrcpy-server controller in background thread for low-latency input.
        
        This uses direct communication with scrcpy-server on the device,
        which means NO WINDOW is opened - all control happens in the background.
        """
        def worker():
            try:
                # Pass the AdbTcpClient instance
                scrcpy = ScrcpyServerController(self._adb)
                scrcpy.set_disconnect_handler(
                    lambda: GLib.idle_add(self._on_scrcpy_disconnected)
                )
                scrcpy.connect()
                GLib.idle_add(self._on_scrcpy_connected, scrcpy)
            except ScrcpyError as e:
                logger.warning(f"scrcpy-server connection failed: {e}")
                GLib.idle_add(self._on_scrcpy_unavailable)
            except Exception as e:
                logger.warning(f"scrcpy error: {e}")
                GLib.idle_add(self._on_scrcpy_unavailable)

        threading.Thread(target=worker, name="scrcpy-connect", daemon=True).start()

    def _on_scrcpy_connected(self, scrcpy: ScrcpyServerController) -> None:
        """Called when scrcpy-server connects successfully."""
        self._scrcpy = scrcpy
        # Enable buttons when scrcpy is ready
        if self._connected_ip:
            self._remote_panel.set_sensitive(True)
        self._remote_panel.set_connection_status(None)  # Hide status on success
        logger.info("scrcpy-server connected - low-latency input enabled (no window)")
        
        # Fetch initial volume level
        self._update_volume_slider()

    def _on_scrcpy_unavailable(self) -> None:
        """Called when scrcpy is not available."""
        self._scrcpy = None
        self._remote_panel.set_connection_status(None)  # Hide status

    def _on_scrcpy_disconnected(self) -> None:
        """Called when scrcpy disconnects unexpectedly."""
        self._scrcpy = None
        logger.info("scrcpy disconnected")

    def _on_connect_failed_ui(self, msg: str) -> None:
        self._adb = None
        self._set_connected(False)
        self._remote_panel.set_connection_status(None)  # Hide status on failure
        self._toast(msg)

    def _on_connect_done_ui(self) -> None:
        self._connect_thread = None

    def _on_disconnect(self, *_args) -> None:
        if self._connect_thread:
            self._toast("Still connecting…")
            return
        # Disconnect scrcpy first
        if self._scrcpy:
            try:
                self._scrcpy.disconnect()
            except Exception:
                pass
            self._scrcpy = None
        # Then disconnect ADB
        if self._adb:
            try:
                self._adb.disconnect()
            except Exception:
                pass
            self._adb = None
        self._set_connected(False)
        self._toast("Disconnected from device.")

    def _on_key_pressed(self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, _state: Gdk.ModifierType) -> bool:
        """Handle global keyboard shortcuts."""
        # Handle Ctrl+Tab for app switcher (works even without scrcpy)
        if (_state & Gdk.ModifierType.CONTROL_MASK) and keyval == Gdk.KEY_Tab:
            if self._adb and self._adb.connected:
                self._on_app_switcher_clicked()
                return True
            return False

        # Handle Ctrl+A for app launcher (works even without scrcpy)
        if (_state & Gdk.ModifierType.CONTROL_MASK) and keyval in (Gdk.KEY_a, Gdk.KEY_A):
            if self._adb and self._adb.connected:
                self._on_app_launcher_clicked()
                return True
            return False

        # Ignore keyboard shortcuts if scrcpy is not ready
        scrcpy = self._scrcpy
        if not scrcpy or not scrcpy.connected:
            return False

        # If keyboard input mode is active, handle keys here (before Entry can consume them)
        if self._remote_panel.keyboard_focused:
            # Handle Ctrl+V for clipboard paste
            # We check for CONTROL_MASK and the 'v' key (both lower and upper case)
            if (_state & Gdk.ModifierType.CONTROL_MASK) and keyval in (Gdk.KEY_v, Gdk.KEY_V):
                self._paste_clipboard()
                return True
            return self._remote_panel.handle_keyboard_key(keyval)

        # If an entry/editable is focused (e.g., in DeviceDialog), don't intercept keys
        focus = self.get_focus()
        if focus and isinstance(focus, (Gtk.Editable, Gtk.Entry)):
            return False

        # Prepare lower-case keyval for fallback (handling Caps Lock)
        lower_keyval = Gdk.keyval_to_lower(keyval)

        # Handle focus keyboard shortcut (configurable)
        if keyval in self._focus_keyboard_keys or lower_keyval in self._focus_keyboard_keys:
            self._remote_panel.focus_keyboard()
            return True

        # Handle search shortcut (sends text "s" for YouTube search, then activates keyboard)
        if keyval in self._search_keys or lower_keyval in self._search_keys:
            self._on_remote_text("s")
            self._remote_panel.focus_keyboard()
            return True

        # Handle TV Input shortcut (T key)
        if keyval in (Gdk.KEY_t, Gdk.KEY_T):
            self._remote_panel.flash_button("KEYCODE_TV_INPUT")
            self._on_remote_keyevent("KEYCODE_TV_INPUT")
            return True

        # Handle keyboard shortcuts
        # Check original keyval first, then fallback to lower-case (ignores Caps Lock)
        keycode = self._key_map.get(keyval) or self._key_map.get(lower_keyval)

        if keycode:
            # Flash the button to show visual feedback
            self._remote_panel.flash_button(keycode)
            # Send the key event
            self._on_remote_keyevent(keycode)
            # Return True to stop event propagation (prevent default behavior)
            return True
        return False

    def _on_remote_keyevent(self, keycode: str) -> None:
        """Send a key event to the device using scrcpy-server.

        Requires scrcpy-server connection for low-latency input (~35-70ms).
        Special handling: If keycode is KEYCODE_TV_INPUT and TV IP is configured,
        open the TV remote dialog instead of sending a single command.
        """
        # Special handling for Input button: open TV remote dialog if configured
        if keycode == "KEYCODE_TV_INPUT":
            tv_ip = self._settings.get_string("tv-ip")
            if tv_ip and tv_ip.strip():
                self._open_tv_remote_dialog(tv_ip.strip())
                return
        
        scrcpy = self._scrcpy
        if not scrcpy or not scrcpy.connected:
            self._toast("Device is not connected.")
            return

        try:
            scrcpy.send_keycode(keycode)
            
            # Update volume slider when volume keys are pressed via keyboard shortcuts
            if keycode == "KEYCODE_VOLUME_UP":
                self._current_volume = min(self._current_volume + 1, self._remote_panel._volume_max)
                self._remote_panel.update_volume(self._current_volume, self._remote_panel._volume_max, False)
            elif keycode == "KEYCODE_VOLUME_DOWN":
                self._current_volume = max(self._current_volume - 1, 0)
                self._remote_panel.update_volume(self._current_volume, self._remote_panel._volume_max, False)
        except Exception as e:
            logger.error(f"scrcpy keyevent failed: {e}")
            self._toast("Failed to send command to TV.")

    def _on_remote_text(self, text: str) -> None:
        """Send text input to the device using scrcpy-server.

        Requires scrcpy-server connection for low-latency input.
        """
        scrcpy = self._scrcpy
        if not scrcpy or not scrcpy.connected:
            self._toast("Device is not connected.")
            return

        try:
            scrcpy.send_text(text)
        except Exception as e:
            logger.error(f"scrcpy text input failed: {e}")
            self._toast("Failed to send text input to TV.")

    def _open_tv_remote_dialog(self, tv_ip: str) -> None:
        """Open the TV remote dialog for controlling the external TV device.
        
        This is used when a TV IP is configured separately from the connected device
        (e.g., when connected to Mi Box but want to control TV Input).
        """
        # Close existing dialog if open
        if self._tv_remote_dialog:
            self._tv_remote_dialog.close()
        
        # Create and show new dialog
        self._tv_remote_dialog = TvRemoteDialog(self, tv_ip, self._settings)
        self._tv_remote_dialog.present()

    def _paste_clipboard(self) -> None:
        """Read text from clipboard and send it to the device."""
        display = Gdk.Display.get_default()
        if not display:
            return
        clipboard = display.get_clipboard()
        # In Gtk 4, clipboard reading is asynchronous
        clipboard.read_text_async(None, self._on_clipboard_read_ready, None)

    def _on_clipboard_read_ready(self, clipboard: Gdk.Clipboard, result: Gio.AsyncResult, _data: None) -> None:
        """Callback for clipboard.read_text_async."""
        try:
            text = clipboard.read_text_finish(result)
            if text:
                self._on_remote_text(text)
        except Exception as e:
            logger.error(f"Failed to read clipboard: {e}")

    def _update_volume_slider(self) -> None:
        """Fetch volume level from device and update the slider."""
        if not self._adb or not self._adb.connected:
            return
        
        def worker():
            try:
                current, max_vol, is_muted = self._adb.get_volume_level()
                GLib.idle_add(self._on_volume_fetched, current, max_vol, is_muted)
            except Exception as e:
                logger.error(f"Failed to get volume level: {e}")
        
        threading.Thread(target=worker, daemon=True).start()

    def _on_volume_fetched(self, current: int, max_vol: int, is_muted: bool) -> None:
        """Called when volume level is fetched from device."""
        self._current_volume = current
        self._remote_panel.update_volume(current, max_vol, is_muted)

    def _on_volume_change(self, new_volume: int) -> None:
        """Handle volume slider change.
        
        Since Android doesn't have a direct "set volume" command via scrcpy,
        we send VOLUME_UP or VOLUME_DOWN events to adjust the volume.
        """
        scrcpy = self._scrcpy
        if not scrcpy or not scrcpy.connected:
            return
        
        diff = new_volume - self._current_volume
        keycode = "KEYCODE_VOLUME_UP" if diff > 0 else "KEYCODE_VOLUME_DOWN"
        
        try:
            for _ in range(abs(diff)):
                scrcpy.send_keycode(keycode)
            self._current_volume = new_volume
        except Exception as e:
            logger.error(f"Failed to adjust volume: {e}")
