from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402


class RemotePanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(18)
        self.set_margin_bottom(18)
        self.set_margin_start(18)
        self.set_margin_end(18)

        self._title = Adw.WindowTitle(title="Remote", subtitle="Connect to a device to enable controls")
        self.append(self._title)

        self._grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.append(self._grid)

        self._on_keyevent = None
        self._on_text = None

        # Map keycode -> button for visual feedback
        self._keycode_buttons: dict[str, Gtk.Button] = {}

        # D-pad
        self._add_key_button("Up", "KEYCODE_DPAD_UP", 1, 0, tooltip="Arrow Up")
        self._add_key_button("Left", "KEYCODE_DPAD_LEFT", 0, 1, tooltip="Arrow Left")
        self._add_key_button("OK", "KEYCODE_DPAD_CENTER", 1, 1, suggested=True, tooltip="Enter")
        self._add_key_button("Right", "KEYCODE_DPAD_RIGHT", 2, 1, tooltip="Arrow Right")
        self._add_key_button("Down", "KEYCODE_DPAD_DOWN", 1, 2, tooltip="Arrow Down")

        # System
        self._add_key_button("Back", "KEYCODE_BACK", 0, 3, tooltip="Esc")
        self._add_key_button("Home", "KEYCODE_HOME", 1, 3, tooltip="Home")
        self._add_key_button("Menu", "KEYCODE_MENU", 2, 3, tooltip="Backspace")

        # Volume
        self._add_key_button("Vol-", "KEYCODE_VOLUME_DOWN", 0, 4, tooltip="- or , or Numpad -")
        self._add_key_button("Mute", "KEYCODE_VOLUME_MUTE", 1, 4, tooltip="M")
        self._add_key_button("Vol+", "KEYCODE_VOLUME_UP", 2, 4, tooltip="+ or . or Numpad +")

        # Power / Media
        self._add_key_button("Power", "KEYCODE_POWER", 0, 5, tooltip="P")
        self._add_key_button("Play/Pause", "KEYCODE_MEDIA_PLAY_PAUSE", 1, 5, tooltip="Space")
        self._add_key_button("Apps", "KEYCODE_ALL_APPS", 2, 5, tooltip="A")

        # Keyboard input area - keystrokes are sent directly to Android TV
        self._keyboard_entry = Gtk.Entry(placeholder_text="Press K to focus keyboard")
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

    def update_device_info(self, info: DeviceInfo | None = None, ip: str | None = None) -> None:
        from ..core.adb_client import DeviceInfo
        if info and ip:
            self._title.set_title(f"{info.manufacturer} {info.model}")
            self._title.set_subtitle(f"Connected to {ip} (Android {info.version})")
        else:
            self._title.set_title("Remote")
            self._title.set_subtitle("Connect to a device to enable controls")

    def _on_keyboard_focus_enter(self, *_args) -> None:
        """Called when keyboard input area gains focus."""
        self._keyboard_focused = True
        self._keyboard_entry.set_placeholder_text("Type here… (Esc to exit)")

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
            # Don't remove if it's the OK button (which always has suggested-action)
            if keycode != "KEYCODE_DPAD_CENTER":
                btn.remove_css_class("suggested-action")
            return False  # Don't repeat

        GLib.timeout_add(150, remove_flash)

    def _add_key_button(self, label: str, keycode: str, col: int, row: int, suggested: bool = False, tooltip: str | None = None) -> None:
        btn = Gtk.Button(label=label)
        if suggested:
            btn.add_css_class("suggested-action")
        if tooltip:
            btn.set_tooltip_text(tooltip)
        btn.connect("clicked", lambda *_: self._on_keyevent and self._on_keyevent(keycode))
        btn.set_hexpand(True)
        btn.set_vexpand(True)
        self._grid.attach(btn, col, row, 1, 1)

        # Register button for visual feedback
        self._keycode_buttons[keycode] = btn


