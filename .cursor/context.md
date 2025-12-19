# AI Context

## Project Architecture
- GNOME/GTK 4 application for controlling Android TV via ADB.
- Uses `libadwaita` for modern GNOME UI components.
- ADB communication handled by a custom `AdbTcpClient` (using `adb_shell`).
- Multi-threaded scanning and connection handling to keep the UI responsive.

## Key Dependencies
- `PyGObject`: GTK 4 and Libadwaita bindings.
- `adb_shell`: For ADB protocol implementation.
- `psutil`: For network interface information.

## Conventions
- UI code is in `src/gnome_adb_tv_remote/ui/`.
- Core logic and ADB client are in `src/gnome_adb_tv_remote/core/`.
- GTK 4 practices are strictly followed (e.g., no `foreach` on containers, use `append`/`remove`/`get_first_child`).

## Known Issues
- [2025-12-19] Fixed `AttributeError: 'ListBox' object has no attribute 'foreach'`. GTK 4 removed `Gtk.Container.foreach`.
- [2025-12-19] Fixed `ModuleNotFoundError: No module named 'pyasn1'`. When using `adb-shell` with RSA authentication in Flatpak, transitive dependencies like `rsa` and `pyasn1` must be explicitly listed in the manifest when building with `--no-deps`.

