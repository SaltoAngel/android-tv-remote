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

## Conventions
- UI code is in `src/gnome_adb_tv_remote/ui/`.
- Core logic and ADB client are in `src/gnome_adb_tv_remote/core/`.
- GTK 4 practices are strictly followed (e.g., no `foreach` on containers, use `append`/`remove`/`get_first_child`).
- Application preferences are stored using GSettings (Gio.Settings) with schema defined in `data/io.github.erens.GnomeAndroidTvRemote.gschema.xml`.
- [2025-12-19] `MainWindow` handles connection state and remote control logic.
- [2025-12-19] `DeviceDialog` handles device discovery and IP input.
- [2025-12-19] `RemotePanel` provides the user interface for sending key events and text.

## Features
- [2025-12-19] Last connected IP address is remembered using GSettings and automatically connected to when the app opens. The IP is saved to `last-connected-ip` key in the GSettings schema when a connection succeeds. Auto-connection happens asynchronously after UI initialization using `GLib.idle_add`.
- [2025-12-19] Connected device info (manufacturer, model, and Android version) is retrieved via `getprop` and displayed in the `RemotePanel` title/subtitle area upon successful connection.

## Known Issues
- [2025-12-19] Fixed Apps button functionality. Changed from `KEYCODE_APP_SWITCH` (Recents) to `KEYCODE_ALL_APPS` (App Drawer) as it is more commonly expected for an "Apps" button on Android TV remotes.
- [2025-12-19] Fixed `AttributeError: 'ListBox' object has no attribute 'foreach'`. GTK 4 removed `Gtk.Container.foreach`.
- [2025-12-19] Fixed `ModuleNotFoundError: No module named 'pyasn1'`. When using `adb-shell` with RSA authentication in Flatpak, transitive dependencies like `rsa` and `pyasn1` must be explicitly listed in the manifest when building with `--no-deps`.
- [2025-12-19] Fixed `ModuleNotFoundError: No module named 'cryptography'`. The `adb_shell.auth.keygen` module requires `cryptography` for key generation. Instead of adding this complex native dependency, implemented custom key generation in `keystore.py` using only the already-available `rsa` and `pyasn1` packages. The custom implementation generates PKCS#8 PEM private keys and Android-format public keys.
- [2025-12-19] Fixed Mute button functionality. Changed from `KEYCODE_MUTE` (microphone mute) to `KEYCODE_VOLUME_MUTE` (system volume mute), which is the standard for TV remotes.

