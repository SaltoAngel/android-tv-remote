"""
Input Device Selection Dialog.

This module provides a dialog for selecting an alternative device
that supports TV Input when the currently connected device doesn't.
"""

from __future__ import annotations

import json
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from typing import TYPE_CHECKING  # noqa: E402

from ..core.adb_client import AdbTcpClient  # noqa: E402
from ..core.network_info import get_ipv4_interface_networks  # noqa: E402
from ..core.scanner import HostFound, ScanProgress, SubnetScanner  # noqa: E402

if TYPE_CHECKING:
    from gi.repository import Gio


class InputDeviceDialog(Adw.Dialog):
    """Dialog for selecting a device with TV Input support.
    
    When the currently connected device doesn't support TV Input (like Mi Box),
    this dialog shows other discovered devices that the user can select
    as the TV Input routing target.
    """

    def __init__(
        self,
        settings: Gio.Settings,
        on_device_selected: callable = None,
    ) -> None:
        """Initialize the Input Device Selection Dialog.
        
        Args:
            settings: GSettings instance to load discovered devices.
            on_device_selected: Callback when a device is selected (receives IP).
        """
        super().__init__(title="Select TV for Input")
        
        self._settings = settings
        self._on_device_selected = on_device_selected
        
        # Pairing state tracking
        self._pairing_in_progress = False
        self._pairing_ip: str | None = None
        self._pairing_timer_id: int | None = None
        self._pairing_button: Gtk.Button | None = None
        
        # Scan state tracking
        self._scan_in_progress = False
        self._scan_cancel: threading.Event | None = None
        self._found_ips: set[str] = set()
        
        self.set_content_width(400)
        self.set_content_height(300)
        
        self._build_ui()
        self._load_devices()

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        
        # Header label
        header_label = Gtk.Label()
        header_label.set_markup(
            "<b>Select a TV with Input Support</b>\n\n"
            "<span size='small'>The connected device doesn't have hardware TV inputs.\n"
            "Choose a TV from the list below to route Input commands.</span>"
        )
        header_label.set_wrap(True)
        header_label.set_halign(Gtk.Align.CENTER)
        header_label.set_margin_bottom(8)
        content.append(header_label)
        
        # Scrolled window for device list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_min_content_height(140)
        
        # Device list box
        self._device_list = Gtk.ListBox()
        self._device_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._device_list.add_css_class("boxed-list")
        scrolled.set_child(self._device_list)
        content.append(scrolled)
        
        # Status label (for no devices message)
        self._status_label = Gtk.Label()
        self._status_label.add_css_class("dim-label")
        self._status_label.set_margin_top(8)
        self._status_label.set_visible(False)
        content.append(self._status_label)
        
        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(8)
        
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())
        button_box.append(cancel_btn)
        
        content.append(button_box)
        
        # Add a toolbar view wrapper
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        
        # Add refresh button to header bar
        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh device list")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        header.pack_end(refresh_btn)
        
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(content)
        
        self.set_child(toolbar_view)

    def _load_devices(self) -> None:
        """Load discovered devices from settings."""
        # Get discovered devices
        devices_json = self._settings.get_string("discovered-devices")
        devices: list[dict] = []
        
        try:
            if devices_json:
                devices = json.loads(devices_json)
        except Exception:
            pass
        
        # Get currently connected IP to exclude it
        connected_ip = self._settings.get_string("last-connected-ip")
        
        # Filter to devices other than the connected one
        other_devices = [d for d in devices if d.get("ip") != connected_ip]
        
        if not other_devices:
            self._status_label.set_text("No other devices found.\nClick the refresh button to scan again.")
            self._status_label.set_visible(True)
            return
        
        # Add each device to the list
        for device in other_devices:
            ip = device.get("ip")
            if ip:
                self._add_device_row(ip)

    def _add_device_row(self, ip: str) -> None:
        """Add a device row to the list.
        
        Args:
            ip: Device IP address.
        """
        row = Adw.ActionRow()
        row.set_title(ip)
        
        # Connect button
        connect_btn = Gtk.Button(label="Connect")
        connect_btn.add_css_class("suggested-action")
        connect_btn.set_valign(Gtk.Align.CENTER)
        connect_btn.connect("clicked", lambda *_, i=ip, b=connect_btn: self._start_pairing_check(i, b))
        row.add_suffix(connect_btn)
        row.set_activatable_widget(connect_btn)
        
        self._device_list.append(row)

    def _start_pairing_check(self, ip: str, btn: Gtk.Button) -> None:
        """Start the pairing check flow for the given IP."""
        if self._pairing_in_progress:
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
        """Start the periodic pairing status timer."""
        if not self._pairing_in_progress:
            return
        # Start checking pairing status every 1.5 seconds
        self._pairing_timer_id = GLib.timeout_add(1500, self._check_pairing_status)
        # Also do an immediate check
        self._check_pairing_status()

    def _check_pairing_status(self) -> bool:
        """Check if the device is paired. Called periodically."""
        if not self._pairing_in_progress or not self._pairing_ip:
            return False  # Stop the timer

        ip = self._pairing_ip

        def check_paired() -> None:
            try:
                client = AdbTcpClient(ip, port=5555, timeout_s=2.0)
                is_paired = client.is_paired_silent()
            except Exception:
                is_paired = False

            GLib.idle_add(self._on_pairing_check_result, is_paired)

        thread = threading.Thread(target=check_paired, daemon=True)
        thread.start()

        return True  # Continue the timer

    def _on_pairing_check_result(self, is_paired: bool) -> None:
        """Handle the result of a pairing check."""
        if not self._pairing_in_progress:
            return

        if is_paired:
            self._on_pairing_complete()

    def _on_pairing_complete(self) -> None:
        """Called when the device is successfully paired."""
        if not self._pairing_button or not self._pairing_ip:
            return

        # Stop the timer
        if self._pairing_timer_id:
            GLib.source_remove(self._pairing_timer_id)
            self._pairing_timer_id = None

        # Update button to "Paired" state
        self._pairing_button.set_label("Paired")
        self._pairing_button.remove_css_class("accent")
        self._pairing_button.add_css_class("success")

        # Fetch device info and update discovered-devices
        ip = self._pairing_ip
        self._fetch_device_info_after_pairing(ip)

        # Select this device
        self._reset_pairing_state()
        self._on_device_select(ip)

    def _fetch_device_info_after_pairing(self, ip: str) -> None:
        """Fetch device info after successful pairing and update discovered-devices."""
        def fetch_info() -> None:
            try:
                client = AdbTcpClient(ip, port=5555, timeout_s=3.0)
                client.connect()
                info = client.get_device_info()
                client.disconnect()
                
                device_name = f"{info.manufacturer} {info.model}"
                
                # Update discovered-devices in settings
                GLib.idle_add(
                    self._update_discovered_device,
                    ip,
                    info.model,
                    info.version,
                    device_name
                )
            except Exception:
                pass

        thread = threading.Thread(target=fetch_info, daemon=True)
        thread.start()

    def _update_discovered_device(self, ip: str, model: str, version: str, device_name: str) -> None:
        """Update a device in discovered-devices settings."""
        import json
        
        devices_json = self._settings.get_string("discovered-devices")
        devices: list[dict] = []
        
        try:
            if devices_json:
                devices = json.loads(devices_json)
        except Exception:
            pass
        
        # Find and update the device
        found = False
        for device in devices:
            if device.get("ip") == ip:
                device["model"] = model
                device["version"] = version
                device["device_name"] = device_name
                found = True
                break
        
        # If device not found, add it
        if not found:
            devices.append({
                "ip": ip,
                "latency_ms": 0.0,
                "model": model,
                "version": version,
                "device_name": device_name
            })
        
        # Save back to settings
        self._settings.set_string("discovered-devices", json.dumps(devices))

    def _reset_pairing_state(self) -> None:
        """Reset the pairing state to allow new pairing attempts."""
        if self._pairing_timer_id:
            GLib.source_remove(self._pairing_timer_id)
            self._pairing_timer_id = None

        if self._pairing_button:
            self._pairing_button.set_label("Connect")
            self._pairing_button.set_sensitive(True)
            self._pairing_button.remove_css_class("accent")
            self._pairing_button.remove_css_class("success")
            self._pairing_button.add_css_class("suggested-action")

        self._pairing_in_progress = False
        self._pairing_ip = None
        self._pairing_button = None

    def _on_device_select(self, ip: str) -> None:
        """Handle device selection.
        
        Args:
            ip: Selected device IP address.
        """
        # Save selected IP as tv-ip
        self._settings.set_string("tv-ip", ip)
        
        # Call callback if provided
        if self._on_device_selected:
            self._on_device_selected(ip)
        
        self.close()

    def _on_refresh_clicked(self, _btn: Gtk.Button) -> None:
        """Handle refresh button click - start network scan for devices."""
        if self._scan_in_progress:
            # Cancel current scan
            if self._scan_cancel:
                self._scan_cancel.set()
            return
        
        # Clear existing device list
        while child := self._device_list.get_first_child():
            self._device_list.remove(child)
        self._found_ips.clear()
        
        # Hide status label during scan
        self._status_label.set_visible(False)
        
        # Get networks to scan
        nets = [n.network for n in get_ipv4_interface_networks(limit_to_slash24_if_broader=True)]
        if not nets:
            self._status_label.set_text("No private IPv4 networks found to scan.")
            self._status_label.set_visible(True)
            return
        
        # Start scan
        self._scan_in_progress = True
        self._scan_cancel = threading.Event()
        scanner = SubnetScanner(port=5555, timeout_s=0.35, concurrency=256)
        
        # Get currently connected IP to exclude
        connected_ip = self._settings.get_string("last-connected-ip")
        
        def on_found(found: HostFound) -> None:
            ip = str(found.ip)
            # Skip the currently connected device
            if ip == connected_ip:
                return
            GLib.idle_add(self._on_scan_found, ip, found.latency_ms)
        
        def run() -> None:
            try:
                scanner.scan(nets, cancel_event=self._scan_cancel, on_found=on_found)
            finally:
                GLib.idle_add(self._on_scan_finished)
        
        thread = threading.Thread(target=run, name="input-dialog-scan", daemon=True)
        thread.start()
        
        # Show scanning status
        self._status_label.set_text("Scanning for devices...")
        self._status_label.set_visible(True)

    def _on_scan_found(self, ip: str, latency_ms: float) -> None:
        """Handle a device found during scan."""
        if ip in self._found_ips:
            return
        self._found_ips.add(ip)
        
        # Hide "scanning" message once we find something
        self._status_label.set_visible(False)
        
        # Add to UI
        self._add_device_row(ip)
        
        # Check pairing and fetch device info in background
        self._check_and_fetch_device_info(ip)

    def _on_scan_finished(self) -> None:
        """Handle scan completion."""
        self._scan_in_progress = False
        self._scan_cancel = None
        
        if len(self._found_ips) == 0:
            self._status_label.set_text("No other devices found.\nClick the refresh button to scan again.")
            self._status_label.set_visible(True)

    def _check_and_fetch_device_info(self, ip: str) -> None:
        """Check if device is paired and fetch device info in background thread."""
        def check_and_fetch() -> None:
            try:
                client = AdbTcpClient(ip, port=5555, timeout_s=2.0)
                is_paired = client.is_paired_silent()
                
                if is_paired:
                    # Device is paired, try to connect and get device info
                    try:
                        client.connect()
                        info = client.get_device_info()
                        client.disconnect()
                        
                        device_name = f"{info.manufacturer} {info.model}"
                        
                        # Update UI with device info
                        GLib.idle_add(self._update_device_row_info, ip, device_name, info.version)
                        
                        # Update discovered-devices in settings
                        GLib.idle_add(
                            self._update_discovered_device,
                            ip,
                            info.model,
                            info.version,
                            device_name
                        )
                    except Exception:
                        pass
            except Exception:
                pass

        thread = threading.Thread(target=check_and_fetch, daemon=True)
        thread.start()

    def _update_device_row_info(self, ip: str, device_name: str, version: str | None) -> None:
        """Update a device row with fetched device information."""
        # Find the row by iterating through the list
        child = self._device_list.get_first_child()
        while child:
            if isinstance(child, Adw.ActionRow) and child.get_title() == ip:
                # Update title to device name
                child.set_title(device_name)
                if version:
                    child.set_subtitle(f"{ip} • Android {version}")
                else:
                    child.set_subtitle(ip)
                break
            child = child.get_next_sibling()
