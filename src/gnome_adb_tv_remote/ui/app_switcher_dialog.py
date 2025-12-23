"""
App Switcher Dialog.

Shows recently used applications for quick switching.
Opened with Ctrl+Tab.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..core.adb_client import AdbTcpClient, AppInfo  # noqa: E402
from ..core.icon_cache import fetch_and_cache_icon, get_cached_icon  # noqa: E402

logger = logging.getLogger(__name__)

# CSS for app switcher
APP_SWITCHER_CSS = """
.app-switcher-item {
    padding: 16px 20px;
    border-radius: 8px;
    transition: background-color 150ms ease;
}

.app-switcher-item:hover {
    background-color: alpha(@accent_color, 0.15);
}

.app-switcher-item.selected {
    background-color: alpha(@accent_color, 0.25);
    border: 2px solid @accent_color;
}

.app-switcher-item.active-app {
    border-left: 4px solid @accent_color;
}

.app-name {
    font-size: 1.1em;
    font-weight: 600;
}

.package-name {
    font-size: 0.8em;
    opacity: 0.7;
}

.active-badge {
    font-size: 0.75em;
    color: @accent_color;
    font-weight: bold;
    background-color: alpha(@accent_color, 0.2);
    padding: 2px 8px;
    border-radius: 4px;
}

