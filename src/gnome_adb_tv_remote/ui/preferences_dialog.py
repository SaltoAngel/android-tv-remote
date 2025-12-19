from __future__ import annotations

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402


# Default keyboard shortcuts mapping: action -> list of Gdk key names
DEFAULT_SHORTCUTS: dict[str, list[str]] = {
    "dpad-up": ["Up"],
    "dpad-down": ["Down"],
    "dpad-left": ["Left"],
    "dpad-right": ["Right"],
    "dpad-center": ["Return", "KP_Enter"],
    "back": ["Escape"],
    "home": ["Home"],
    "menu": ["BackSpace"],
    "volume-up": ["plus", "equal", "KP_Add", "period"],
    "volume-down": ["minus", "KP_Subtract", "comma"],
    "volume-mute": ["m"],
    "power": ["p"],
    "play-pause": ["space"],
    "apps": ["a"],
    "focus-keyboard": ["k"],
}

# Action to ADB keycode mapping
ACTION_TO_KEYCODE: dict[str, str] = {
    "dpad-up": "KEYCODE_DPAD_UP",
    "dpad-down": "KEYCODE_DPAD_DOWN",
    "dpad-left": "KEYCODE_DPAD_LEFT",
    "dpad-right": "KEYCODE_DPAD_RIGHT",
    "dpad-center": "KEYCODE_DPAD_CENTER",
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "menu": "KEYCODE_MENU",
    "volume-up": "KEYCODE_VOLUME_UP",
    "volume-down": "KEYCODE_VOLUME_DOWN",
    "volume-mute": "KEYCODE_VOLUME_MUTE",
    "power": "KEYCODE_POWER",
    "play-pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "apps": "KEYCODE_ALL_APPS",
    "focus-keyboard": None,  # Special action, not an ADB keycode
}

# Human-readable action names
ACTION_LABELS: dict[str, str] = {
    "dpad-up": "Up",
    "dpad-down": "Down",
    "dpad-left": "Left",
    "dpad-right": "Right",
    "dpad-center": "OK / Select",
    "back": "Back",
    "home": "Home",
    "menu": "Menu",
    "volume-up": "Volume Up",
    "volume-down": "Volume Down",
    "volume-mute": "Mute",
    "power": "Power",
    "play-pause": "Play/Pause",
    "apps": "Apps",
    "focus-keyboard": "Focus Keyboard",
}

# Category groupings
ACTION_CATEGORIES: dict[str, list[str]] = {
    "Navigation": ["dpad-up", "dpad-down", "dpad-left", "dpad-right", "dpad-center"],
    "System": ["back", "home", "menu", "apps"],
    "Volume": ["volume-up", "volume-down", "volume-mute"],
    "Media & Power": ["play-pause", "power"],
    "Other": ["focus-keyboard"],
}


def get_key_display_name(key_name: str) -> str:
    """Convert Gdk key name to human-readable display name."""
    display_map = {
        "Up": "↑",
        "Down": "↓",
        "Left": "←",
        "Right": "→",
        "Return": "Enter",
        "KP_Enter": "Numpad Enter",
        "Escape": "Esc",
        "BackSpace": "Backspace",
        "space": "Space",
        "plus": "+",
        "minus": "-",
        "equal": "=",
        "period": ".",
        "comma": ",",
        "KP_Add": "Numpad +",
        "KP_Subtract": "Numpad -",
    }
    return display_map.get(key_name, key_name.upper() if len(key_name) == 1 else key_name)


def gdk_keyval_to_name(keyval: int) -> str | None:
    """Convert Gdk keyval to key name string."""
    name = Gdk.keyval_name(keyval)
    return name


def gdk_name_to_keyval(name: str) -> int | None:
    """Convert key name string to Gdk keyval."""
    keyval = Gdk.keyval_from_name(name)
    return keyval if keyval != Gdk.KEY_VoidSymbol else None


