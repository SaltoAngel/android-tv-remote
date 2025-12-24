"""
Shared Icon Loading Utilities.

Provides common icon loading functionality used by App Launcher and App Switcher dialogs.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk  # noqa: E402

if TYPE_CHECKING:
    from ..core.adb_client import AdbTcpClient, AppInfo

from ..core.icon_cache import fetch_and_cache_icon, get_cached_icon  # noqa: E402

logger = logging.getLogger(__name__)


def load_icons_in_background(
    apps: list["AppInfo"],
    adb_client: "AdbTcpClient",
    on_icon_loaded: Callable[[str, str], None],
) -> None:
    """Load app icons asynchronously in background.
    
    Args:
        apps: List of AppInfo objects to load icons for.
        adb_client: The ADB client instance.
        on_icon_loaded: Callback(package_name, icon_path) called on main thread when icon is loaded.
    """
    def worker():
        for app in apps:
            # Skip if we already have a cached icon
            if get_cached_icon(app.package_name, adb_client.host):
                continue

            # Fetch and cache icon
            icon_path = fetch_and_cache_icon(adb_client, app.package_name)
            if icon_path:
                GLib.idle_add(on_icon_loaded, app.package_name, icon_path)

    threading.Thread(target=worker, daemon=True).start()


def update_icon_widget(
    icon_widgets: dict[str, Gtk.Widget],
    package_name: str,
    icon_path: str,
    size: int = 48,
) -> None:
    """Update an icon widget with a loaded icon file.
    
    Replaces the placeholder Image widget with a Picture widget showing the icon.
    
    Args:
        icon_widgets: Dictionary mapping package names to icon widgets.
        package_name: The package name of the app.
        icon_path: Path to the icon file.
        size: Size of the icon (width and height).
    """
    icon_widget = icon_widgets.get(package_name)
    if not icon_widget:
        return

    try:
        # Replace the Image widget with a Picture widget
        parent = icon_widget.get_parent()
        if parent:
            new_icon = Gtk.Picture.new_for_filename(icon_path)
            new_icon.set_size_request(size, size)
            new_icon.set_content_fit(Gtk.ContentFit.CONTAIN)
            
            # Replace in parent (prepend to keep icon at the start)
            parent.remove(icon_widget)
            parent.prepend(new_icon)
            
            icon_widgets[package_name] = new_icon
    except Exception as e:
        logger.debug(f"Failed to load icon for {package_name}: {e}")


def create_app_icon(
    package_name: str,
    device_ip: str,
    size: int = 48,
) -> Gtk.Widget:
    """Create an icon widget for an app.
    
    Returns a Picture widget if a cached icon exists, otherwise an Image placeholder.
    
    Args:
        package_name: The app's package name.
        device_ip: The device IP address.
        size: Size of the icon (width and height).
        
    Returns:
        Gtk.Picture for cached icons, Gtk.Image placeholder otherwise.
    """
    cached_icon = get_cached_icon(package_name, device_ip)
    
    if cached_icon:
        try:
            icon_widget = Gtk.Picture.new_for_filename(cached_icon)
            icon_widget.set_size_request(size, size)
            icon_widget.set_content_fit(Gtk.ContentFit.CONTAIN)
            return icon_widget
        except Exception:
            pass
    
    # Fallback to placeholder
    icon_widget = Gtk.Image.new_from_icon_name("application-x-executable-symbolic")
    icon_widget.set_pixel_size(size)
    return icon_widget
