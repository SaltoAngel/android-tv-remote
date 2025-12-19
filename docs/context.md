# AI Context

## Project Architecture
- GNOME/GTK 4 application for controlling Android TV via ADB.
- Uses `libadwaita` for modern GNOME UI components.
- ADB communication handled by a custom `AdbTcpClient` (using `adb_shell`).
- Multi-threaded scanning and connection handling to keep the UI responsive.
- [2025-12-19] UI uses a single-pane layout with a "Devices" button in the header bar. Device selection and scanning are handled in a modal `DeviceDialog`.

## Key Dependencies
- `PyGObject`: GTK 4 and Libadwaita bindings.
- `adb_shell`: For ADB protocol implementation.
- `psutil`: For network interface information.
- `scrcpy`: For low-latency input injection (optional, falls back to ADB shell if unavailable).

## Conventions
- UI code is in `src/gnome_adb_tv_remote/ui/`.
- Core logic and ADB client are in `src/gnome_adb_tv_remote/core/`.
- GTK 4 practices are strictly followed (e.g., no `foreach` on containers, use `append`/`remove`/`get_first_child`).
- Application preferences are stored using GSettings (Gio.Settings) with schema defined in `data/io.github.erens.GnomeAndroidTvRemote.gschema.xml`.
- [2025-12-19] `MainWindow` handles connection state and remote control logic. It persists a single `DeviceDialog` instance to preserve scan results and UI state.
- [2025-12-19] `DeviceDialog` handles device discovery and IP input. It hides instead of destroying itself when closed to maintain state. Discovered devices are persisted across app restarts using JSON-encoded strings in GSettings (`discovered-devices` key).
- [2025-12-19] `RemotePanel` provides the user interface for sending key events and text.

## Features
- [2025-12-19] Last connected IP address is remembered using GSettings and automatically connected to when the app opens. The IP is saved to `last-connected-ip` key in the GSettings schema when a connection succeeds. Auto-connection happens asynchronously after UI initialization using `GLib.idle_add`.
- [2025-12-19] Connected device info (manufacturer, model, and Android version) is retrieved via `getprop` and displayed in the `RemotePanel` title/subtitle area upon successful connection.
- [2025-12-19] Keyboard shortcuts implemented globally in `MainWindow` using `Gtk.EventControllerKey`. Navigation, media controls, and system keys are mapped to ADB keycodes. Shortcuts are automatically disabled when a text entry is focused.
- [2025-12-19] Low-latency input injection via scrcpy. When scrcpy is available, it's launched in headless mode (`--no-video --no-audio`) to reduce key event latency from ~200-500ms (ADB shell `input keyevent`) to ~35-70ms. Falls back to ADB shell commands gracefully if scrcpy is not installed. Implementation in `ScrcpyController` class in `src/gnome_adb_tv_remote/core/scrcpy_controller.py`.
- [2025-12-20] Text input field sends keystrokes directly to Android TV as they're typed. Each printable character is sent immediately via the `on_text` handler. Special keys like Enter (KEYCODE_DPAD_CENTER), Backspace (KEYCODE_DEL), and Tab (KEYCODE_TAB) are mapped to corresponding Android keycodes. Pressing Escape returns focus to the OK button in the D-pad grid.

## Known Issues
- [2025-12-19] Fixed Apps button functionality. Changed from `KEYCODE_APP_SWITCH` (Recents) to `KEYCODE_ALL_APPS` (App Drawer) as it is more commonly expected for an "Apps" button on Android TV remotes.
- [2025-12-19] Fixed `AttributeError: 'ListBox' object has no attribute 'foreach'`. GTK 4 removed `Gtk.Container.foreach`.
- [2025-12-19] Fixed `ModuleNotFoundError: No module named 'pyasn1'`. When using `adb-shell` with RSA authentication in Flatpak, transitive dependencies like `rsa` and `pyasn1` must be explicitly listed in the manifest when building with `--no-deps`.
- [2025-12-19] Fixed `ModuleNotFoundError: No module named 'cryptography'`. The `adb_shell.auth.keygen` module requires `cryptography` for key generation. Instead of adding this complex native dependency, implemented custom key generation in `keystore.py` using only the already-available `rsa` and `pyasn1` packages. The custom implementation generates PKCS#8 PEM private keys and Android-format public keys.
- [2025-12-19] Fixed Mute button functionality. Changed from `KEYCODE_MUTE` (microphone mute) to `KEYCODE_VOLUME_MUTE` (system volume mute), which is the standard for TV remotes.