class ShortcutButton(Gtk.Button):
    """A button that captures keyboard input to set a shortcut."""

    def __init__(self, action: str, key_names: list[str], on_change: callable) -> None:
        super().__init__()
        self._action = action
        self._key_names = key_names.copy()
        self._on_change = on_change
        self._listening = False

        self.set_hexpand(True)
        self._update_label()

        self.connect("clicked", self._on_clicked)

        # Key controller for capturing shortcuts
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        # Focus controller to stop listening when focus is lost
        focus_controller = Gtk.EventControllerFocus()
        focus_controller.connect("leave", self._on_focus_leave)
        self.add_controller(focus_controller)

    def _update_label(self) -> None:
        if self._listening:
            self.set_label("Press a key…")
            self.add_css_class("suggested-action")
        else:
            if self._key_names:
                display_names = [get_key_display_name(k) for k in self._key_names]
                self.set_label(", ".join(display_names))
            else:
                self.set_label("Not set")
            self.remove_css_class("suggested-action")

    def _on_clicked(self, *_args) -> None:
        self._listening = True
        self._update_label()

    def _on_focus_leave(self, *_args) -> None:
        self._listening = False
        self._update_label()

    def _on_key_pressed(self, _controller, keyval: int, _keycode: int, state: Gdk.ModifierType) -> bool:
        if not self._listening:
            return False

        # Escape cancels editing
        if keyval == Gdk.KEY_Escape:
            self._listening = False
            self._update_label()
            return True

        # Ignore modifier keys alone
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L,
                      Gdk.KEY_Control_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
                      Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Caps_Lock):
            return True

        key_name = gdk_keyval_to_name(keyval)
        if key_name:
            # Replace shortcuts with the new key
            self._key_names = [key_name]
            self._listening = False
            self._update_label()
            self._on_change(self._action, self._key_names)
            return True

        return False

    def get_key_names(self) -> list[str]:
        return self._key_names.copy()

    def set_key_names(self, key_names: list[str]) -> None:
        self._key_names = key_names.copy()
        self._update_label()


class PreferencesDialog(Adw.Dialog):
    """Preferences dialog for configuring keyboard shortcuts."""

    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__()
        self._parent = parent
        self._settings = Gio.Settings.new("io.github.erens.GnomeAndroidTvRemote")
        self._shortcut_buttons: dict[str, ShortcutButton] = {}
        self._shortcuts = self._load_shortcuts()

        self.set_title("Preferences")
        self.set_content_width(450)
        self.set_content_height(600)

        self._build_ui()

    def _load_shortcuts(self) -> dict[str, list[str]]:
        """Load shortcuts from settings, falling back to defaults."""
        shortcuts = DEFAULT_SHORTCUTS.copy()
        try:
            custom = json.loads(self._settings.get_string("keyboard-shortcuts"))
            if custom:
                for action, keys in custom.items():
                    if action in shortcuts:
                        shortcuts[action] = keys
        except (json.JSONDecodeError, TypeError):
            pass
        return shortcuts

    def _save_shortcuts(self) -> None:
        """Save custom shortcuts to settings."""
        # Only save differences from defaults
        custom = {}
        for action, keys in self._shortcuts.items():
            if keys != DEFAULT_SHORTCUTS.get(action, []):
                custom[action] = keys
        self._settings.set_string("keyboard-shortcuts", json.dumps(custom))

        # Notify parent window to reload shortcuts
        if hasattr(self._parent, "reload_shortcuts"):
            self._parent.reload_shortcuts()

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        # Header bar
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Reset button
        reset_btn = Gtk.Button(label="Reset All")
        reset_btn.add_css_class("destructive-action")
        reset_btn.connect("clicked", self._on_reset_all)
        header.pack_end(reset_btn)

        # Scrolled content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scrolled)

        # Main content box
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        scrolled.set_child(content)

        # Info banner
        info_label = Gtk.Label(
            label="Click a shortcut button and press a key to change it. Press Escape to cancel.",
            wrap=True,
            xalign=0,
        )
        info_label.add_css_class("dim-label")
        content.append(info_label)

        # Create preference groups for each category
        for category, actions in ACTION_CATEGORIES.items():
            group = Adw.PreferencesGroup(title=category)
            content.append(group)

            for action in actions:
                row = Adw.ActionRow(title=ACTION_LABELS.get(action, action))

                # Shortcut button
                btn = ShortcutButton(
                    action,
                    self._shortcuts.get(action, []),
                    self._on_shortcut_changed,
                )
                btn.set_valign(Gtk.Align.CENTER)
                row.add_suffix(btn)
                self._shortcut_buttons[action] = btn

                # Reset button for individual action
                reset_action_btn = Gtk.Button(icon_name="edit-undo-symbolic")
                reset_action_btn.set_valign(Gtk.Align.CENTER)
                reset_action_btn.set_tooltip_text("Reset to default")
                reset_action_btn.add_css_class("flat")
                reset_action_btn.connect("clicked", self._on_reset_action, action)
                row.add_suffix(reset_action_btn)

                group.add(row)

    def _on_shortcut_changed(self, action: str, key_names: list[str]) -> None:
        """Called when a shortcut is changed."""
        self._shortcuts[action] = key_names
        self._save_shortcuts()

    def _on_reset_action(self, _btn: Gtk.Button, action: str) -> None:
        """Reset a single action to its default shortcut."""
        default_keys = DEFAULT_SHORTCUTS.get(action, [])
        self._shortcuts[action] = default_keys.copy()
        self._shortcut_buttons[action].set_key_names(default_keys)
        self._save_shortcuts()

    def _on_reset_all(self, *_args) -> None:
        """Reset all shortcuts to defaults."""
        self._shortcuts = {k: v.copy() for k, v in DEFAULT_SHORTCUTS.items()}
        for action, btn in self._shortcut_buttons.items():
            btn.set_key_names(DEFAULT_SHORTCUTS.get(action, []))
        self._save_shortcuts()