.switcher-hint {
    font-size: 0.85em;
    opacity: 0.6;
}
"""


class AppSwitcherDialog(Adw.Dialog):
    """Dialog for switching between recent applications."""

    def __init__(
        self,
        adb_client: AdbTcpClient,
        on_switch: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._adb = adb_client
        self._on_switch = on_switch
        self._apps: list[AppInfo] = []
        self._selected_index = 0
        self._item_boxes: list[Gtk.Box] = []

        self.set_title("Switch Application")
        self.set_content_width(400)
        self.set_content_height(350)

        self._build_ui()
        self._setup_keyboard()
        self._load_apps()

    def _build_ui(self) -> None:
        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(APP_SWITCHER_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gtk.StyleContext.get_display(self.get_style_context()),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Main layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)

        # Header
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        main_box.append(header)

        # Close button
        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.connect("clicked", lambda *_: self.close())
        header.pack_end(close_btn)

        # Content
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content_box.set_margin_top(8)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        content_box.set_vexpand(True)
        main_box.append(content_box)

        # Stack for loading/content states
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_vexpand(True)
        content_box.append(self._stack)

        # Loading spinner
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        loading_box.set_valign(Gtk.Align.CENTER)
        loading_box.set_halign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.set_size_request(32, 32)
        spinner.start()
        loading_box.append(spinner)
        loading_label = Gtk.Label(label="Loading recent apps...")
        loading_label.add_css_class("dim-label")
        loading_box.append(loading_label)
        self._stack.add_named(loading_box, "loading")

        # Apps list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.connect("row-activated", self._on_list_row_activated)
        scrolled.set_child(self._list_box)
        self._stack.add_named(scrolled, "apps")

        # Empty state
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_label = Gtk.Label(label="No recent applications")
        empty_label.add_css_class("dim-label")
        empty_box.append(empty_label)
        self._stack.add_named(empty_box, "empty")

        # Hint at bottom
        hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        hint_box.set_halign(Gtk.Align.CENTER)
        hint_box.set_margin_top(8)

        hint1 = Gtk.Label(label="↑↓ Navigate")
        hint1.add_css_class("switcher-hint")
        hint_box.append(hint1)

        hint2 = Gtk.Label(label="Enter Select")
        hint2.add_css_class("switcher-hint")
        hint_box.append(hint2)

        hint3 = Gtk.Label(label="Esc Close")
        hint3.add_css_class("switcher-hint")
        hint_box.append(hint3)

        content_box.append(hint_box)

        self._stack.set_visible_child_name("loading")

    def _setup_keyboard(self) -> None:
        """Setup keyboard navigation."""
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, _controller, keyval: int, _keycode: int, state: Gdk.ModifierType) -> bool:
        """Handle keyboard navigation."""
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True

        if keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            self._activate_selected()
            return True

        if keyval == Gdk.KEY_Up or keyval == Gdk.KEY_k:
            self._move_selection(-1)
            return True

        if keyval == Gdk.KEY_Down or keyval == Gdk.KEY_j:
            self._move_selection(1)
            return True

        # Tab cycles through apps (Shift+Tab goes backwards)
        if keyval == Gdk.KEY_Tab:
            if state & Gdk.ModifierType.SHIFT_MASK:
                self._move_selection(-1)
            else:
                self._move_selection(1)
            return True

        return False

    def _move_selection(self, delta: int) -> None:
        """Move selection by delta."""
        if not self._apps:
            return

        new_index = (self._selected_index + delta) % len(self._apps)
        self._update_selection(new_index)

    def _update_selection(self, new_index: int) -> None:
        """Update visual selection."""
        # Remove old selection
        if 0 <= self._selected_index < len(self._item_boxes):
            self._item_boxes[self._selected_index].remove_css_class("selected")

        self._selected_index = new_index

        # Add new selection
        if 0 <= self._selected_index < len(self._item_boxes):
            box = self._item_boxes[self._selected_index]
            box.add_css_class("selected")

            # Scroll to visible if needed
            row = box.get_parent()
            if row:
                row.grab_focus()

    def _activate_selected(self) -> None:
        """Launch the selected app."""
        if not self._apps or self._selected_index >= len(self._apps):
            return

        app = self._apps[self._selected_index]
        if self._on_switch:
            self._on_switch(app.package_name)
        self.close()

    def _load_apps(self) -> None:
        """Load recent apps in background thread."""
        self._stack.set_visible_child_name("loading")

        def worker():
            try:
                apps = self._adb.get_recent_apps(limit=10)
                GLib.idle_add(self._on_apps_loaded, apps)
            except Exception as e:
                logger.error(f"Failed to load recent apps: {e}")
                GLib.idle_add(self._on_apps_loaded, [])

        threading.Thread(target=worker, daemon=True).start()

    def _on_apps_loaded(self, apps: list[AppInfo]) -> None:
        """Called when apps are loaded."""
        self._apps = apps
        self._item_boxes = []
        self._icon_widgets: dict[str, Gtk.Image] = {}
        self._selected_index = 0

        # Clear existing
        while child := self._list_box.get_first_child():
            self._list_box.remove(child)

        if not apps:
            self._stack.set_visible_child_name("empty")
            return

        # Add app rows
        for i, app in enumerate(apps):
            row, icon_widget = self._create_app_row(app, i)
            self._list_box.append(row)
            if icon_widget:
                self._icon_widgets[app.package_name] = icon_widget

        # Select first non-active app (for quick switching)
        # If all are active or only one app, select the first
        for i, app in enumerate(apps):
            if not app.is_active and i > 0:
                self._selected_index = i
                break

        # Apply initial selection
        if self._item_boxes:
            self._item_boxes[self._selected_index].add_css_class("selected")

        self._stack.set_visible_child_name("apps")

        # Load icons asynchronously
        self._load_icons_async()

    def _create_app_row(self, app: AppInfo, index: int) -> tuple[Gtk.ListBoxRow, Gtk.Image | None]:
        """Create a row for an app."""
        row = Gtk.ListBoxRow()
        row.set_activatable(True)

        # Main box
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("app-switcher-item")

        if app.is_active:
            box.add_css_class("active-app")

        # Icon - check cache first
        cached_icon = get_cached_icon(app.package_name, self._adb.host)

        if cached_icon:
            try:
                icon_widget = Gtk.Picture.new_for_filename(cached_icon)
                icon_widget.set_size_request(32, 32)
                icon_widget.set_content_fit(Gtk.ContentFit.CONTAIN)
            except Exception:
                icon_widget = Gtk.Image.new_from_icon_name("application-x-executable-symbolic")
                icon_widget.set_pixel_size(32)
        else:
            icon_widget = Gtk.Image.new_from_icon_name("application-x-executable-symbolic")
            icon_widget.set_pixel_size(32)

        box.append(icon_widget)

        # Text content
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        # App name
        name_label = Gtk.Label(label=app.label)
        name_label.add_css_class("app-name")
        name_label.set_halign(Gtk.Align.START)
        name_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        text_box.append(name_label)

        # Package name
        pkg_label = Gtk.Label(label=app.package_name)
        pkg_label.add_css_class("package-name")
        pkg_label.set_halign(Gtk.Align.START)
        pkg_label.set_ellipsize(3)
        text_box.append(pkg_label)

        box.append(text_box)

        # Active badge
        if app.is_active:
            badge = Gtk.Label(label="Active")
            badge.add_css_class("active-badge")
            badge.set_valign(Gtk.Align.CENTER)
            box.append(badge)

        row.set_child(box)

        self._item_boxes.append(box)
        return row, icon_widget

    def _on_list_row_activated(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """Handle row click/activation."""
        index = row.get_index()
        self._selected_index = index
        self._activate_selected()

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
            # Replace the Image widget with a Picture widget
            parent = icon_widget.get_parent()
            if parent:
                new_icon = Gtk.Picture.new_for_filename(icon_path)
                new_icon.set_size_request(32, 32)
                new_icon.set_content_fit(Gtk.ContentFit.CONTAIN)
                
                # Insert at the beginning (before text)
                parent.remove(icon_widget)
                parent.prepend(new_icon)
                
                self._icon_widgets[package_name] = new_icon
        except Exception as e:
            logger.debug(f"Failed to load icon for {package_name}: {e}")

