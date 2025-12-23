"""
App Launcher Dialog.

Shows installed applications and allows launching them.
Active app is highlighted.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from ..core.adb_client import AdbTcpClient, AppInfo  # noqa: E402
from ..core.icon_cache import fetch_and_cache_icon, get_cached_icon  # noqa: E402

logger = logging.getLogger(__name__)

# CSS for app launcher
APP_LAUNCHER_CSS = """
.app-button {
    padding: 12px;
    min-width: 100px;
    min-height: 80px;
    border-radius: 12px;
}

.app-button:hover {
    background-color: alpha(@accent_color, 0.2);
}

.app-button.active-app {
    background-color: alpha(@accent_color, 0.3);
    border: 2px solid @accent_color;
}

.app-button.active-app:hover {
    background-color: alpha(@accent_color, 0.4);
}

.app-label {
    font-size: 0.85em;
}

.active-indicator {
    font-size: 0.75em;
    color: @accent_color;
    font-weight: bold;
}
"""


class AppLauncherDialog(Adw.Dialog):
    """Dialog for launching installed applications."""

    def __init__(
        self,
        adb_client: AdbTcpClient,
        on_launch: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._adb = adb_client
        self._on_launch = on_launch
        self._apps: list[AppInfo] = []

        self.set_title("Applications")
        self.set_content_width(500)
        self.set_content_height(450)

        self._build_ui()
        self._load_apps()

    def _build_ui(self) -> None:
        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(APP_LAUNCHER_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gtk.StyleContext.get_display(self.get_style_context()),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Main layout
        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        # Header
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar_view.add_top_bar(header)

        # Close button
        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.connect("clicked", lambda *_: self.close())
        header.pack_end(close_btn)

        # Refresh button
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh app list")
        refresh_btn.connect("clicked", lambda *_: self._load_apps())
        header.pack_start(refresh_btn)

        # Content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        toolbar_view.set_content(scrolled)

        # Loading state
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        scrolled.set_child(self._stack)

        # Loading spinner
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        loading_box.set_valign(Gtk.Align.CENTER)
        loading_box.set_halign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.set_size_request(32, 32)
        spinner.start()
        loading_box.append(spinner)
        loading_label = Gtk.Label(label="Loading applications...")
        loading_label.add_css_class("dim-label")
        loading_box.append(loading_label)
        self._stack.add_named(loading_box, "loading")

        # Apps grid
        self._flow_box = Gtk.FlowBox()
        self._flow_box.set_valign(Gtk.Align.START)
        self._flow_box.set_max_children_per_line(4)
        self._flow_box.set_min_children_per_line(2)
        self._flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flow_box.set_homogeneous(True)
        self._flow_box.set_row_spacing(8)
        self._flow_box.set_column_spacing(8)
        self._flow_box.set_margin_top(12)
        self._flow_box.set_margin_bottom(12)
        self._flow_box.set_margin_start(12)
        self._flow_box.set_margin_end(12)
        self._stack.add_named(self._flow_box, "apps")

        # Empty state
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_label = Gtk.Label(label="No applications found")
        empty_label.add_css_class("dim-label")
        empty_box.append(empty_label)
        self._stack.add_named(empty_box, "empty")

        self._stack.set_visible_child_name("loading")

    def _load_apps(self) -> None:
        """Load installed apps in background thread."""
        self._stack.set_visible_child_name("loading")

        def worker():
            try:
                apps = self._adb.get_installed_apps(third_party_only=True)
                GLib.idle_add(self._on_apps_loaded, apps)
            except Exception as e:
                logger.error(f"Failed to load apps: {e}")
                GLib.idle_add(self._on_apps_loaded, [])

        threading.Thread(target=worker, daemon=True).start()

    def _on_apps_loaded(self, apps: list[AppInfo]) -> None:
        """Called when apps are loaded."""
        self._apps = apps
        self._icon_widgets: dict[str, Gtk.Image] = {}

        # Clear existing
        while child := self._flow_box.get_first_child():
            self._flow_box.remove(child)

        if not apps:
            self._stack.set_visible_child_name("empty")
            return

        # Add app buttons
        for app in apps:
            btn, icon_widget = self._create_app_button(app)
            self._flow_box.append(btn)
            if icon_widget:
                self._icon_widgets[app.package_name] = icon_widget

        self._stack.set_visible_child_name("apps")

        # Load icons asynchronously
        self._load_icons_async()

    def _create_app_button(self, app: AppInfo) -> tuple[Gtk.Button, Gtk.Image | None]:
        """Create a button for an app."""
        btn = Gtk.Button()
        btn.add_css_class("app-button")
        btn.add_css_class("flat")

        if app.is_active:
            btn.add_css_class("active-app")

        # Vertical box for icon area and label
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        # App icon - check cache first, otherwise use placeholder
        icon_widget: Gtk.Image | None = None
        cached_icon = get_cached_icon(app.package_name, self._adb.host)
        
        if cached_icon:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(cached_icon, 48, 48, True)
                icon_widget = Gtk.Image.new_from_pixbuf(pixbuf)
            except Exception:
                icon_widget = None
        
        if not icon_widget:
            icon_widget = Gtk.Image.new_from_icon_name("application-x-executable-symbolic")
            icon_widget.set_pixel_size(48)
        
        box.append(icon_widget)

        # App label
        label = Gtk.Label(label=app.label)
        label.add_css_class("app-label")
        label.set_wrap(True)
        label.set_max_width_chars(12)
        label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        label.set_justify(Gtk.Justification.CENTER)
        box.append(label)

        # Active indicator
        if app.is_active:
            active_label = Gtk.Label(label="● Active")
            active_label.add_css_class("active-indicator")
            box.append(active_label)

        btn.set_child(box)
        btn.set_tooltip_text(app.package_name)

        # Connect click handler
        btn.connect("clicked", lambda *_, pkg=app.package_name: self._on_app_clicked(pkg))

        return btn, icon_widget

    def _on_app_clicked(self, package_name: str) -> None:
        """Handle app button click."""
        if self._on_launch:
            self._on_launch(package_name)
        self.close()

    def _load_icons_async(self) -> None:
        """Load app icons asynchronously in background."""
        def worker():
            for app in self._apps:
                # Skip if we already have a cached icon
                if get_cached_icon(app.package_name, self._adb.host):
                    continue

                # Fetch and cache icon
                icon_path = fetch_and_cache_icon(self._adb, app.package_name)
                if icon_path:
                    GLib.idle_add(self._update_icon, app.package_name, icon_path)

        threading.Thread(target=worker, daemon=True).start()

    def _update_icon(self, package_name: str, icon_path: str) -> None:
        """Update icon widget with loaded icon."""
        icon_widget = self._icon_widgets.get(package_name)
        if not icon_widget:
            return

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 48, 48, True)
            icon_widget.set_from_pixbuf(pixbuf)
        except Exception as e:
            logger.debug(f"Failed to load icon for {package_name}: {e}")

