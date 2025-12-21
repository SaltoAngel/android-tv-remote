"""
Setup Instructions Dialog.

This module provides the InfoDialog class, which displays instructions
on how to prepare an Android TV for connection and provides a link to
the project's GitHub repository.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402


class InfoDialog(Adw.Window):
    """A modal dialog showing setup instructions for Android TV."""

    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__(
            transient_for=parent,
            modal=True,
            title="How to Setup",
            default_width=450,
            default_height=550,
        )

        self._build_ui()

        self.connect("close-request", self._on_close_request)

        # Add keyboard controller for Escape key
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_close_request(self, *_args) -> bool:
        """Hide the window instead of destroying it."""
        self.hide()
        return True

    def _on_key_pressed(self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, _state: Gdk.ModifierType) -> bool:
        """Handle keyboard shortcuts in the dialog."""
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        # Instructions Section
        instructions_group = Adw.PreferencesGroup(
            title="Android TV Preparation",
            description="Follow these steps on your TV to enable remote control access."
        )
        
        setup_steps = [
            ("1. Enable Developer Options", "Go to Settings > Device Preferences > About. Find 'Build' and click it 7 times until developer mode is enabled."),
            ("2. Enable ADB Debugging", "Go to Settings > Device Preferences > Developer Options. Enable 'USB debugging' or 'Wireless debugging'."),
            ("3. Enable Network Port", "Ensure the TV is listening on port 5555. Some devices may require connecting via USB first and running 'adb tcpip 5555'."),
            ("4. Authorize Connection", "When you try to connect from this app, look at your TV screen and 'Always allow' the connection request.")
        ]

        for step_title, step_desc in setup_steps:
            row = Adw.ActionRow(title=step_title, subtitle=step_desc)
            row.set_subtitle_lines(0)  # Unlimited lines for subtitle
            instructions_group.add(row)
        
        content.append(instructions_group)

        # GitHub Link Section
        link_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        link_box.set_valign(Gtk.Align.END)
        link_box.set_vexpand(True)
        
        github_label = Gtk.Label(
            label="For more information, source code, and updates, visit the project page on GitHub:",
            wrap=True,
            justify=Gtk.Justification.CENTER
        )
        github_label.add_css_class("dim-label")
        link_box.append(github_label)

        github_btn = Gtk.LinkButton(
            uri="https://github.com/erenseymen/android-tv-remote",
            label="github.com/erenseymen/android-tv-remote"
        )
        link_box.append(github_btn)
        
        content.append(link_box)

        # Use a ScrolledWindow to ensure content is accessible on smaller screens
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(content)
        scrolled.set_propagate_natural_height(True)
        toolbar_view.set_content(scrolled)
