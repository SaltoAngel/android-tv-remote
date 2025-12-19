from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402


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

        # D-pad
        self._add_key_button("Up", "KEYCODE_DPAD_UP", 1, 0, tooltip="Arrow Up")
        self._add_key_button("Left", "KEYCODE_DPAD_LEFT", 0, 1, tooltip="Arrow Left")
        self._add_key_button("OK", "KEYCODE_DPAD_CENTER", 1, 1, suggested=True, tooltip="Enter")
        self._add_key_button("Right", "KEYCODE_DPAD_RIGHT", 2, 1, tooltip="Arrow Right")
        self._add_key_button("Down", "KEYCODE_DPAD_DOWN", 1, 2, tooltip="Arrow Down")

        # System
        self._add_key_button("Back", "KEYCODE_BACK", 0, 3, tooltip="Backspace / Esc")
        self._add_key_button("Home", "KEYCODE_HOME", 1, 3, tooltip="Home")
        self._add_key_button("Menu", "KEYCODE_MENU", 2, 3, tooltip="M")

        # Volume
        self._add_key_button("Vol-", "KEYCODE_VOLUME_DOWN", 0, 4, tooltip="- or ,")
        self._add_key_button("Mute", "KEYCODE_VOLUME_MUTE", 1, 4)
        self._add_key_button("Vol+", "KEYCODE_VOLUME_UP", 2, 4, tooltip="+ or .")

        # Power / Media
        self._add_key_button("Power", "KEYCODE_POWER", 0, 5, tooltip="P")
        self._add_key_button("Play/Pause", "KEYCODE_MEDIA_PLAY_PAUSE", 1, 5, tooltip="Space")
        self._add_key_button("Apps", "KEYCODE_ALL_APPS", 2, 5, tooltip="A")

        text_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._text_entry = Gtk.Entry(placeholder_text="Type text to send…")
        self._text_entry.connect("activate", lambda *_: self._send_text())

        send_btn = Gtk.Button(label="Send")
        send_btn.add_css_class("suggested-action")
        send_btn.connect("clicked", lambda *_: self._send_text())
        text_row.append(self._text_entry)
        text_row.append(send_btn)
        self.append(text_row)

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

    def _send_text(self) -> None:
        text = self._text_entry.get_text()
        if not text.strip():
            return
        self._text_entry.set_text("")
        if self._on_text:
            self._on_text(text)

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


