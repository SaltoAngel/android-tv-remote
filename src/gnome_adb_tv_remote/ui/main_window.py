from __future__ import annotations

import ipaddress
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..core.adb_client import AdbAuthRequiredError, AdbConnectError, AdbTcpClient  # noqa: E402
from ..core.network_info import get_ipv4_interface_networks  # noqa: E402
from ..core.scanner import HostFound, ScanProgress, SubnetScanner  # noqa: E402
from .remote_panel import RemotePanel  # noqa: E402


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="Android TV Remote")
        self.set_default_size(980, 620)

        self._scan_in_progress = False
        self._connected_ip: str | None = None
        self._scan_cancel: threading.Event | None = None
        self._scan_thread: threading.Thread | None = None
        self._found_ips: set[str] = set()
        self._adb: AdbTcpClient | None = None
        self._connect_thread: threading.Thread | None = None

        # Initialize GSettings
        self._settings = Gio.Settings.new("io.github.erens.GnomeAndroidTvRemote")

        self._build_ui()
        self._create_actions()
        self._remote_panel.set_handlers(on_keyevent=self._on_remote_keyevent, on_text=self._on_remote_text)
        
        # Load last connected IP
        self._load_last_ip()

    def _build_ui(self) -> None:
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self._toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        toolbar_view.add_top_bar(header)

        scan_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        scan_btn.set_tooltip_text("Scan for devices")
        scan_btn.connect("clicked", lambda *_: self.activate_action("win.scan", None))
        header.pack_start(scan_btn)

        self._scan_spinner = Gtk.Spinner(spinning=False)
        header.pack_start(self._scan_spinner)

        split = Adw.NavigationSplitView()
        toolbar_view.set_content(split)

        # Sidebar (devices)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sidebar.set_margin_top(12)
        sidebar.set_margin_bottom(12)
        sidebar.set_margin_start(12)
        sidebar.set_margin_end(12)

        ip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._ip_entry = Gtk.Entry(placeholder_text="Device IP (e.g. 192.168.1.50)")
        self._ip_entry.set_input_purpose(Gtk.InputPurpose.URL)
        self._ip_entry.connect("activate", lambda *_: self.activate_action("win.connect_ip", None))
        ip_row.append(self._ip_entry)

        connect_btn = Gtk.Button(label="Connect")
        connect_btn.add_css_class("suggested-action")
        connect_btn.connect("clicked", lambda *_: self.activate_action("win.connect_ip", None))
        ip_row.append(connect_btn)
        sidebar.append(ip_row)

        self._scan_progress = Gtk.ProgressBar(show_text=True)
        self._scan_progress.set_visible(False)
        sidebar.append(self._scan_progress)

        self._device_list = Gtk.ListBox()
        self._device_list.set_selection_mode(Gtk.SelectionMode.NONE)

        device_frame = Gtk.Frame()
        device_frame.set_child(self._device_list)
        sidebar.append(device_frame)

        sidebar_page = Adw.NavigationPage(title="Devices", child=sidebar)
        split.set_sidebar(sidebar_page)

        # Content (remote)
        self._remote_panel = RemotePanel()
        remote_page = Adw.NavigationPage(title="Remote", child=self._remote_panel)
        split.set_content(remote_page)

        self._set_connected(False)

    def _load_last_ip(self) -> None:
        """Load the last successfully connected IP address from settings."""
        last_ip = self._settings.get_string("last-connected-ip")
        if last_ip:
            self._ip_entry.set_text(last_ip)

    def _save_last_ip(self, ip: str) -> None:
        """Save the successfully connected IP address to settings."""
        self._settings.set_string("last-connected-ip", ip)

    def _create_actions(self) -> None:
        scan = Gio.SimpleAction.new("scan", None)
        scan.connect("activate", self._on_scan)
        self.add_action(scan)

        connect_ip = Gio.SimpleAction.new("connect_ip", None)
        connect_ip.connect("activate", self._on_connect_ip)
        self.add_action(connect_ip)

        disconnect = Gio.SimpleAction.new("disconnect", None)
        disconnect.connect("activate", self._on_disconnect)
        self.add_action(disconnect)

    def _toast(self, text: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=text))

    def _set_scanning(self, scanning: bool) -> None:
        self._scan_in_progress = scanning
        self._scan_spinner.set_spinning(scanning)
        self._scan_progress.set_visible(scanning)
        if scanning:
            self._scan_progress.set_fraction(0.0)
            self._scan_progress.set_text("Scanning…")

    def _set_connected(self, connected: bool, ip: str | None = None) -> None:
        self._connected_ip = ip if connected else None
        self._remote_panel.set_sensitive(connected)

    def _on_scan(self, *_args) -> None:
        if self._scan_in_progress:
            if self._scan_cancel:
                self._scan_cancel.set()
                self._toast("Stopping scan…")
            return

        self._set_scanning(True)
        while child := self._device_list.get_first_child():
            self._device_list.remove(child)
        self._found_ips.clear()

        nets = [n.network for n in get_ipv4_interface_networks(limit_to_slash24_if_broader=True)]
        if not nets:
            self._set_scanning(False)
            self._toast("No private IPv4 networks found to scan")
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

    def _on_scan_progress_ui(self, scanned: int, total: int) -> None:
        if not self._scan_in_progress:
            return
        frac = 0.0 if total <= 0 else min(1.0, scanned / total)
        self._scan_progress.set_fraction(frac)
        self._scan_progress.set_text(f"Scanning {scanned}/{total}")

    def _on_scan_found_ui(self, ip: str, latency_ms: float) -> None:
        if ip in self._found_ips:
            return
        self._found_ips.add(ip)

        row = Adw.ActionRow(title=ip, subtitle=f"Port 5555 open ({latency_ms:.0f} ms)")

        btn = Gtk.Button(label="Connect")
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: self._connect_from_row(ip))
        row.add_suffix(btn)
        row.set_activatable_widget(btn)

        self._device_list.append(row)

    def _connect_from_row(self, ip: str) -> None:
        self._ip_entry.set_text(ip)
        self.activate_action("win.connect_ip", None)

    def _on_scan_finished_ui(self, cancelled: bool) -> None:
        self._set_scanning(False)
        self._scan_cancel = None
        self._scan_thread = None
        if cancelled:
            self._toast("Scan stopped")
        else:
            self._toast(f"Scan finished ({len(self._found_ips)} found)")

    def _on_connect_ip(self, *_args) -> None:
        ip = self._ip_entry.get_text().strip()
        if not ip:
            self._toast("Enter an IP address")
            return

        try:
            ipaddress.ip_address(ip)
        except ValueError:
            self._toast("Invalid IP address")
            return

        if self._connect_thread:
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

        self._toast(f"Connecting to {ip}:5555…")
        client = AdbTcpClient(ip, port=5555, timeout_s=8.0)

        def worker() -> None:
            try:
                try:
                    client.connect()
                except AdbAuthRequiredError as e:
                    GLib.idle_add(self._on_connect_failed_ui, str(e) or "Authorization required")
                    return
                except AdbConnectError as e:
                    GLib.idle_add(self._on_connect_failed_ui, str(e) or "Connection failed")
                    return
                except Exception as e:  # pragma: no cover
                    GLib.idle_add(self._on_connect_failed_ui, str(e) or "Connection failed")
                    return

                GLib.idle_add(self._on_connect_success_ui, ip, client)
            finally:
                GLib.idle_add(self._on_connect_done_ui)

        self._connect_thread = threading.Thread(target=worker, name="adb-connect", daemon=True)
        self._connect_thread.start()

    def _on_connect_success_ui(self, ip: str, client: AdbTcpClient) -> None:
        self._adb = client
        self._set_connected(True, ip=ip)
        self._save_last_ip(ip)
        self._toast(f"Connected to {ip}")

    def _on_connect_failed_ui(self, msg: str) -> None:
        self._adb = None
        self._set_connected(False)
        self._toast(msg)

    def _on_connect_done_ui(self) -> None:
        self._connect_thread = None

    def _on_disconnect(self, *_args) -> None:
        if self._connect_thread:
            self._toast("Still connecting…")
            return
        if self._adb:
            try:
                self._adb.disconnect()
            except Exception:
                pass
            self._adb = None
        self._set_connected(False)
        self._toast("Disconnected")

    def _on_remote_keyevent(self, keycode: str) -> None:
        client = self._adb
        if not client:
            return

        def worker() -> None:
            try:
                client.send_keyevent(keycode)
            except Exception as e:
                GLib.idle_add(self._toast, f"Keyevent failed: {e}")

        threading.Thread(target=worker, name="adb-keyevent", daemon=True).start()

    def _on_remote_text(self, text: str) -> None:
        client = self._adb
        if not client:
            return

        def worker() -> None:
            try:
                client.send_text(text)
            except Exception as e:
                GLib.idle_add(self._toast, f"Send text failed: {e}")

        threading.Thread(target=worker, name="adb-text", daemon=True).start()


