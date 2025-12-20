"""
Device Discovery and Connection Dialog.

This module provides the DeviceDialog class, a modal dialog for discovering
Android TV devices on the local network and initiating connections. It includes
network scanning functionality and persists discovered devices across sessions.
"""

from __future__ import annotations

import json
import ipaddress
import re
import threading
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..core.adb_client import AdbAuthRequiredError, AdbConnectError, AdbTcpClient, DeviceInfo  # noqa: E402
from ..core.network_info import get_ipv4_interface_networks  # noqa: E402
from ..core.scanner import HostFound, ScanProgress, SubnetScanner  # noqa: E402

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

        self._build_ui()
        self._load_discovered_devices()
        self.connect("close-request", self._on_close_request)
        
        # Add keyboard controller for Escape key
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_close_request(self, *_args) -> bool:
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

        connect_btn = Gtk.Button(label="Connect")
        connect_btn.add_css_class("suggested-action")
        connect_btn.connect("clicked", self._on_connect_clicked)
        ip_row.append(connect_btn)
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

        self._parent._connect_ip_address(ip)
        self.close()

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
        scanner = SubnetScanner(port=5555, timeout_s=0.35, concurrency=256)

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
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: self._connect_from_row(ip))
        row.add_suffix(btn)
        row.set_activatable_widget(btn)

        self._device_list.append(row)
        self._device_rows[ip] = row

        # If device info not provided, fetch it in background
        if not model or not version:
            self._fetch_device_info_async(ip)

    def _fetch_device_info_async(self, ip: str) -> None:
        """Fetch device info (name and Android version) in background thread."""
        def worker() -> None:
            client = AdbTcpClient(ip, port=5555, timeout_s=3.0)
            try:
                client.connect()
                device_info = client.get_device_info()
                GLib.idle_add(self._on_device_info_fetched_ui, ip, device_info)
            except (AdbAuthRequiredError, AdbConnectError, Exception):
                # If we can't connect or get info, just leave the row as is
                pass
            finally:
                try:
                    client.disconnect()
                except Exception:
                    pass

        thread = threading.Thread(target=worker, name=f"fetch-device-info-{ip}", daemon=True)
        thread.start()

    def _on_device_info_fetched_ui(self, ip: str, device_info: DeviceInfo) -> None:
        """Update the device row with fetched device info."""
        row = self._device_rows.get(ip)
        if not row:
            return

        # Update subtitle with device info
        latency_match = None
        current_subtitle = row.get_subtitle()
        if current_subtitle:
            # Extract latency from existing subtitle
            match = re.search(r'(\d+\.?\d*)\s*ms', current_subtitle)
            if match:
                latency_match = match.group(1)

        subtitle_parts = []
        if device_info.model:
            subtitle_parts.append(device_info.model)
        if device_info.version:
            subtitle_parts.append(f"Android {device_info.version}")
        if latency_match:
            subtitle_parts.append(f"{latency_match} ms")
        else:
            subtitle_parts.append("Port 5555 open")

        subtitle = " • ".join(subtitle_parts)
        row.set_subtitle(GLib.markup_escape_text(subtitle))

        # Update stored device info
        for device in self._discovered_devices:
            if device.get("ip") == ip:
                device["model"] = device_info.model
                device["version"] = device_info.version
                self._save_discovered_devices()
                break

    def _connect_from_row(self, ip: str) -> None:
        self._parent._connect_ip_address(ip)
        self.close()

    def _on_scan_finished_ui(self, cancelled: bool) -> None:
        self._set_scanning(False)
        self._scan_cancel = None
        self._scan_thread = None
        if cancelled:
            self._parent._toast("Scan stopped")
        else:
            self._parent._toast(f"Scan finished ({len(self._found_ips)} found)")



