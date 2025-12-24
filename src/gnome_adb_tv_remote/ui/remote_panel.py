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

from ..core.adb_client import DeviceInfo, DeviceStatus  # noqa: E402

# Path to material icons
def get_icons_dir():
    # Check Flatpak path first
    flatpak_path = "/app/share/io.github.erenseymen.android-tv-remote/icons/material"
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
    "KEYCODE_MEDIA_PLAY_PAUSE": "play-pause",
    "KEYCODE_MEDIA_PREVIOUS": "previous",
    "KEYCODE_MEDIA_NEXT": "next",
    "KEYCODE_MEDIA_REWIND": "rewind",
    "KEYCODE_MEDIA_FAST_FORWARD": "fast-forward",
    "KEYCODE_ALL_APPS": "apps",
    "KEYCODE_ASSIST": "assistant",
    "KEYCODE_CAPTIONS": "captions",
    "KEYCODE_TV_INPUT": "tv-input",
    "KEYCODE_CHANNEL_UP": "channel-up",
    "KEYCODE_CHANNEL_DOWN": "channel-down",
    "KEYCODE_GUIDE": "guide",
    "KEYCODE_INFO": "info",
    "KEYCODE_SETTINGS": "settings",
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
        self._add_key_button("Back", "KEYCODE_BACK", 0, 3, icon_name="edit-undo-symbolic")
        self._add_key_button("Home", "KEYCODE_HOME", 1, 3, icon_name="user-home-symbolic")
        self._add_key_button("Menu", "KEYCODE_MENU", 2, 3, icon_name="view-list-symbolic")

        # Volume
        self._add_key_button("Vol-", "KEYCODE_VOLUME_DOWN", 0, 4, icon_name="audio-volume-low-symbolic")
        self._add_key_button("Mute", "KEYCODE_VOLUME_MUTE", 1, 4, icon_name="audio-volume-muted-symbolic")
        self._add_key_button("Vol+", "KEYCODE_VOLUME_UP", 2, 4, icon_name="audio-volume-high-symbolic")

        # Media - Row 5: Rewind, Play/Pause, Fast Forward
        self._add_key_button("Rewind", "KEYCODE_MEDIA_REWIND", 0, 5, icon_name="media-seek-backward-symbolic")
        self._add_key_button("Play/Pause", "KEYCODE_MEDIA_PLAY_PAUSE", 1, 5, icon_name=["media-playback-start-symbolic", "media-playback-pause-symbolic"])
        self._add_key_button("Fast Forward", "KEYCODE_MEDIA_FAST_FORWARD", 2, 5, icon_name="media-seek-forward-symbolic")
        
        # Media - Row 6: Prev, Stop (placeholder), Next
        self._add_key_button("Prev", "KEYCODE_MEDIA_PREVIOUS", 0, 6, icon_name="media-skip-backward-symbolic")
        self._add_key_button("Subtitles", "KEYCODE_CAPTIONS", 1, 6, icon_name="media-view-subtitles-symbolic")
        self._add_key_button("Next", "KEYCODE_MEDIA_NEXT", 2, 6, icon_name="media-skip-forward-symbolic")
        
        # System - Row 7: Apps, Assistant, Search
        self._add_key_button("Apps", "KEYCODE_ALL_APPS", 0, 7, icon_name="view-app-grid-symbolic")
        self._add_search_button(1, 7, icon_name="system-search-symbolic")
        self._add_key_button("Assistant", "KEYCODE_ASSIST", 2, 7, icon_name="audio-input-microphone-symbolic")

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
        
        # Device Status Bar
        self._device_status_bar = self._build_status_bar()
        self.append(self._device_status_bar)
        
        # Advanced Controls - Expandable section
        self._advanced_expander = Gtk.Expander(label="Advanced Controls")
        self._advanced_expander.set_margin_top(12)
        self._build_advanced_controls()
        self.append(self._advanced_expander)

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
        
        # Human-readable names for tooltip
        direction_names = {
            "KEYCODE_DPAD_UP": "Up",
            "KEYCODE_DPAD_DOWN": "Down",
            "KEYCODE_DPAD_LEFT": "Left",
            "KEYCODE_DPAD_RIGHT": "Right",
        }
        
        for keycode, shortcut_label in self._keycode_shortcut_labels.items():
            action = KEYCODE_TO_ACTION.get(keycode)
            
            # Special handling for direction buttons: only show if changed from default
            if keycode in direction_keycodes:
                action = direction_keycodes[keycode]
                
                # Update tooltip to show all shortcuts
                shortcut_text = get_action_tooltip(action, settings)
                if shortcut_text:
                    btn = self._keycode_buttons.get(keycode)
                    if btn:
                        btn.set_tooltip_text(f"{direction_names[keycode]}: {shortcut_text}")
                
                # Never show shortcut label on direction buttons (UI requirement)
                shortcut_label.set_visible(False)
                continue
            
            # Special handling for Enter (dpad-center): update button label if changed
            if keycode == "KEYCODE_DPAD_CENTER":
                shortcut_text = get_action_tooltip("dpad-center", settings)
                
                # Update tooltip to show all shortcuts
                if shortcut_text:
                    btn = self._keycode_buttons.get(keycode)
                    if btn:
                        btn.set_tooltip_text(f"OK / Select: {shortcut_text}")
                
                # Never show shortcut label on center button (UI requirement)
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

    def _build_status_bar(self) -> Gtk.Box:
        """Build the device status bar showing volume, power, etc."""
        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status_bar.set_halign(Gtk.Align.CENTER)
        status_bar.set_margin_top(12)
        status_bar.set_margin_bottom(4)
        status_bar.add_css_class("dim-label")
        status_bar.set_visible(False)  # Hidden until connected
        
        # Screen status indicator
        self._screen_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._screen_status_icon = Gtk.Image.new_from_icon_name("display-brightness-symbolic")
        self._screen_status_icon.set_pixel_size(16)
        self._screen_status_label = Gtk.Label(label="Screen: --")
        self._screen_status_box.append(self._screen_status_icon)
        self._screen_status_box.append(self._screen_status_label)
        status_bar.append(self._screen_status_box)
        
        # Separator
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        status_bar.append(sep1)
        
        # Volume indicator
        self._volume_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._volume_status_icon = Gtk.Image.new_from_icon_name("audio-volume-medium-symbolic")
        self._volume_status_icon.set_pixel_size(16)
        self._volume_status_label = Gtk.Label(label="Vol: --")
        self._volume_status_box.append(self._volume_status_icon)
        self._volume_status_box.append(self._volume_status_label)
        status_bar.append(self._volume_status_box)
        
        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        status_bar.append(sep2)
        
        # Memory indicator
        self._memory_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._memory_status_icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        self._memory_status_icon.set_pixel_size(16)
        self._memory_status_label = Gtk.Label(label="Mem: --")
        self._memory_status_box.append(self._memory_status_icon)
        self._memory_status_box.append(self._memory_status_label)
        status_bar.append(self._memory_status_box)
        
        return status_bar

    def update_device_status(self, status: DeviceStatus | None) -> None:
        """Update the device status bar with current status info."""
        if status is None:
            self._device_status_bar.set_visible(False)
            return
        
        self._device_status_bar.set_visible(True)
        
        # Update screen status
        if status.screen_on:
            self._screen_status_label.set_text("Screen: On")
            self._screen_status_icon.set_from_icon_name("display-brightness-symbolic")
        else:
            self._screen_status_label.set_text("Screen: Off")
            self._screen_status_icon.set_from_icon_name("display-brightness-symbolic")
        
        # Update volume status
        if status.volume_max > 0:
            vol_percent = int((status.volume_level / status.volume_max) * 100)
            self._volume_status_label.set_text(f"Vol: {status.volume_level}/{status.volume_max}")
            
            # Update icon based on volume level
            if status.volume_level == 0:
                self._volume_status_icon.set_from_icon_name("audio-volume-muted-symbolic")
            elif vol_percent < 33:
                self._volume_status_icon.set_from_icon_name("audio-volume-low-symbolic")
            elif vol_percent < 66:
                self._volume_status_icon.set_from_icon_name("audio-volume-medium-symbolic")
            else:
                self._volume_status_icon.set_from_icon_name("audio-volume-high-symbolic")
        
        # Update memory status
        if status.memory_total_mb > 0:
            mem_used_gb = status.memory_used_mb / 1024
            mem_total_gb = status.memory_total_mb / 1024
            self._memory_status_label.set_text(f"Mem: {mem_used_gb:.1f}/{mem_total_gb:.1f}GB")

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

    def _build_advanced_controls(self) -> None:
        """Build the advanced controls section with TV-specific buttons."""
        advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        advanced_box.set_margin_top(8)
        
        # TV Controls Grid
        tv_grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        tv_grid.set_column_homogeneous(True)
        
        # Row 0: TV Input, Guide, Info, Settings
        self._add_advanced_button(tv_grid, "Input", "KEYCODE_TV_INPUT", 0, 0, icon_name="video-display-symbolic")
        self._add_advanced_button(tv_grid, "Guide", "KEYCODE_GUIDE", 1, 0, icon_name="x-office-calendar-symbolic")
        self._add_advanced_button(tv_grid, "Info", "KEYCODE_INFO", 2, 0, icon_name="dialog-information-symbolic")
        self._add_advanced_button(tv_grid, "Settings", "KEYCODE_SETTINGS", 3, 0, icon_name="emblem-system-symbolic")
        
        # Row 1: Channel controls
        self._add_advanced_button(tv_grid, "CH-", "KEYCODE_CHANNEL_DOWN", 0, 1, icon_name="go-down-symbolic")
        self._add_advanced_button(tv_grid, "CH+", "KEYCODE_CHANNEL_UP", 3, 1, icon_name="go-up-symbolic")
        
        advanced_box.append(tv_grid)
        
        # Numpad section
        numpad_label = Gtk.Label(label="Number Pad (Channel Input)")
        numpad_label.add_css_class("dim-label")
        numpad_label.set_margin_top(12)
        numpad_label.set_halign(Gtk.Align.START)
        advanced_box.append(numpad_label)
        
        numpad_grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        numpad_grid.set_column_homogeneous(True)
        
        # Standard numpad layout: 
        # 1 2 3
        # 4 5 6
        # 7 8 9
        #   0
        self._add_numpad_button(numpad_grid, "1", "KEYCODE_1", 0, 0)
        self._add_numpad_button(numpad_grid, "2", "KEYCODE_2", 1, 0)
        self._add_numpad_button(numpad_grid, "3", "KEYCODE_3", 2, 0)
        self._add_numpad_button(numpad_grid, "4", "KEYCODE_4", 0, 1)
        self._add_numpad_button(numpad_grid, "5", "KEYCODE_5", 1, 1)
        self._add_numpad_button(numpad_grid, "6", "KEYCODE_6", 2, 1)
        self._add_numpad_button(numpad_grid, "7", "KEYCODE_7", 0, 2)
        self._add_numpad_button(numpad_grid, "8", "KEYCODE_8", 1, 2)
        self._add_numpad_button(numpad_grid, "9", "KEYCODE_9", 2, 2)
        self._add_numpad_button(numpad_grid, "0", "KEYCODE_0", 1, 3)
        
        advanced_box.append(numpad_grid)
        
        # Colored buttons section
        color_label = Gtk.Label(label="Color Keys (Teletext/HbbTV)")
        color_label.add_css_class("dim-label")
        color_label.set_margin_top(12)
        color_label.set_halign(Gtk.Align.START)
        advanced_box.append(color_label)
        
        color_grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        color_grid.set_column_homogeneous(True)
        
        # Colored buttons with actual colors
        self._add_color_button(color_grid, "Red", "KEYCODE_PROG_RED", 0, 0, "#e74c3c")
        self._add_color_button(color_grid, "Green", "KEYCODE_PROG_GREEN", 1, 0, "#2ecc71")
        self._add_color_button(color_grid, "Yellow", "KEYCODE_PROG_YELLOW", 2, 0, "#f1c40f")
        self._add_color_button(color_grid, "Blue", "KEYCODE_PROG_BLUE", 3, 0, "#3498db")
        
        advanced_box.append(color_grid)
        
        self._advanced_expander.set_child(advanced_box)

    def _add_advanced_button(self, grid: Gtk.Grid, label: str, keycode: str, col: int, row: int, icon_name: str | None = None) -> None:
        """Add a button to the advanced controls grid."""
        btn = Gtk.Button()
        btn.set_tooltip_text(label)
        btn.connect("clicked", lambda *_: self._on_keyevent and self._on_keyevent(keycode))
        btn.set_hexpand(True)
        
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.set_halign(Gtk.Align.CENTER)
        
        if icon_name:
            image = Gtk.Image.new_from_icon_name(icon_name)
            image.set_pixel_size(16)
            box.append(image)
        
        text_label = Gtk.Label(label=label)
        box.append(text_label)
        
        btn.set_child(box)
        grid.attach(btn, col, row, 1, 1)
        
        self._keycode_buttons[keycode] = btn

    def _add_numpad_button(self, grid: Gtk.Grid, label: str, keycode: str, col: int, row: int) -> None:
        """Add a numpad button for channel input."""
        btn = Gtk.Button(label=label)
        btn.set_tooltip_text(f"Number {label}")
        btn.connect("clicked", lambda *_: self._on_keyevent and self._on_keyevent(keycode))
        btn.set_hexpand(True)
        
        # Make numpad buttons slightly larger and more prominent
        btn.add_css_class("flat")
        
        grid.attach(btn, col, row, 1, 1)
        
        self._keycode_buttons[keycode] = btn

    def _add_color_button(self, grid: Gtk.Grid, label: str, keycode: str, col: int, row: int, color: str) -> None:
        """Add a colored button for teletext/HbbTV."""
        btn = Gtk.Button(label=label)
        btn.set_tooltip_text(f"{label} Button")
        btn.connect("clicked", lambda *_: self._on_keyevent and self._on_keyevent(keycode))
        btn.set_hexpand(True)
        
        # Apply custom CSS for this button's color
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(f"""
            button {{
                background-color: {color};
                color: white;
                font-weight: bold;
            }}
            button:hover {{
                background-color: shade({color}, 1.1);
            }}
        """)
        btn.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        grid.attach(btn, col, row, 1, 1)
        
        self._keycode_buttons[keycode] = btn

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
        btn.set_tooltip_text("Find (YouTube)")
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
            main_label = Gtk.Label(label="Find (YouTube)")
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
        """Create an icon from a file path or icon name.
        
        Uses Gio.FileIcon to load SVG files as symbolic icons,
        which allows them to adapt their color to the current theme.
        """
        if icon_name.endswith(".svg"):
            path = os.path.join(ICONS_DIR, icon_name)
            if os.path.exists(path):
                # Load as GIcon to get proper symbolic icon theming
                file = Gio.File.new_for_path(path)
                gicon = Gio.FileIcon.new(file)
                image = Gtk.Image.new_from_gicon(gicon)
                image.set_pixel_size(24)
                return image
        
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_pixel_size(24)
        return image



