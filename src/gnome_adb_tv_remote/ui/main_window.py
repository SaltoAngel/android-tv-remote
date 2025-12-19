from __future__ import annotations

import ipaddress
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..core.adb_client import AdbAuthRequiredError, AdbConnectError, AdbTcpClient  # noqa: E402
from .device_dialog import DeviceDialog  # noqa: E402
from .remote_panel import RemotePanel  # noqa: E402


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="Android TV Remote")
        self.set_default_size(500, 650)

        self._connected_ip: str | None = None
        self._adb: AdbTcpClient | None = None
        self._connect_thread: threading.Thread | None = None
        self._connect_silent: bool = False

        # Initialize GSettings
        self._settings = Gio.Settings.new("io.github.erens.GnomeAndroidTvRemote")

        self._build_ui()
        self._create_actions()
        self._remote_panel.set_handlers(on_keyevent=self._on_remote_keyevent, on_text=self._on_remote_text)
        
        # Load last connected IP and auto-connect
        self._auto_connect_last_ip()

    def _build_ui(self) -> None:
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self._toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        toolbar_view.add_top_bar(header)

        # Devices button in top bar
        devices_btn = Gtk.Button(label="Devices")
        devices_btn.set_tooltip_text("Manage devices")
        devices_btn.connect("clicked", self._on_devices_clicked)
        header.pack_start(devices_btn)

        # Content (remote)
        self._remote_panel = RemotePanel()
        toolbar_view.set_content(self._remote_panel)

        self._set_connected(False)

    def _on_devices_clicked(self, *_args) -> None:
        dialog = DeviceDialog(self)
        dialog.present()

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

    def _set_connected(self, connected: bool, ip: str | None = None) -> None:
        self._connected_ip = ip if connected else None
        self._remote_panel.set_sensitive(connected)
        if not connected:
            self._remote_panel.update_device_info(None, None)

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

                from ..core.adb_client import DeviceInfo
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
            self._toast(f"Connected to {ip}")
        self._connect_silent = False

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