def load_shortcuts_from_settings(settings: Gio.Settings) -> dict[int, str]:
    """Load keyboard shortcuts and return a mapping of Gdk keyval -> ADB keycode.

    This function is used by MainWindow to get the current shortcut configuration.
    """
    shortcuts = DEFAULT_SHORTCUTS.copy()
    try:
        custom = json.loads(settings.get_string("keyboard-shortcuts"))
        if custom:
            for action, keys in custom.items():
                if action in shortcuts:
                    shortcuts[action] = keys
    except (json.JSONDecodeError, TypeError):
        pass

    # Build keyval -> keycode mapping
    key_map: dict[int, str] = {}
    for action, key_names in shortcuts.items():
        keycode = ACTION_TO_KEYCODE.get(action)
        if keycode is None:
            continue  # Skip special actions like focus-keyboard
        for key_name in key_names:
            keyval = gdk_name_to_keyval(key_name)
            if keyval is not None:
                key_map[keyval] = keycode

    return key_map


def get_focus_keyboard_keys(settings: Gio.Settings) -> list[int]:
    """Get the Gdk keyvals for the focus-keyboard action."""
    shortcuts = DEFAULT_SHORTCUTS.copy()
    try:
        custom = json.loads(settings.get_string("keyboard-shortcuts"))
        if custom and "focus-keyboard" in custom:
            shortcuts["focus-keyboard"] = custom["focus-keyboard"]
    except (json.JSONDecodeError, TypeError):
        pass

    keyvals = []
    for key_name in shortcuts.get("focus-keyboard", []):
        keyval = gdk_name_to_keyval(key_name)
        if keyval is not None:
            keyvals.append(keyval)
    return keyvals


def get_action_tooltip(action: str, settings: Gio.Settings) -> str:
    """Get tooltip text showing the current shortcut for an action."""
    shortcuts = DEFAULT_SHORTCUTS.copy()
    try:
        custom = json.loads(settings.get_string("keyboard-shortcuts"))
        if custom and action in custom:
            shortcuts[action] = custom[action]
    except (json.JSONDecodeError, TypeError):
        pass

    key_names = shortcuts.get(action, [])
    if key_names:
        display_names = [get_key_display_name(k) for k in key_names]
        return ", ".join(display_names)
    return ""

