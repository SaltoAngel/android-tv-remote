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

from ..core.adb_client import DeviceInfo  # noqa: E402
from .ui_utils import create_icon, flash_button  # noqa: E402


# CSS for larger button fonts and volume slider
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

.volume-slider-box {
    margin-top: 8px;
    margin-bottom: 8px;
}

.volume-slider-box scale {
    min-height: 32px;
}

.volume-slider-box scale trough {
    min-height: 8px;
    border-radius: 4px;
}

.volume-slider-box scale highlight {
    border-radius: 4px;
}

.volume-mute-button {
    min-width: 40px;
    min-height: 40px;
    padding: 8px;
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
    "KEYCODE_VOLUME_MUTE": "volume-mute",
    "KEYCODE_MEDIA_PLAY_PAUSE": "play-pause",
    "KEYCODE_MEDIA_PREVIOUS": "previous",
    "KEYCODE_MEDIA_NEXT": "next",
    "KEYCODE_ALL_APPS": "apps",
    "KEYCODE_ASSIST": "assistant",
    "KEYCODE_CAPTIONS": "captions",
    "KEYCODE_TV_INPUT": "tv-input",
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
        
        # Volume slider components
        self._volume_slider: Gtk.Scale | None = None
        self._mute_button: Gtk.Button | None = None
        self._volume_max: int = 15  # Will be updated from device
        self._on_volume_change = None  # Callback for volume changes
        self._updating_slider = False  # Prevent feedback loops
        self._is_muted: bool = False  # Track mute state for UI toggle

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

        # Volume slider row (spans all 3 columns)
        self._add_volume_slider(row=4)

        # Media - Row 5: Play/Pause
        self._add_key_button("Play/Pause", "KEYCODE_MEDIA_PLAY_PAUSE", 1, 5, icon_name=["media-playback-start-symbolic", "media-playback-pause-symbolic"])
        
        # Media - Row 6: Prev, Stop (placeholder), Next
        self._add_key_button("Prev", "KEYCODE_MEDIA_PREVIOUS", 0, 6, icon_name="media-skip-backward-symbolic")
        self._add_key_button("Subtitles", "KEYCODE_CAPTIONS", 1, 6, icon_name="media-view-subtitles-symbolic")
        self._add_key_button("Next", "KEYCODE_MEDIA_NEXT", 2, 6, icon_name="media-skip-forward-symbolic")
        
        # System - Row 7: Apps, Search, Assistant
        self._add_key_button("Apps", "KEYCODE_ALL_APPS", 0, 7, icon_name="view-app-grid-symbolic")
        self._add_search_button(1, 7, icon_name="system-search-symbolic")
        self._add_key_button("Assistant", "KEYCODE_ASSIST", 2, 7, icon_name="audio-input-microphone-symbolic")
        
        # Row 8: Input (centered)
        self._add_key_button("Input", "KEYCODE_TV_INPUT", 1, 8, icon_name="video-display-symbolic")

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

    def set_handlers(self, *, on_keyevent=None, on_text=None, on_volume_change=None) -> None:
        self._on_keyevent = on_keyevent
        self._on_text = on_text
        self._on_volume_change = on_volume_change

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
        flash_button(btn)

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
                    image = create_icon(name)
                    icon_box.append(image)
                box.append(icon_box)
            else:
                image = create_icon(icon_name)
                box.append(image)
        else:
            main_label = Gtk.Label(label=label)
            # Make text label bold if no icon
            main_label.set_markup(f"<b>{label}</b>")
            box.append(main_label)
        
        # Shortcut label (bold, same as Enter button)
        shortcut_label = Gtk.Label()
        shortcut_label.add_css_class("caption")
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
            image = create_icon(icon_name)
            box.append(image)
        else:
            main_label = Gtk.Label(label="Find (YouTube)")
            box.append(main_label)
        
        # Shortcut label (bold, same as Enter button)
        shortcut_label = Gtk.Label()
        shortcut_label.add_css_class("caption")
        shortcut_label.set_visible(False)  # Will be shown when shortcuts are loaded
        box.append(shortcut_label)
        
        # Set box as button child
        btn.set_child(box)
        
        # Attach to grid, single column width
        self._grid.attach(btn, col, row, 1, 1)
        
        # Store references
        self._search_button = btn
        self._search_shortcut_label = shortcut_label

    def _add_volume_slider(self, row: int) -> None:
        """Add volume slider with mute button to the grid."""
        # Create container box for the whole volume row
        volume_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        volume_box.add_css_class("volume-slider-box")
        volume_box.set_hexpand(True)
        volume_box.set_vexpand(True)
        volume_box.set_valign(Gtk.Align.CENTER)
        
        # Mute button
        mute_btn = Gtk.Button()
        mute_btn.add_css_class("volume-mute-button")
        mute_btn.set_tooltip_text("Mute")
        mute_btn.connect("clicked", self._on_mute_clicked)
        
        mute_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        mute_icon.set_pixel_size(24)
        mute_btn.set_child(mute_icon)
        volume_box.append(mute_btn)
        self._mute_button = mute_btn
        self._keycode_buttons["KEYCODE_VOLUME_MUTE"] = mute_btn
        
        # Volume slider
        adjustment = Gtk.Adjustment(value=0, lower=0, upper=15, step_increment=1, page_increment=1)
        slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
        slider.set_hexpand(True)
        slider.set_draw_value(False)
        slider.set_tooltip_text("Volume")
        slider.connect("value-changed", self._on_slider_changed)
        volume_box.append(slider)
        self._volume_slider = slider
        
        # Attach to grid spanning all 3 columns
        self._grid.attach(volume_box, 0, row, 3, 1)

    def _on_slider_changed(self, slider: Gtk.Scale) -> None:
        """Called when slider value changes."""
        if self._updating_slider:
            return
        
        new_value = int(slider.get_value())
        
        # Unmute when volume is adjusted
        if self._is_muted:
            self._is_muted = False
            self._update_mute_button_icon()
        
        # Notify callback
        if self._on_volume_change:
            self._on_volume_change(new_value)

    def update_volume(self, current: int, max_vol: int, is_muted: bool = False) -> None:
        """Update volume slider from device state.
        
        Args:
            current: Current volume level (0 to max_vol).
            max_vol: Maximum volume level.
            is_muted: Whether the audio is muted.
        """
        self._volume_max = max_vol
        self._is_muted = is_muted
        
        if self._volume_slider:
            self._updating_slider = True
            adjustment = self._volume_slider.get_adjustment()
            adjustment.set_upper(max_vol)
            adjustment.set_value(current)
            self._updating_slider = False
        
        # Update mute button icon based on muted state
        self._update_mute_button_icon()

    def _update_mute_button_icon(self) -> None:
        """Update the mute button icon based on current muted state."""
        if self._mute_button:
            child = self._mute_button.get_child()
            if isinstance(child, Gtk.Image):
                if self._is_muted:
                    child.set_from_icon_name("audio-volume-muted-symbolic")
                    self._mute_button.add_css_class("destructive-action")
                else:
                    child.set_from_icon_name("audio-volume-high-symbolic")
                    self._mute_button.remove_css_class("destructive-action")

    def _on_mute_clicked(self, *_args) -> None:
        """Handle mute button click - toggle mute state and send keyevent."""
        # Toggle mute state in UI
        self._is_muted = not self._is_muted
        self._update_mute_button_icon()
        
        # Send the keyevent to device
        if self._on_keyevent:
            self._on_keyevent("KEYCODE_VOLUME_MUTE")
