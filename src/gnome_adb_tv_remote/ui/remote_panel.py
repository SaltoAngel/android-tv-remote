"""
Remote Control Panel Widget.

This module provides the RemotePanel class, the main remote control interface
that displays navigation buttons, volume controls, media buttons, and a text
input area. Button presses are translated to ADB key events.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402
import os

from ..core.adb_client import DeviceInfo  # noqa: E402

# Path to material icons
def get_icons_dir():
    # Check Flatpak path first
    flatpak_path = "/app/share/io.github.erenseymen.TvRemote/icons/material"
    if os.path.exists(flatpak_path):
        return flatpak_path
    # Fallback to local development path
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/icons/material"))

ICONS_DIR = get_icons_dir()


# CSS for larger button fonts
BUTTON_CSS = """
button.remote-button {
    padding: 12px;
    min-width: 80px;
    min-height: 80px;
}

button.remote-button image {
    -gtk-icon-style: symbolic;
}

button.remote-button label.caption {
    font-size: 0.8em;
    font-weight: 700;
    opacity: 0.9;
    margin-top: 4px;
}
"""


# Mapping from ADB keycode to action name (for tooltip lookup)
KEYCODE_TO_ACTION: dict[str, str] = {
    "KEYCODE_DPAD_UP": "dpad-up",
    "KEYCODE_DPAD_DOWN": "dpad-down",
    "KEYCODE_DPAD_LEFT": "dpad-left",
    "KEYCODE_DPAD_RIGHT": "dpad-right",
    "KEYCODE_DPAD_CENTER": "dpad-center",
    "KEYCODE_BACK": "back",
    "KEYCODE_HOME": "home",
    "KEYCODE_MENU": "menu",
    "KEYCODE_VOLUME_UP": "volume-up",
    "KEYCODE_VOLUME_DOWN": "volume-down",
    "KEYCODE_VOLUME_MUTE": "volume-mute",
    "KEYCODE_POWER": "power",
    "KEYCODE_MEDIA_PLAY_PAUSE": "play-pause",
    "KEYCODE_ALL_APPS": "apps",
}


class RemotePanel(Gtk.Box):
    """Remote control panel widget with navigation and media buttons.
    
    Displays a grid of buttons for D-pad navigation, system controls,
    volume, and media playback. Also provides a keyboard input area
    for typing text on the connected device.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(18)
        self.set_margin_bottom(18)
        self.set_margin_start(18)
        self.set_margin_end(18)
        
        # Apply CSS for larger button fonts
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(BUTTON_CSS.encode())
        self.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._title = Adw.WindowTitle(title="Remote", subtitle="Connect to a device to enable controls")
        self.append(self._title)

        # Connection status indicator
        self._status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._status_box.set_halign(Gtk.Align.CENTER)
        self._status_box.set_margin_top(8)
        self._status_box.set_margin_bottom(8)
        
        self._status_spinner = Gtk.Spinner()
        self._status_spinner.set_size_request(16, 16)
        self._status_box.append(self._status_spinner)
        
        self._status_label = Gtk.Label()
        self._status_label.add_css_class("dim-label")
        self._status_box.append(self._status_label)
        
        self._status_box.set_visible(False)
        self.append(self._status_box)

        self._grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self._grid.set_column_homogeneous(True)
        self._grid.set_row_homogeneous(True)
        self.append(self._grid)

        self._on_keyevent = None
        self._on_text = None

        # Map keycode -> button for visual feedback
        self._keycode_buttons: dict[str, Gtk.Button] = {}
        # Map keycode -> shortcut label for updating shortcuts
        self._keycode_shortcut_labels: dict[str, Gtk.Label] = {}
        # Search button (special, sends text instead of keycode)
        self._search_button: Gtk.Button | None = None
        self._search_shortcut_label: Gtk.Label | None = None

        # D-pad
        self._add_key_button("Up", "KEYCODE_DPAD_UP", 1, 0, icon_name="keyboard_arrow_up-symbolic.svg")
        self._add_key_button("Left", "KEYCODE_DPAD_LEFT", 0, 1, icon_name="keyboard_arrow_left-symbolic.svg")
        self._add_key_button("Enter", "KEYCODE_DPAD_CENTER", 1, 1, icon_name="fiber_manual_record-symbolic.svg")
        self._add_key_button("Right", "KEYCODE_DPAD_RIGHT", 2, 1, icon_name="keyboard_arrow_right-symbolic.svg")
        self._add_key_button("Down", "KEYCODE_DPAD_DOWN", 1, 2, icon_name="keyboard_arrow_down-symbolic.svg")

        # System
        self._add_key_button("Back", "KEYCODE_BACK", 0, 3, icon_name="arrow_back-symbolic.svg")
        self._add_key_button("Home", "KEYCODE_HOME", 1, 3, icon_name="home-symbolic.svg")
        self._add_key_button("Menu", "KEYCODE_MENU", 2, 3, icon_name="menu-symbolic.svg")

        # Volume
        self._add_key_button("Vol-", "KEYCODE_VOLUME_DOWN", 0, 4, icon_name="volume_down-symbolic.svg")
        self._add_key_button("Mute", "KEYCODE_VOLUME_MUTE", 1, 4, icon_name="volume_off-symbolic.svg")
        self._add_key_button("Vol+", "KEYCODE_VOLUME_UP", 2, 4, icon_name="volume_up-symbolic.svg")

        # Media
        self._add_key_button("Apps", "KEYCODE_ALL_APPS", 0, 5, icon_name="apps-symbolic.svg")
        self._add_key_button("Play/Pause", "KEYCODE_MEDIA_PLAY_PAUSE", 1, 5, icon_name=["play_arrow-symbolic.svg", "pause-symbolic.svg"])
        
        # Search button (sends text "s" for YouTube search) - moved to row 5, col 2
        self._add_search_button(2, 5, icon_name="search-symbolic.svg")

        # Keyboard input area - keystrokes are sent directly to Android TV
        self._keyboard_entry = Gtk.Entry(placeholder_text="Focus keyboard for text input")
        self._keyboard_entry.set_hexpand(True)
        self._keyboard_entry.set_editable(False)  # Disable text input, we handle keys manually
        self._keyboard_focused = False
        
        # Add focus state tracking
        focus_controller = Gtk.EventControllerFocus()
        focus_controller.connect("enter", self._on_keyboard_focus_enter)
        focus_controller.connect("leave", self._on_keyboard_focus_leave)
        self._keyboard_entry.add_controller(focus_controller)
        
        self.append(self._keyboard_entry)

    def set_handlers(self, *, on_keyevent=None, on_text=None) -> None:
        self._on_keyevent = on_keyevent
        self._on_text = on_text

    def update_tooltips(self, settings: Gio.Settings) -> None:
        """Update button shortcut labels based on current keyboard shortcuts."""
        from .preferences_dialog import get_action_tooltip, DEFAULT_SHORTCUTS, _load_shortcuts_dict

        # Load current shortcuts to compare with defaults
        current_shortcuts = _load_shortcuts_dict(settings)

        # Mapping from keycode to action for direction buttons
        direction_keycodes = {
            "KEYCODE_DPAD_UP": "dpad-up",
            "KEYCODE_DPAD_DOWN": "dpad-down",
            "KEYCODE_DPAD_LEFT": "dpad-left",
            "KEYCODE_DPAD_RIGHT": "dpad-right",
        }
        
        for keycode, shortcut_label in self._keycode_shortcut_labels.items():
            action = KEYCODE_TO_ACTION.get(keycode)
            
            # Special handling for direction buttons: only show if changed from default
            if keycode in direction_keycodes:
                action = direction_keycodes[keycode]
                current_keys = current_shortcuts.get(action, [])
                default_keys = DEFAULT_SHORTCUTS.get(action, [])
                
                # Only show shortcut if it differs from default
                if current_keys != default_keys:
                    shortcut_text = get_action_tooltip(action, settings)
                    if shortcut_text:
                        shortcut_label.set_markup(f"<b>{shortcut_text}</b>")
                        shortcut_label.set_visible(True)
                    else:
                        shortcut_label.set_text("")
                        shortcut_label.set_visible(False)
                else:
                    shortcut_label.set_visible(False)
                continue
            
            # Special handling for Enter (dpad-center): update button label if changed
            if keycode == "KEYCODE_DPAD_CENTER":
                current_keys = current_shortcuts.get("dpad-center", [])
                default_keys = DEFAULT_SHORTCUTS.get("dpad-center", [])
                shortcut_text = get_action_tooltip("dpad-center", settings)
                
                # Update Enter button label with new shortcut
                # Since we use an icon now, we don't update the main label text
                # Logic kept here if we ever want to revert or handle tooltip
                pass
                
                # Show shortcut label only if changed from default
                if current_keys != default_keys:
                    if shortcut_text:
                        shortcut_label.set_markup(f"<b>{shortcut_text}</b>")
                        shortcut_label.set_visible(True)
                    else:
                        shortcut_label.set_visible(False)
                else:
                    shortcut_label.set_visible(False)
                continue

            # Standard buttons: always show shortcut
            if action:
                shortcut_text = get_action_tooltip(action, settings)
                if shortcut_text:
                    shortcut_label.set_markup(f"<b>{shortcut_text}</b>")
                    shortcut_label.set_visible(True)
                else:
                    shortcut_label.set_text("")
                    shortcut_label.set_visible(False)
        
        # Update keyboard entry placeholder with focus shortcut
        focus_tooltip = get_action_tooltip("focus-keyboard", settings)
        if focus_tooltip:
            self._keyboard_entry.set_placeholder_text(f"Press {focus_tooltip} to focus keyboard")
        
        # Update search button shortcut label
        if self._search_shortcut_label:
            search_tooltip = get_action_tooltip("search", settings)
            if search_tooltip:
                self._search_shortcut_label.set_markup(f"<b>{search_tooltip}</b>")
                self._search_shortcut_label.set_visible(True)
            else:
                self._search_shortcut_label.set_text("")
                self._search_shortcut_label.set_visible(False)

    def set_connection_status(self, status: str | None) -> None:
        """Set connection status message.
        
        Args:
            status: Status message to display, or None to hide the status.
        """
        if status:
            self._status_label.set_text(status)
            self._status_spinner.start()
            self._status_box.set_visible(True)
        else:
            self._status_spinner.stop()
            self._status_box.set_visible(False)

    def update_device_info(self, info: DeviceInfo | None = None, ip: str | None = None) -> None:
        if info and ip:
            self._title.set_title(GLib.markup_escape_text(f"{info.manufacturer} {info.model}"))
            self._title.set_subtitle(GLib.markup_escape_text(f"Connected to {ip} (Android {info.version})"))
        else:
            self._title.set_title("Remote")
            self._title.set_subtitle("Connect to a device to enable controls")

    def _on_keyboard_focus_enter(self, *_args) -> None:
        """Called when keyboard input area gains focus."""
        self._keyboard_focused = True
        self._keyboard_entry.set_placeholder_text("Type or Ctrl+V to paste (Esc to exit)")

    def _on_keyboard_focus_leave(self, *_args) -> None:
        """Called when keyboard input area loses focus."""
        self._keyboard_focused = False
        self._keyboard_entry.set_placeholder_text("Press K to focus keyboard")

    @property
    def keyboard_focused(self) -> bool:
        """Returns True if the keyboard input area is focused."""
        return self._keyboard_focused

    def focus_keyboard(self) -> None:
        """Focus the keyboard input area."""
        self._keyboard_entry.grab_focus()

    def handle_keyboard_key(self, keyval: int) -> bool:
        """Handle keystrokes in keyboard mode - send them directly to Android TV.
        
        Called by MainWindow when keyboard is focused. Returns True if key was handled.
        """
        # Escape: return focus to the OK button (center of D-pad)
        if keyval == Gdk.KEY_Escape:
            ok_btn = self._keycode_buttons.get("KEYCODE_DPAD_CENTER")
            if ok_btn:
                ok_btn.grab_focus()
            return True
        
        # Enter: send KEYCODE_ENTER for text confirmation
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if self._on_keyevent:
                self._on_keyevent("KEYCODE_ENTER")
            return True
        
        # Backspace: send KEYCODE_DEL to delete character on TV
        if keyval == Gdk.KEY_BackSpace:
            if self._on_keyevent:
                self._on_keyevent("KEYCODE_DEL")
            return True
        
        # Delete key: also send KEYCODE_DEL
        if keyval == Gdk.KEY_Delete:
            if self._on_keyevent:
                self._on_keyevent("KEYCODE_FORWARD_DEL")
            return True
        
        # Tab: send Tab keycode
        if keyval == Gdk.KEY_Tab:
            if self._on_keyevent:
                self._on_keyevent("KEYCODE_TAB")
            return True
        
        # Ignore modifier keys alone
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, 
                      Gdk.KEY_Control_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
                      Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Caps_Lock):
            return False
        
        # Convert keyval to character and send as text
        char = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else None
        if char and char.isprintable():
            if self._on_text:
                self._on_text(char)
            return True
        
        return False

    def flash_button(self, keycode: str) -> None:
        """Flash the button corresponding to the keycode to show visual feedback.
        
        This is called when a keyboard shortcut triggers a key event,
        so the user can see which button was activated.
        """
        btn = self._keycode_buttons.get(keycode)
        if not btn:
            return
        # Add a CSS class for the "pressed" state
        btn.add_css_class("suggested-action")

        # Remove the class after a short delay
        def remove_flash():
            btn.remove_css_class("suggested-action")
            return False  # Don't repeat

        GLib.timeout_add(150, remove_flash)

    def _add_key_button(self, label: str, keycode: str, col: int, row: int, icon_name: str | list[str] | None = None) -> None:
        # Create button
        btn = Gtk.Button()
        btn.add_css_class("remote-button")
        # Ensure the buttons are accessible/labelled even if showing icon
        btn.set_tooltip_text(label)
        
        btn.connect("clicked", lambda *_: self._on_keyevent and self._on_keyevent(keycode))
        btn.set_hexpand(True)
        btn.set_vexpand(True)
        
        # Create vertical box for content and shortcut
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        
        # Main content (Icon or Label)
        if icon_name:
            if isinstance(icon_name, list):
                icon_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                icon_box.set_halign(Gtk.Align.CENTER)
                for name in icon_name:
                    image = self._create_icon(name)
                    icon_box.append(image)
                box.append(icon_box)
            else:
                image = self._create_icon(icon_name)
                box.append(image)
        else:
            main_label = Gtk.Label(label=label)
            # Make text label bold if no icon
            main_label.set_markup(f"<b>{label}</b>")
            box.append(main_label)
        
        # Shortcut label (bold, same as Enter button)
        shortcut_label = Gtk.Label()
        shortcut_label.set_visible(False)  # Will be shown when shortcuts are loaded
        box.append(shortcut_label)
        
        # Set box as button child
        btn.set_child(box)
        
        self._grid.attach(btn, col, row, 1, 1)

        # Register button and shortcut label for updates
        self._keycode_buttons[keycode] = btn
        self._keycode_shortcut_labels[keycode] = shortcut_label

    def _add_search_button(self, col: int, row: int, icon_name: str | None = None) -> None:
        """Add Search button that sends text 's' for YouTube search."""
        # Create button
        btn = Gtk.Button()
        btn.add_css_class("remote-button")
        btn.set_hexpand(True)
        btn.set_vexpand(True)
        btn.set_tooltip_text("YouTube Search")
        btn.connect("clicked", lambda *_: self._on_text and self._on_text("s"))
        
        # Create vertical box for label and shortcut
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        
        # Main content
        if icon_name:
            image = self._create_icon(icon_name)
            box.append(image)
        else:
            main_label = Gtk.Label(label="YouTube Search")
            box.append(main_label)
        
        # Shortcut label (bold, same as Enter button)
        shortcut_label = Gtk.Label()
        shortcut_label.set_visible(False)  # Will be shown when shortcuts are loaded
        box.append(shortcut_label)
        
        # Set box as button child
        btn.set_child(box)
        
        # Attach to grid, single column width
        self._grid.attach(btn, col, row, 1, 1)
        
        # Store references
        self._search_button = btn
        self._search_shortcut_label = shortcut_label

    def _create_icon(self, icon_name: str) -> Gtk.Image:
        """Create an icon from a file path or icon name."""
        if icon_name.endswith(".svg"):
            path = os.path.join(ICONS_DIR, icon_name)
            if os.path.exists(path):
                image = Gtk.Image.new_from_file(path)
                image.set_pixel_size(24)
                return image
        
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_pixel_size(24)
        return image



