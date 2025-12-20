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
- `scrcpy-server`: For low-latency input injection (pre-built binary pushed to device).

## Conventions
- UI code is in `src/gnome_adb_tv_remote/ui/`.
- Core logic and ADB client are in `src/gnome_adb_tv_remote/core/`.
- GTK 4 practices are strictly followed (e.g., no `foreach` on containers, use `append`/`remove`/`get_first_child`).
- Application preferences are stored using GSettings (Gio.Settings) with schema defined in `data/io.android.TvRemote.gschema.xml`.
- [2025-12-19] `MainWindow` handles connection state and remote control logic. It persists a single `DeviceDialog` instance to preserve scan results and UI state.
- [2025-12-19] `DeviceDialog` handles device discovery and IP input. It hides instead of destroying itself when closed to maintain state. Discovered devices are persisted across app restarts using JSON-encoded strings in GSettings (`discovered-devices` key).
- [2025-12-19] `RemotePanel` provides the user interface for sending key events and text.

## Features
- [2025-12-19] Last connected IP address is remembered using GSettings and automatically connected to when the app opens. The IP is saved to `last-connected-ip` key in the GSettings schema when a connection succeeds. Auto-connection happens asynchronously after UI initialization using `GLib.idle_add`.
- [2025-12-19] Connected device info (manufacturer, model, and Android version) is retrieved via `getprop` and displayed in the `RemotePanel` title/subtitle area upon successful connection.
- [2025-12-19] Keyboard shortcuts implemented globally in `MainWindow` using `Gtk.EventControllerKey`. Navigation, media controls, and system keys are mapped to ADB keycodes. Shortcuts are automatically disabled when a text entry is focused.
- [2025-12-19] Low-latency input injection via scrcpy-server. Instead of using the full scrcpy desktop client, the app uses a custom Python implementation (`ScrcpyServerController`) that pushes `scrcpy-server` to the device and communicates with it directly. This implementation uses `adb_shell` for authorized operations (push) and the `adb` CLI (via `subprocess.Popen` with `ADB_VENDOR_KEYS`) for starting the server and port forwarding. This ensures the server process remains alive as a child of the application and works seamlessly within the Flatpak sandbox. This reduces key event latency from ~200-500ms (ADB shell `input keyevent`) to ~35-70ms without requiring FFmpeg or the scrcpy C client. Implementation in `ScrcpyServerController` class in `src/gnome_adb_tv_remote/core/scrcpy_controller.py`.
- [2025-12-20] Input injection exclusively uses scrcpy-server. Removed ADB shell fallback mechanism (`input keyevent` and `input text` commands). All key events and text input now require an active scrcpy-server connection. If scrcpy-server is not connected, users receive a toast notification. This ensures consistent low-latency input (~35-70ms) and simplifies the codebase by removing the slower fallback path.
- [2025-12-20] Keyboard input mode: Press K to focus a dedicated keyboard input area. When focused, all keystrokes are sent directly to Android TV (like scrcpy). Uses a focusable Label widget to avoid Entry's special key handling. State tracked via `keyboard_focused` property so MainWindow knows to let RemotePanel handle keys. Escape exits keyboard mode and returns focus to the OK button.
- [2025-12-20] Configurable keyboard shortcuts: All keyboard shortcuts are now configurable through a Preferences dialog. Shortcuts are stored in GSettings (`keyboard-shortcuts` key) as JSON. The `PreferencesDialog` class in `ui/preferences_dialog.py` provides the UI for customizing shortcuts. Default shortcuts are defined in `DEFAULT_SHORTCUTS` dict. Button tooltips in `RemotePanel` dynamically reflect the current shortcut configuration. Numpad button information (e.g. "Numpad Enter") is removed from tooltips for clarity, showing only "Enter" and deduplicating if both regular and Numpad keys are assigned.
- [2025-12-20] Keyboard shortcuts displayed on buttons: Shortcuts are now shown directly on the buttons themselves instead of in tooltips. Each button displays the main label and the keyboard shortcut below it in smaller, dimmed text. This provides better visibility and discoverability of shortcuts. The shortcut labels are updated dynamically when shortcuts are changed in preferences via the `update_tooltips()` method (which now updates button labels rather than tooltips).

## Flatpak Permissions
- [2025-12-20] Removed `--device=all` permission as the app only uses network-based ADB (TCP), not USB. The permission was unnecessarily broad. Required permissions: `--share=network` (ADB-over-TCP), `--socket=wayland`, `--socket=fallback-x11` (GUI), `--device=dri` (GPU rendering).

## Dependencies
- [2025-12-20] Removed FFmpeg, scrcpy (C client), and libusb dependencies. The app only requires the `scrcpy-server` binary, which is a Java-based component that runs on the Android device and doesn't require native libraries on the host. This significantly reduces Flatpak build time and bundle size.

## Known Issues
- [2025-12-19] Fixed Apps button functionality. Changed from `KEYCODE_APP_SWITCH` (Recents) to `KEYCODE_ALL_APPS` (App Drawer) as it is more commonly expected for an "Apps" button on TV remotes.
- [2025-12-19] Fixed `AttributeError: 'ListBox' object has no attribute 'foreach'`. GTK 4 removed `Gtk.Container.foreach`.
- [2025-12-19] Fixed `ModuleNotFoundError: No module named 'pyasn1'`. When using `adb-shell` with RSA authentication in Flatpak, transitive dependencies like `rsa` and `pyasn1` must be explicitly listed in the manifest when building with `--no-deps`.
- [2025-12-19] Fixed `ModuleNotFoundError: No module named 'cryptography'`. The `adb_shell.auth.keygen` module requires `cryptography` for key generation. Instead of adding this complex native dependency, implemented custom key generation in `keystore.py` using only the already-available `rsa` and `pyasn1` packages. The custom implementation generates PKCS#8 PEM private keys and Android-format public keys.
- [2025-12-19] Fixed Mute button functionality. Changed from `KEYCODE_MUTE` (microphone mute) to `KEYCODE_VOLUME_MUTE` (system volume mute), which is the standard for TV remotes.

## Code Quality
- [2025-12-20] Code cleanup: removed orphan `ScrcpyController` class (only `ScrcpyServerController` is used). Fixed missing `DeviceInfo` import in `remote_panel.py`. Fixed type hint `callable` → `Callable` in `preferences_dialog.py`. Refactored duplicate shortcut loading logic into single `_load_shortcuts_dict()` helper function.
