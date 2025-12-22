"""
Device Discovery and Connection Dialog.

This module provides the DeviceDialog class, a modal dialog for discovering
Android TV devices on the local network and initiating connections. It includes
network scanning functionality and persists discovered devices across sessions.
"""

from __future__ import annotations

import json
import ipaddress

import threading
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402


from ..core.network_info import get_ipv4_interface_networks  # noqa: E402
from ..core.scanner import HostFound, ScanProgress, SubnetScanner  # noqa: E402
from ..core.adb_client import AdbTcpClient  # noqa: E402

if TYPE_CHECKING:
    from .main_window import MainWindow


class DeviceDialog(Adw.Window):
    """Modal dialog for discovering and connecting to Android TV devices.
    
    Provides:
    - Manual IP address entry for direct connection
    - Network scanning to discover devices with ADB enabled
    - Persistence of discovered devices across app sessions
    - Device info display (model, Android version, latency)
    """

    def __init__(self, parent: MainWindow) -> None:
        super().__init__(
            transient_for=parent,
            modal=True,
            title="Connect to Device",
            default_width=400,
            default_height=500,
        )
        self._parent = parent
        self._scan_in_progress = False
        self._scan_cancel: threading.Event | None = None
        self._scan_thread: threading.Thread | None = None
        self._found_ips: set[str] = set()
        self._discovered_devices: list[dict[str, str | float | None]] = []
        self._device_rows: dict[str, Adw.ActionRow] = {}
        
        # Pairing state tracking
        self._pairing_in_progress = False
        self._pairing_ip: str | None = None
        self._pairing_button: Gtk.Button | None = None
        self._ip_entry_button: Gtk.Button | None = None
        # Single persistent thread for pairing checks (performance optimization)
        self._pairing_stop_event: threading.Event | None = None
        self._pairing_thread: threading.Thread | None = None

        self._build_ui()
        self._load_discovered_devices()
        self.connect("close-request", self._on_close_request)
        
        # Add keyboard controller for Escape key
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_close_request(self, *_args) -> bool:
        # Reset pairing state if in progress
        if self._pairing_in_progress:
            self._reset_pairing_state()
        self.hide()
        return True

    def _on_key_pressed(self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, _state: Gdk.ModifierType) -> bool:
        """Handle keyboard shortcuts in the dialog."""
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def update_last_ip(self) -> None:
        """Refresh the IP entry with the last connected IP from settings."""
        last_ip = self._parent._settings.get_string("last-connected-ip")
        if last_ip:
            self._ip_entry.set_text(last_ip)

    def _load_discovered_devices(self) -> None:
        """Load previously discovered devices from settings."""
        json_data = self._parent._settings.get_string("discovered-devices")
        if not json_data:
            return
        try:
            devices = json.loads(json_data)
            for device in devices:
                ip = device.get("ip")
                latency = device.get("latency_ms", 0.0)
                model = device.get("model")
                version = device.get("version")
                if ip:
                    self._on_scan_found_ui(ip, latency, save=False, model=model, version=version)
        except Exception:
            pass

    def _save_discovered_devices(self) -> None:
        """Save currently found devices to settings."""
        json_data = json.dumps(self._discovered_devices)
        self._parent._settings.set_string("discovered-devices", json_data)

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self._scan_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self._scan_btn.set_tooltip_text("Scan for devices")
        self._scan_btn.connect("clicked", self._on_scan_clicked)
        header.pack_start(self._scan_btn)

        self._scan_spinner = Gtk.Spinner(spinning=False)
        header.pack_start(self._scan_spinner)

        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        toolbar_view.set_content(content)

        # IP Entry Row
        ip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._ip_entry = Gtk.Entry(placeholder_text="Device IP (e.g. 192.168.1.50)")
        self._ip_entry.set_input_purpose(Gtk.InputPurpose.URL)
        self._ip_entry.set_hexpand(True)
        self._ip_entry.connect("activate", self._on_connect_clicked)
        
        # Pre-fill with last connected IP if available
        last_ip = self._parent._settings.get_string("last-connected-ip")
        if last_ip:
            self._ip_entry.set_text(last_ip)

        ip_row.append(self._ip_entry)

        self._ip_entry_button = Gtk.Button(label="Connect")
        self._ip_entry_button.add_css_class("suggested-action")
        self._ip_entry_button.connect("clicked", self._on_connect_clicked)
        ip_row.append(self._ip_entry_button)
        content.append(ip_row)



        # Scan Progress
        self._scan_progress = Gtk.ProgressBar(show_text=True)
        self._scan_progress.set_visible(False)
        content.append(self._scan_progress)

        # Device List
        self._device_list = Gtk.ListBox()
        self._device_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._device_list.add_css_class("boxed-list")

        device_scroll = Gtk.ScrolledWindow()
        device_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        device_scroll.set_vexpand(True)
        device_scroll.set_child(self._device_list)
        content.append(device_scroll)

    def _on_connect_clicked(self, *_args) -> None:
        ip = self._ip_entry.get_text().strip()
        if not ip:
            self._parent._toast("Enter an IP address")
            return
        
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            self._parent._toast("Invalid IP address")
            return

        self._start_pairing_check(ip, self._ip_entry_button)

    def _on_scan_clicked(self, *_args) -> None:
        if self._scan_in_progress:
            if self._scan_cancel:
                self._scan_cancel.set()
                self._parent._toast("Stopping scan…")
            return

        self._set_scanning(True)
        while child := self._device_list.get_first_child():
            self._device_list.remove(child)
        self._found_ips.clear()
        self._discovered_devices.clear()
        self._device_rows.clear()
        self._save_discovered_devices()

        nets = [n.network for n in get_ipv4_interface_networks(limit_to_slash24_if_broader=True)]
        if not nets:
            self._set_scanning(False)
            self._parent._toast("No private IPv4 networks found to scan")
            return

        self._scan_cancel = threading.Event()
        scanner = SubnetScanner(port=5555, timeout_s=0.25, concurrency=256)

        def on_progress(p: ScanProgress) -> None:
            GLib.idle_add(self._on_scan_progress_ui, p.scanned, p.total)

        def on_found(found: HostFound) -> None:
            GLib.idle_add(self._on_scan_found_ui, str(found.ip), found.latency_ms)

        def run() -> None:
            try:
                scanner.scan(nets, cancel_event=self._scan_cancel, on_progress=on_progress, on_found=on_found)
            finally:
                cancelled = bool(self._scan_cancel and self._scan_cancel.is_set())
                GLib.idle_add(self._on_scan_finished_ui, cancelled)

        self._scan_thread = threading.Thread(target=run, name="subnet-scan", daemon=True)
        self._scan_thread.start()

    def _set_scanning(self, scanning: bool) -> None:
        self._scan_in_progress = scanning
        self._scan_spinner.set_spinning(scanning)
        self._scan_progress.set_visible(scanning)
        if scanning:
            self._scan_progress.set_fraction(0.0)
            self._scan_progress.set_text("Scanning…")
            self._scan_btn.set_icon_name("process-stop-symbolic")
        else:
            self._scan_btn.set_icon_name("view-refresh-symbolic")

    def _on_scan_progress_ui(self, scanned: int, total: int) -> None:
        if not self._scan_in_progress:
            return
        frac = 0.0 if total <= 0 else min(1.0, scanned / total)
        self._scan_progress.set_fraction(frac)
        self._scan_progress.set_text(f"Scanning {scanned}/{total}")

    def _on_scan_found_ui(self, ip: str, latency_ms: float, save: bool = True, model: str | None = None, version: str | None = None) -> None:
        if ip in self._found_ips:
            return
        self._found_ips.add(ip)

        if save:
            device_data: dict[str, str | float | None] = {"ip": ip, "latency_ms": latency_ms}
            if model:
                device_data["model"] = model
            if version:
                device_data["version"] = version
            self._discovered_devices.append(device_data)
            self._save_discovered_devices()

        # Create row with initial info
        subtitle = f"Port 5555 open ({latency_ms:.0f} ms)"
        if model and version:
            subtitle = f"{model} • Android {version} • {latency_ms:.0f} ms"
        elif model:
            subtitle = f"{model} • {latency_ms:.0f} ms"
        elif version:
            subtitle = f"Android {version} • {latency_ms:.0f} ms"

        row = Adw.ActionRow(
            title=GLib.markup_escape_text(ip),
            subtitle=GLib.markup_escape_text(subtitle)
        )

        btn = Gtk.Button(label="Connect")
        btn.set_valign(Gtk.Align.CENTER)
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_, b=btn: self._connect_from_row(ip, b))
        row.add_suffix(btn)
        row.set_activatable_widget(btn)

        self._device_list.append(row)
        self._device_rows[ip] = row





    def _connect_from_row(self, ip: str, btn: Gtk.Button) -> None:
        self._start_pairing_check(ip, btn)

    def _start_pairing_check(self, ip: str, btn: Gtk.Button) -> None:
        """Start the pairing check flow for the given IP."""
        if self._pairing_in_progress:
            self._parent._toast("Already pairing with another device")
            return

        self._pairing_in_progress = True
        self._pairing_ip = ip
        self._pairing_button = btn

        # Change button to "Pairing" state
        btn.set_label("Pairing")
        btn.set_sensitive(False)
        btn.remove_css_class("suggested-action")
        btn.add_css_class("accent")

        # First, trigger a connection attempt to show the pairing dialog on the TV
        def trigger_connection() -> None:
            try:
                client = AdbTcpClient(ip, port=5555, timeout_s=2.0)
                client.connect()
            except Exception:
                # Connection will fail if not paired, that's expected
                pass
            # Start the pairing status checks after attempting connection
            GLib.idle_add(self._start_pairing_timer)

        thread = threading.Thread(target=trigger_connection, daemon=True)
        thread.start()

    def _start_pairing_timer(self) -> None:
        """Start the persistent pairing check thread."""
        if not self._pairing_in_progress or not self._pairing_ip:
            return
        
        # Create stop event for clean shutdown
        self._pairing_stop_event = threading.Event()
        ip = self._pairing_ip
        
        def pairing_check_loop() -> None:
            """Single persistent thread that checks pairing status periodically."""
            import time
            while not self._pairing_stop_event.is_set():
                try:
                    client = AdbTcpClient(ip, port=5555, timeout_s=2.0)
                    is_paired = client.is_paired_silent()
                except Exception:
                    is_paired = False
                
                if is_paired:
                    GLib.idle_add(self._on_pairing_complete)
                    return  # Stop thread on success
                
                # Wait 1 second before next check, but check stop event frequently
                for _ in range(10):  # 10 x 0.1s = 1 second
                    if self._pairing_stop_event.is_set():
                        return
                    time.sleep(0.1)
        
        self._pairing_thread = threading.Thread(target=pairing_check_loop, name="pairing-check", daemon=True)
        self._pairing_thread.start()

    def _on_pairing_complete(self) -> None:
        """Called when the device is successfully paired."""
        if not self._pairing_button or not self._pairing_ip:
            return

        # Stop the pairing check thread
        if self._pairing_stop_event:
            self._pairing_stop_event.set()
            self._pairing_stop_event = None
        self._pairing_thread = None

        # Update button to "Paired" state
        self._pairing_button.set_label("Paired")
        self._pairing_button.remove_css_class("accent")
        self._pairing_button.add_css_class("success")

        # Connect silently in the background
        ip = self._pairing_ip

        # Use _connect_ip with silent=True
        self._parent._connect_ip(ip, silent=True)
        
        # Monitor connection status - check every 500ms for up to 10 seconds
        self._connection_check_count = 0
        
        def check_connection() -> bool:
            self._connection_check_count += 1
            if self._parent._adb and self._parent._adb.connected:
                self._reset_pairing_state()
                self.close()
                return False
            if self._connection_check_count >= 20:  # 10 seconds timeout
                self._reset_pairing_state()
                return False
            return True
        
        GLib.timeout_add(500, check_connection)

    def _reset_pairing_state(self) -> None:
        """Reset the pairing state to allow new pairing attempts."""
        # Stop the pairing check thread
        if self._pairing_stop_event:
            self._pairing_stop_event.set()
            self._pairing_stop_event = None
        self._pairing_thread = None

        if self._pairing_button:
            self._pairing_button.set_label("Connect")
            self._pairing_button.set_sensitive(True)
            self._pairing_button.remove_css_class("accent")
            self._pairing_button.remove_css_class("success")
            self._pairing_button.add_css_class("suggested-action")

        self._pairing_in_progress = False
        self._pairing_ip = None
        self._pairing_button = None

    def _on_scan_finished_ui(self, cancelled: bool) -> None:
        self._set_scanning(False)
        self._scan_cancel = None
        self._scan_thread = None
        if cancelled:
            self._parent._toast("Scan stopped")
        else:
            self._parent._toast(f"Scan finished ({len(self._found_ips)} found)")



