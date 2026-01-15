"""
Main Application Window.

This module contains the MainWindow class which serves as the primary window
for the TV Remote application. It coordinates device connections, remote control
input, and integrates with the scrcpy-server for low-latency input injection.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..core.adb_client import AdbAuthRequiredError, AdbConnectError, AdbTcpClient, DeviceInfo  # noqa: E402
from ..core.scanner import SubnetScanner, HostFound, ScanProgress  # noqa: E402
from ..core.network_info import get_ipv4_interface_networks  # noqa: E402
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
from .input_device_dialog import InputDeviceDialog  # noqa: E402
from ..core.mpris_service import MprisService  # noqa: E402

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
        # Secondary scrcpy connection for TV Input Routing
        self._tv_adb: AdbTcpClient | None = None
        self._tv_scrcpy: ScrcpyServerController | None = None
        self._connect_thread: threading.Thread | None = None
        self._connect_silent: bool = False
        self._device_dialog: DeviceDialog | None = None
        self._preferences_dialog: PreferencesDialog | None = None
        self._info_dialog: InfoDialog | None = None
        self._app_launcher_dialog: AppLauncherDialog | None = None
        self._app_switcher_dialog: AppSwitcherDialog | None = None
        self._tv_remote_dialog: TvRemoteDialog | None = None
        self._tv_device_info: DeviceInfo | None = None
        self._tv_scrcpy_required: bool = False  # True when TV scrcpy is needed but not yet connected
        self._ip_discovery_in_progress: bool = False  # Flag to prevent reconnect loop during IP discovery
        self._tv_discovery_attempted: bool = False  # Flag to prevent retrying TV discovery infinitely
        self._device_has_input_support: bool = True  # Whether connected device has native TV Input support
        self._input_device_dialog: InputDeviceDialog | None = None
        self._pending_tv_remote_dialog_ip: str | None = None  # IP to open TV remote dialog for after connection
        
        # Initialize MPRIS service for desktop media control integration
        self._mpris = MprisService(
            on_play_pause=self._on_mpris_play_pause,
            on_play=self._on_mpris_play,
            on_pause=self._on_mpris_pause,
            on_stop=self._on_mpris_stop,
            on_next=self._on_mpris_next,
            on_previous=self._on_mpris_previous,
            on_raise=self._on_mpris_raise,
            on_quit=self._on_mpris_quit,
        )
        self._mpris.start()
        self._mpris_poll_timer_id: int = 0  # Timer ID for media info polling

        # Initialize GSettings
        self._settings = Gio.Settings.new("io.github.erenseymen.android-tv-remote")

        # Load window size
        width = self._settings.get_int("window-width")
        height = self._settings.get_int("window-height")
        self.set_default_size(width, height)
        
        # Set minimum window size to ensure all controls remain visible
        self.set_size_request(350, 680)
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
            on_app_launcher=self._on_app_launcher_clicked,
            on_app_switcher=self._on_app_switcher_clicked,
        )
        
        # Track current volume for slider changes
        self._current_volume: int = 0
        self._last_volume_change_time: float = 0.0
        self._remote_panel.update_tooltips(self._settings)
        # Update Power button tooltip
        self.reload_shortcuts()
        
        # Load last connected IP and auto-connect
        self._auto_connect_last_ip()
        
        # Listen for TV IP setting changes
        self._settings.connect("changed::tv-ip", self._on_tv_ip_setting_changed)

    def _on_close_request(self, *_args) -> bool:
        """Save window state before closing."""
        is_maximized = self.is_maximized()

        if not is_maximized:
            width = self.get_width()
            height = self.get_height()
            self._settings.set_int("window-width", width)
            self._settings.set_int("window-height", height)

        self._settings.set_boolean("window-is-maximized", is_maximized)
        
        # Stop MPRIS media polling and service
        self._stop_mpris_media_polling()
        self._mpris.stop()

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
        """Load the last successfully connected IP address from settings and auto-connect.
        
        If connection fails, triggers network discovery to find paired devices
        that may have changed IP addresses.
        """
        last_ip = self._settings.get_string("last-connected-ip")
        if last_ip:
            # Automatically attempt connection after UI is fully initialized
            GLib.idle_add(lambda: (self._connect_ip_with_discovery_fallback(last_ip), False)[1])
    
    def _connect_ip_with_discovery_fallback(self, ip: str) -> None:
        """Attempt to connect to IP, falling back to IP discovery on failure.
        
        This is used for auto-connect on startup. If the saved IP is no longer
        reachable, we scan the network to find paired devices that may have
        changed IP addresses.
        """
        if not ip:
            return
        
        if self._connect_thread:
            return
        
        self._connect_silent = True
        self._remote_panel.set_connection_status("Connecting…")
        client = AdbTcpClient(ip, port=5555, timeout_s=8.0)
        
        def worker() -> None:
            try:
                try:
                    client.connect()
                    device_info = client.get_device_info()
                except (AdbAuthRequiredError, AdbConnectError, Exception):
                    # Connection failed - start IP discovery in background
                    GLib.idle_add(self._on_auto_connect_failed_start_discovery)
                    return
                
                GLib.idle_add(self._on_connect_success_ui, ip, client, device_info)
            finally:
                GLib.idle_add(self._on_connect_done_ui)
        
        self._connect_thread = threading.Thread(target=worker, name="adb-auto-connect", daemon=True)
        self._connect_thread.start()
    
    def _on_auto_connect_failed_start_discovery(self) -> None:
        """Called when auto-connect fails. Starts network discovery to find paired devices."""
        self._connect_thread = None
        self._connect_silent = False
        self._remote_panel.set_connection_status("Searching for device…")
        logger.info("Auto-connect failed, starting network discovery for paired devices")
        
        # Start discovery in background thread
        threading.Thread(
            target=self._discover_and_update_device_ips,
            name="ip-discovery",
            daemon=True
        ).start()
    
    def _discover_and_update_device_ips(self) -> None:
        """Scan network for paired devices and update stored IPs.
        
        This runs in a background thread. It:
        1. Scans for devices with ADB port open
        2. Checks which ones are paired using is_paired_silent
        3. Gets device info for paired devices
        4. Matches device names with stored discovered-devices
        5. Updates both last-connected-ip and tv-ip if their devices are found
        6. Attempts to connect to the previously saved device
        """
        # Load stored device info
        stored_devices_json = self._settings.get_string("discovered-devices")
        stored_devices: list[dict] = []
        try:
            if stored_devices_json:
                stored_devices = json.loads(stored_devices_json)
        except Exception:
            pass
        
        # Get last connected device's model (if we have it stored)
        last_ip = self._settings.get_string("last-connected-ip")
        last_device_model: str | None = None
        for dev in stored_devices:
            if dev.get("ip") == last_ip:
                last_device_model = dev.get("model")
                break
        
        # Get TV IP device's model (if we have it stored)
        tv_ip = self._settings.get_string("tv-ip")
        tv_device_model: str | None = None
        if tv_ip:
            for dev in stored_devices:
                if dev.get("ip") == tv_ip:
                    tv_device_model = dev.get("model")
                    break
        
        # Get networks to scan
        nets = [n.network for n in get_ipv4_interface_networks(limit_to_slash24_if_broader=True)]
        if not nets:
            GLib.idle_add(self._on_discovery_complete, None, None, "No networks found")
            return
        
        # Scan for devices
        scanner = SubnetScanner(port=5555, timeout_s=0.35, concurrency=256)
        found_hosts: list[HostFound] = []
        
        def on_found(host: HostFound) -> None:
            found_hosts.append(host)
        
        try:
            scanner.scan(nets, on_found=on_found)
        except Exception as e:
            logger.error(f"Network scan failed: {e}")
            GLib.idle_add(self._on_discovery_complete, None, None, "Scan failed")
            return
        
        if not found_hosts:
            GLib.idle_add(self._on_discovery_complete, None, None, "No devices found")
            return
        
        # Check each found device for pairing status and get device info
        paired_devices: list[dict] = []
        new_ip_for_last_device: str | None = None
        new_ip_for_tv_device: str | None = None
        
        for host in found_hosts:
            ip = str(host.ip)
            try:
                client = AdbTcpClient(ip, port=5555, timeout_s=3.0)
                if not client.is_paired_silent():
                    continue
                
                # Device is paired - get its info
                try:
                    client.connect()
                    device_info = client.get_device_info()
                    client.disconnect()
                except Exception:
                    device_info = None
                
                device_data = {
                    "ip": ip,
                    "latency_ms": host.latency_ms,
                    "model": device_info.model if device_info else None,
                    "version": device_info.version if device_info else None,
                }
                paired_devices.append(device_data)
                
                # Check if this matches our last connected device
                if last_device_model and device_info and device_info.model == last_device_model:
                    new_ip_for_last_device = ip
                    logger.info(f"Found main device '{last_device_model}' at new IP: {ip}")
                
                # Check if this matches our TV device
                if tv_device_model and device_info and device_info.model == tv_device_model:
                    new_ip_for_tv_device = ip
                    logger.info(f"Found TV device '{tv_device_model}' at new IP: {ip}")
                
            except Exception as e:
                logger.debug(f"Failed to check device at {ip}: {e}")
                continue
        
        # Update stored devices with new IP addresses
        if paired_devices:
            # Build a map of model -> new IP from paired devices
            model_to_new_ip: dict[str, str] = {}
            for pd in paired_devices:
                if pd.get("model"):
                    model_to_new_ip[pd["model"]] = pd["ip"]
            
            # Update stored devices
            updated_devices: list[dict] = []
            for stored_dev in stored_devices:
                stored_model = stored_dev.get("model")
                if stored_model and stored_model in model_to_new_ip:
                    # Update IP
                    stored_dev["ip"] = model_to_new_ip[stored_model]
                    # Find latency from paired_devices
                    for pd in paired_devices:
                        if pd.get("model") == stored_model:
                            stored_dev["latency_ms"] = pd.get("latency_ms", 0)
                            break
                updated_devices.append(stored_dev)
            
            # Also add any new paired devices not in stored list
            stored_models = {d.get("model") for d in stored_devices if d.get("model")}
            for pd in paired_devices:
                if pd.get("model") and pd["model"] not in stored_models:
                    updated_devices.append(pd)
            
            # Save updated devices - wrap in function that returns False to prevent GLib loop
            def save_devices():
                self._settings.set_string("discovered-devices", json.dumps(updated_devices))
                return False
            GLib.idle_add(save_devices)
        
        # Update TV IP if found at new address
        # Set flag to prevent _on_tv_ip_setting_changed from triggering reconnection loop
        if new_ip_for_tv_device and new_ip_for_tv_device != tv_ip:
            def update_tv_ip(new_tv_ip: str) -> None:
                self._ip_discovery_in_progress = True
                self._settings.set_string("tv-ip", new_tv_ip)
                self._ip_discovery_in_progress = False
                return False  # For GLib.idle_add compatibility
            GLib.idle_add(update_tv_ip, new_ip_for_tv_device)
            logger.info(f"Updated tv-ip from {tv_ip} to {new_ip_for_tv_device}")
        
        # If we found the last connected device at a new IP, update and connect
        if new_ip_for_last_device and new_ip_for_last_device != last_ip:
            GLib.idle_add(self._save_last_ip, new_ip_for_last_device)
            GLib.idle_add(self._on_discovery_complete, new_ip_for_last_device, new_ip_for_tv_device, None)
        elif paired_devices:
            # Connect to first available paired device
            first_ip = paired_devices[0]["ip"]
            GLib.idle_add(self._on_discovery_complete, first_ip, new_ip_for_tv_device, None)
        else:
            GLib.idle_add(self._on_discovery_complete, None, new_ip_for_tv_device, "No paired devices found")
    
    def _on_discovery_complete(self, found_ip: str | None, found_tv_ip: str | None, error_msg: str | None) -> None:
        """Called when IP discovery completes.
        
        Args:
            found_ip: New IP for main device (last-connected-ip)
            found_tv_ip: New IP for TV device (tv-ip)
            error_msg: Error message if discovery failed
        """
        self._remote_panel.set_connection_status(None)
        
        if error_msg:
            logger.info(f"IP discovery: {error_msg}")
            return
        
        if found_tv_ip:
            logger.info(f"IP discovery updated TV device IP to {found_tv_ip}")
        
        if found_ip:
            logger.info(f"IP discovery found device at {found_ip}, connecting...")
            self._connect_ip(found_ip, silent=False)

    def _save_last_ip(self, ip: str) -> None:
        """Save the successfully connected IP address to settings."""
        self._settings.set_string("last-connected-ip", ip)
        return False  # For GLib.idle_add compatibility

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
        self._remote_panel.set_app_buttons_sensitive(connected)
        if not connected:
            self._remote_panel.update_device_info(None, None)
            # Cleanup scrcpy when disconnected
            if self._scrcpy:
                try:
                    self._scrcpy.disconnect()
                except Exception:
                    pass
                self._scrcpy = None
            # Also cleanup TV scrcpy if exists
            if self._tv_scrcpy:
                try:
                    self._tv_scrcpy.disconnect()
                except Exception:
                    pass
                self._tv_scrcpy = None
            if self._tv_adb:
                try:
                    self._tv_adb.disconnect()
                except Exception:
                    pass
                self._tv_adb = None

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
            # Update MPRIS with device connection (get device name if available)
            device_name = "Android TV"
            if self._adb:
                try:
                    device_info = self._adb.get_device_info()
                    if device_info and device_info.model:
                        device_name = device_info.model
                except Exception:
                    pass
            self._mpris.set_device_connected(True, device_name)
            
            # Start MPRIS media info polling (every 3 seconds)
            self._start_mpris_media_polling()
        self._remote_panel.set_connection_status(None)  # Hide status on success
        logger.info("scrcpy-server connected - low-latency input enabled (no window)")
        
        # Fetch initial volume level
        self._update_volume_slider()
        
        # Check if device supports TV Input in background
        self._check_tv_input_support_async()
        
        # Start secondary scrcpy connection for TV Input Routing if configured
        # Skip if TV IP is the same as connected device (no separate routing needed)
        tv_ip = self._settings.get_string("tv-ip")
        if tv_ip and tv_ip.strip() and tv_ip.strip() != self._connected_ip:
            # Disable Input button until TV scrcpy connects
            self._tv_scrcpy_required = True
            self._tv_discovery_attempted = False  # Reset discovery flag for fresh connection attempt
            self._remote_panel.set_input_button_sensitive(False)
            self._start_tv_scrcpy_async(tv_ip.strip())
        else:
            self._tv_scrcpy_required = False

    def _check_tv_input_support_async(self) -> None:
        """Check if connected device has TV Input support in background thread."""
        adb = self._adb
        if not adb:
            return
        
        def worker():
            try:
                has_support = adb.has_tv_input_support()
                GLib.idle_add(self._on_tv_input_support_checked, has_support)
            except Exception as e:
                logger.debug(f"Failed to check TV Input support: {e}")
                # Assume supported if check fails
                GLib.idle_add(self._on_tv_input_support_checked, True)
        
        threading.Thread(target=worker, name="tv-input-check", daemon=True).start()

    def _on_tv_input_support_checked(self, has_support: bool) -> bool:
        """Called when TV Input support check completes.
        
        Args:
            has_support: Whether the device has native TV Input support.
            
        Returns:
            False for GLib.idle_add compatibility.
        """
        self._device_has_input_support = has_support
        
        if not has_support:
            # Device doesn't support Input - dim the button
            self._remote_panel.set_input_button_dimmed(True)
            logger.info("Connected device doesn't support TV Input - button dimmed")
        else:
            self._remote_panel.set_input_button_dimmed(False)
        
        return False

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
        # Stop MPRIS media polling
        self._stop_mpris_media_polling()
        # Disconnect scrcpy first
        if self._scrcpy:
            try:
                self._scrcpy.disconnect()
            except Exception:
                pass
            self._scrcpy = None
        # Disconnect TV scrcpy if exists
        if self._tv_scrcpy:
            try:
                self._tv_scrcpy.disconnect()
            except Exception:
                pass
            self._tv_scrcpy = None
        if self._tv_adb:
            try:
                self._tv_adb.disconnect()
            except Exception:
                pass
            self._tv_adb = None
        # Then disconnect ADB
        if self._adb:
            try:
                self._adb.disconnect()
            except Exception:
                pass
            self._adb = None
        self._set_connected(False)
        # Update MPRIS to reflect disconnection
        self._mpris.set_device_connected(False)
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
        # Skip if TV scrcpy is required but not yet connected
        if keyval in (Gdk.KEY_t, Gdk.KEY_T):
            if self._tv_scrcpy_required:
                return True  # Ignore keypress while TV scrcpy is connecting
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
        Special handling: If keycode is KEYCODE_TV_INPUT and TV scrcpy is connected,
        send command directly to TV device for faster response.
        """
        # Special handling for Input button
        if keycode == "KEYCODE_TV_INPUT":
            tv_ip = self._settings.get_string("tv-ip")
            
            # If device doesn't support Input and no TV IP configured, show device selection dialog
            if not self._device_has_input_support and (not tv_ip or not tv_ip.strip() or tv_ip.strip() == self._connected_ip):
                self._open_input_device_dialog()
                return
            
            # If TV IP is configured and different from connected device, open TV remote dialog
            if tv_ip and tv_ip.strip() and tv_ip.strip() != self._connected_ip:
                # Open dialog - it will send Input command automatically when connected
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
        # Destroy existing dialog if it exists
        if self._tv_remote_dialog:
            self._tv_remote_dialog.destroy()
            self._tv_remote_dialog = None
        
        # Always create a fresh dialog, passing TV scrcpy for fast commands
        self._tv_remote_dialog = TvRemoteDialog(self, tv_ip, self._settings, self._tv_scrcpy, self._tv_device_info)
        self._tv_remote_dialog.present()

    def _open_input_device_dialog(self) -> None:
        """Open the Input Device Selection dialog.
        
        This is shown when the connected device doesn't support TV Input
        and no alternative TV is configured. Allows user to select
        a device with Input support from discovered devices.
        """
        # Close existing dialog if any
        if self._input_device_dialog:
            self._input_device_dialog.close()
            self._input_device_dialog = None
        
        self._input_device_dialog = InputDeviceDialog(
            settings=self._settings,
            on_device_selected=self._on_input_device_selected,
        )
        self._input_device_dialog.present(self)

    def _on_input_device_selected(self, ip: str) -> None:
        """Called when user selects a device in the Input Device Selection dialog.
        
        Args:
            ip: IP address of the selected device.
        """
        # Start TV scrcpy connection to selected device
        self._tv_scrcpy_required = True
        self._remote_panel.set_input_button_sensitive(False)
        # Set flag to open TV remote dialog after connection
        self._pending_tv_remote_dialog_ip = ip
        self._start_tv_scrcpy_async(ip)

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
                # Display pasted text in the keyboard entry
                self._remote_panel.append_text(text)
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
        # Skip updating if user recently changed volume (within 1 second)
        # This prevents the slider from jumping back to old values
        if time.time() - self._last_volume_change_time < 1.0:
            return
        
        self._current_volume = current
        self._remote_panel.update_volume(current, max_vol, is_muted)
        # Update MPRIS volume (0.0 to 1.0 range)
        if max_vol > 0:
            mpris_volume = current / max_vol
            self._mpris.set_volume(mpris_volume)

    def _on_volume_change(self, new_volume: int) -> None:
        """Handle volume slider change.
        
        Since Android doesn't have a direct "set volume" command via scrcpy,
        we send VOLUME_UP or VOLUME_DOWN events to adjust the volume.
        """
        scrcpy = self._scrcpy
        if not scrcpy or not scrcpy.connected:
            return
        
        # Record the time of this volume change
        self._last_volume_change_time = time.time()
        
        diff = new_volume - self._current_volume
        if diff == 0:
            return
            
        keycode = "KEYCODE_VOLUME_UP" if diff > 0 else "KEYCODE_VOLUME_DOWN"
        
        try:
            for _ in range(abs(diff)):
                scrcpy.send_keycode(keycode)
            self._current_volume = new_volume
        except Exception as e:
            logger.error(f"Failed to adjust volume: {e}")

    def _start_tv_scrcpy_async(self, tv_ip: str) -> None:
        """Start scrcpy-server for TV Input Routing in background.
        
        This establishes a second scrcpy connection to the TV device specified
        in settings, enabling faster Input button operations.
        """
        def worker():
            try:
                # Create ADB client for TV device
                tv_client = AdbTcpClient(tv_ip, port=5555, timeout_s=8.0)
                tv_client.connect()
                
                # Get device info for display in dialog
                tv_device_info = tv_client.get_device_info()
                
                # Create scrcpy controller for TV
                tv_scrcpy = ScrcpyServerController(tv_client)
                tv_scrcpy.connect()
                
                GLib.idle_add(self._on_tv_scrcpy_connected, tv_client, tv_scrcpy, tv_device_info)
            except Exception as e:
                logger.warning(f"TV scrcpy connection failed for {tv_ip}: {e}")
                GLib.idle_add(self._on_tv_scrcpy_failed)
        
        threading.Thread(target=worker, name="tv-scrcpy-connect", daemon=True).start()
    
    def _on_tv_scrcpy_connected(self, tv_adb: AdbTcpClient, tv_scrcpy: ScrcpyServerController, tv_device_info: DeviceInfo) -> None:
        """Called when TV scrcpy connects successfully."""
        self._tv_adb = tv_adb
        self._tv_scrcpy = tv_scrcpy
        self._tv_device_info = tv_device_info
        self._tv_scrcpy_required = False  # Connection established
        # Enable Input button now that TV scrcpy is ready
        self._remote_panel.set_input_button_sensitive(True)
        # Update tooltip to show connected TV device (manufacturer + model)
        if tv_device_info and tv_device_info.manufacturer and tv_device_info.model:
            device_name = f"{tv_device_info.manufacturer} {tv_device_info.model}"
        elif tv_device_info and tv_device_info.model:
            device_name = tv_device_info.model
        else:
            device_name = tv_adb.host
        self._remote_panel.set_input_button_tooltip(f"Input ({device_name})")
        logger.info(f"TV scrcpy connected to {tv_adb.host} ({device_name}) - Input button will use fast connection")
        
        # Store TV device model info to discovered-devices for future IP discovery
        if tv_device_info and tv_device_info.model:
            self._store_tv_device_model(tv_adb.host, tv_device_info)
        
        # If we have a pending TV remote dialog to open, do it now
        if self._pending_tv_remote_dialog_ip:
            ip = self._pending_tv_remote_dialog_ip
            self._pending_tv_remote_dialog_ip = None
            self._open_tv_remote_dialog(ip)
    
    def _store_tv_device_model(self, ip: str, device_info: DeviceInfo) -> None:
        """Store TV device model info to discovered-devices for future IP discovery.
        
        This ensures that when the TV device's IP changes, we can identify it
        by its model name during network discovery.
        
        Args:
            ip: The TV device's IP address.
            device_info: Device info containing model, version, etc.
        """
        stored_devices_json = self._settings.get_string("discovered-devices")
        stored_devices: list[dict] = []
        try:
            if stored_devices_json:
                stored_devices = json.loads(stored_devices_json)
        except Exception:
            pass
        
        # Check if this IP already exists in stored devices
        found = False
        for dev in stored_devices:
            if dev.get("ip") == ip:
                # Update model info
                dev["model"] = device_info.model
                if device_info.version:
                    dev["version"] = device_info.version
                found = True
                break
        
        # If not found, add as new entry
        if not found:
            stored_devices.append({
                "ip": ip,
                "model": device_info.model,
                "version": device_info.version,
                "latency_ms": 0,  # Unknown latency
            })
        
        # Save updated devices
        self._settings.set_string("discovered-devices", json.dumps(stored_devices))
        logger.info(f"Stored TV device model '{device_info.model}' for IP {ip}")

    
    def _on_tv_scrcpy_failed(self) -> None:
        """Called when TV scrcpy fails to connect.
        
        Triggers IP discovery to find the TV device at its new IP address,
        then retries the connection. Only attempts discovery once per connection
        session to prevent infinite loops if the device is offline.
        """
        # Check if we already tried discovery - if so, the device is likely offline
        if self._tv_discovery_attempted:
            logger.info("TV scrcpy failed after discovery - device likely offline")
            self._tv_scrcpy_required = False
            self._pending_tv_remote_dialog_ip = None
            self._remote_panel.set_input_button_sensitive(True)
            self._remote_panel.set_input_button_tooltip("Input (TV offline)")
            return
        
        self._tv_discovery_attempted = True
        logger.info("TV scrcpy connection failed - starting IP discovery for TV device")
        
        # Keep Input button disabled during discovery
        self._remote_panel.set_input_button_sensitive(False)
        self._remote_panel.set_input_button_tooltip("Searching for TV device…")
        
        # Start discovery in background thread
        threading.Thread(
            target=self._discover_tv_device_ip,
            name="tv-ip-discovery",
            daemon=True
        ).start()
    
    def _discover_tv_device_ip(self) -> None:
        """Scan network to find the TV device's new IP address.
        
        This runs in a background thread. It:
        1. Gets the stored TV device model from settings
        2. Scans for devices with ADB port open
        3. Checks which ones are paired and matches the TV device model
        4. Updates tv-ip setting and retries connection
        """
        # Load stored device info to get TV device model
        stored_devices_json = self._settings.get_string("discovered-devices")
        stored_devices: list[dict] = []
        try:
            if stored_devices_json:
                stored_devices = json.loads(stored_devices_json)
        except Exception:
            pass
        
        # Get TV IP device's model (if we have it stored)
        tv_ip = self._settings.get_string("tv-ip")
        tv_device_model: str | None = None
        if tv_ip:
            for dev in stored_devices:
                if dev.get("ip") == tv_ip:
                    tv_device_model = dev.get("model")
                    break
        
        if not tv_device_model:
            logger.warning("Cannot discover TV device - no model info stored")
            GLib.idle_add(self._on_tv_discovery_complete, None)
            return
        
        # Get networks to scan
        nets = [n.network for n in get_ipv4_interface_networks(limit_to_slash24_if_broader=True)]
        if not nets:
            logger.warning("No networks found for TV device discovery")
            GLib.idle_add(self._on_tv_discovery_complete, None)
            return
        
        # Scan for devices
        scanner = SubnetScanner(port=5555, timeout_s=0.35, concurrency=256)
        found_hosts: list[HostFound] = []
        
        def on_found(host: HostFound) -> None:
            found_hosts.append(host)
        
        try:
            scanner.scan(nets, on_found=on_found)
        except Exception as e:
            logger.error(f"Network scan for TV device failed: {e}")
            GLib.idle_add(self._on_tv_discovery_complete, None)
            return
        
        if not found_hosts:
            logger.info("No devices found during TV device discovery")
            GLib.idle_add(self._on_tv_discovery_complete, None)
            return
        
        # Check each found device for pairing status and match model
        new_tv_ip: str | None = None
        
        for host in found_hosts:
            ip = str(host.ip)
            try:
                client = AdbTcpClient(ip, port=5555, timeout_s=3.0)
                if not client.is_paired_silent():
                    continue
                
                # Device is paired - check if it matches our TV device
                try:
                    client.connect()
                    device_info = client.get_device_info()
                    client.disconnect()
                except Exception:
                    continue
                
                if device_info and device_info.model == tv_device_model:
                    new_tv_ip = ip
                    logger.info(f"Found TV device '{tv_device_model}' at new IP: {ip}")
                    break
                
            except Exception as e:
                logger.debug(f"Failed to check device at {ip}: {e}")
                continue
        
        # Update tv-ip setting if found at new address
        if new_tv_ip and new_tv_ip != tv_ip:
            def update_tv_ip_setting() -> bool:
                self._ip_discovery_in_progress = True
                self._settings.set_string("tv-ip", new_tv_ip)
                self._ip_discovery_in_progress = False
                return False
            GLib.idle_add(update_tv_ip_setting)
            
            # Also update stored devices
            for dev in stored_devices:
                if dev.get("model") == tv_device_model:
                    dev["ip"] = new_tv_ip
                    break
            GLib.idle_add(
                lambda: (self._settings.set_string("discovered-devices", json.dumps(stored_devices)), False)[1]
            )
            
            logger.info(f"Updated tv-ip from {tv_ip} to {new_tv_ip}")
        
        GLib.idle_add(self._on_tv_discovery_complete, new_tv_ip)
    
    def _on_tv_discovery_complete(self, new_tv_ip: str | None) -> bool:
        """Called when TV device IP discovery completes.
        
        Args:
            new_tv_ip: New IP for TV device, or None if not found.
            
        Returns:
            False for GLib.idle_add compatibility.
        """
        if new_tv_ip:
            logger.info(f"TV device found at {new_tv_ip}, retrying connection...")
            # Retry TV scrcpy connection with new IP
            self._tv_scrcpy_required = True
            self._remote_panel.set_input_button_tooltip("Connecting to TV…")
            self._start_tv_scrcpy_async(new_tv_ip)
        else:
            # Discovery failed - give up on TV connection
            self._tv_scrcpy_required = False
            self._pending_tv_remote_dialog_ip = None
            self._remote_panel.set_input_button_sensitive(True)
            self._remote_panel.set_input_button_tooltip("Input")
            logger.info("TV device not found - Input button will use normal mode")
        
        return False

    def _on_tv_ip_setting_changed(self, settings: Gio.Settings, key: str) -> None:
        """Called when TV IP setting changes - reconnect TV scrcpy if needed."""
        # Skip if this change is from IP discovery (to prevent reconnection loop)
        if self._ip_discovery_in_progress:
            return
        
        # Only process if we have an active main connection
        if not self._scrcpy or not self._scrcpy.connected:
            return
        
        # Disconnect existing TV scrcpy
        if self._tv_scrcpy:
            try:
                self._tv_scrcpy.disconnect()
            except Exception:
                pass
            self._tv_scrcpy = None
        if self._tv_adb:
            try:
                self._tv_adb.disconnect()
            except Exception:
                pass
            self._tv_adb = None
        self._tv_device_info = None
        
        # Get new TV IP
        tv_ip = settings.get_string("tv-ip")
        
        # Start new connection if TV IP is set and different from connected device
        if tv_ip and tv_ip.strip() and tv_ip.strip() != self._connected_ip:
            # Disable Input button until TV scrcpy connects
            self._tv_scrcpy_required = True
            self._tv_discovery_attempted = False  # Reset discovery flag for fresh connection attempt
            self._remote_panel.set_input_button_sensitive(False)
            self._start_tv_scrcpy_async(tv_ip.strip())
            logger.info(f"TV IP changed to {tv_ip} - reconnecting TV scrcpy")
        else:
            # No TV routing needed - enable Input button
            self._tv_scrcpy_required = False
            self._remote_panel.set_input_button_sensitive(True)
            logger.info("TV IP cleared or same as connected device - TV scrcpy disabled")

    # -------------------------------------------------------------------------
    # MPRIS Callbacks - Desktop media control integration
    # -------------------------------------------------------------------------
    
    def _on_mpris_play_pause(self) -> None:
        """Handle MPRIS PlayPause command - toggle play/pause on the TV."""
        scrcpy = self._scrcpy
        if scrcpy and scrcpy.connected:
            try:
                scrcpy.send_keycode("KEYCODE_MEDIA_PLAY_PAUSE")
                self._remote_panel.flash_button("KEYCODE_MEDIA_PLAY_PAUSE")
            except Exception as e:
                logger.error(f"MPRIS PlayPause failed: {e}")
    
    def _on_mpris_play(self) -> None:
        """Handle MPRIS Play command - start playback on the TV."""
        scrcpy = self._scrcpy
        if scrcpy and scrcpy.connected:
            try:
                scrcpy.send_keycode("KEYCODE_MEDIA_PLAY")
                self._remote_panel.flash_button("KEYCODE_MEDIA_PLAY_PAUSE")
            except Exception as e:
                logger.error(f"MPRIS Play failed: {e}")
    
    def _on_mpris_pause(self) -> None:
        """Handle MPRIS Pause command - pause playback on the TV."""
        scrcpy = self._scrcpy
        if scrcpy and scrcpy.connected:
            try:
                scrcpy.send_keycode("KEYCODE_MEDIA_PAUSE")
                self._remote_panel.flash_button("KEYCODE_MEDIA_PLAY_PAUSE")
            except Exception as e:
                logger.error(f"MPRIS Pause failed: {e}")
    
    def _on_mpris_stop(self) -> None:
        """Handle MPRIS Stop command - stop playback on the TV."""
        scrcpy = self._scrcpy
        if scrcpy and scrcpy.connected:
            try:
                scrcpy.send_keycode("KEYCODE_MEDIA_STOP")
                self._remote_panel.flash_button("KEYCODE_MEDIA_STOP")
            except Exception as e:
                logger.error(f"MPRIS Stop failed: {e}")
    
    def _on_mpris_next(self) -> None:
        """Handle MPRIS Next command - skip to next track on the TV."""
        scrcpy = self._scrcpy
        if scrcpy and scrcpy.connected:
            try:
                scrcpy.send_keycode("KEYCODE_MEDIA_NEXT")
                self._remote_panel.flash_button("KEYCODE_MEDIA_NEXT")
            except Exception as e:
                logger.error(f"MPRIS Next failed: {e}")
    
    def _on_mpris_previous(self) -> None:
        """Handle MPRIS Previous command - skip to previous track on the TV."""
        scrcpy = self._scrcpy
        if scrcpy and scrcpy.connected:
            try:
                scrcpy.send_keycode("KEYCODE_MEDIA_PREVIOUS")
                self._remote_panel.flash_button("KEYCODE_MEDIA_PREVIOUS")
            except Exception as e:
                logger.error(f"MPRIS Previous failed: {e}")
    
    def _on_mpris_raise(self) -> None:
        """Handle MPRIS Raise command - bring window to front."""
        self.present()
    
    def _on_mpris_quit(self) -> None:
        """Handle MPRIS Quit command - close the application."""
        self.get_application().quit()

    # -------------------------------------------------------------------------
    # MPRIS Media Info Polling
    # -------------------------------------------------------------------------
    
    def _start_mpris_media_polling(self) -> None:
        """Start periodic polling for media session info."""
        if self._mpris_poll_timer_id != 0:
            return  # Already polling
        
        # Poll immediately, then every 3 seconds
        self._poll_media_info()
        self._mpris_poll_timer_id = GLib.timeout_add_seconds(3, self._poll_media_info)
    
    def _stop_mpris_media_polling(self) -> None:
        """Stop periodic polling for media session info."""
        if self._mpris_poll_timer_id != 0:
            GLib.source_remove(self._mpris_poll_timer_id)
            self._mpris_poll_timer_id = 0
    
    def _poll_media_info(self) -> bool:
        """Fetch media info from device and update MPRIS.
        
        Returns True to continue polling, False to stop.
        """
        if not self._adb or not self._adb.connected:
            self._stop_mpris_media_polling()
            return False
        
        def worker():
            try:
                media_info = self._adb.get_media_session_info()
                GLib.idle_add(self._on_media_info_fetched, media_info)
            except Exception as e:
                logger.debug(f"Failed to fetch media info: {e}")
        
        threading.Thread(target=worker, daemon=True).start()
        return True  # Continue polling
    
    def _on_media_info_fetched(self, media_info) -> None:
        """Called when media info is fetched from device."""
        if media_info:
            self._mpris.set_media_info(
                title=media_info.title,
                artist=media_info.artist,
                album=media_info.album,
                playback_status=media_info.playback_state,
                position_ms=media_info.position_ms,
            )
            # Update RemotePanel's Now Playing widget
            self._remote_panel.update_now_playing(
                title=media_info.title,
                artist=media_info.artist,
                playback_status=media_info.playback_state,
            )
        else:
            # No active media session - set to stopped with device name
            self._mpris.set_media_info(
                title=None,
                artist=None,
                album=None,
                playback_status="Stopped",
                position_ms=0,
            )
            # Hide the Now Playing widget
            self._remote_panel.update_now_playing(
                title=None,
                artist=None,
                playback_status="Stopped",
            )
