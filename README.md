# TV Remote

A GTK-based remote control for Android TV devices, powered by [scrcpy](https://github.com/Genymobile/scrcpy) and ADB. Features low-latency input, keyboard shortcuts, and an intuitive interface.

![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg) ![Platform](https://img.shields.io/badge/platform-Linux-green.svg) ![GTK](https://img.shields.io/badge/GTK-4.0-orange.svg)

<br>

<div align="center">
  <a href="https://flathub.org/apps/io.github.erenseymen.android-tv-remote">
    <img src="https://dl.flathub.org/assets/badges/flathub-badge-en.png" width="300" alt="Download on Flathub">
  </a>
</div>

| Light Mode | Dark Mode |
| :---: | :---: |
| ![Light Mode](screenshots/light.png) | ![Dark Mode](screenshots/dark.png) |

[▶️ Watch Usage Demo](screenshots/usage.mp4)

## Features

- **Auto-Connect**: Scans network for Android TVs (port 5555) and connects automatically.
- **Full Control**: D-pad, Home/Back/Menu, volume, power, and media controls.
- **App Management**: Launch installed apps and switch between recent ones (Ctrl+Tab).
- **Performance**: Low-latency input (~35-70ms) via scrcpy-server.
- **Integration**: MPRIS media controls and local keyboard input support.

## Keyboard Shortcuts

*Essential shortcuts listed below. All are configurable in Preferences.*

| Key | Action |
| --- | --- |
| Arrow Keys / W A S D | Navigate (Up/Down/Left/Right) |
| Enter / E | OK / Select |
| Esc / Q | Back |
| H | Home |
| I | Menu |
| R | Apps |
| G | Google Assistant |
| Space | Play/Pause |
| Z | Previous |
| X | Next |
| M | Mute |
| + or . | Volume Up |
| - or , | Volume Down |
| Delete | Power |
| C | Captions/Subtitles |
| T | TV Input (switch source) |
| F | Search (YouTube) |
| K | Focus Keyboard |
| Ctrl+Tab | App Switcher (switch between recent apps) |
| Ctrl+A | App Launcher (view all installed apps) |

## Installation

```bash
flatpak install flathub io.github.erenseymen.android-tv-remote
flatpak run io.github.erenseymen.android-tv-remote
```

## Setup

1. Enable **Developer options** and **USB/Wireless debugging** onto your TV.
2. Ensure ADB over network is enabled on **port 5555**.
3. Accept the authorization prompt on your TV during first connection.

## Tested Devices

- [Xiaomi TV Box S (2nd Gen)](https://www.epey.com/medya-oynatici/xiaomi-tv-box-s-2nd-gen.html)
- [Philips 50PUS7000](https://www.epey.com/televizyon/philips-50pus7000.html)

## Development

```bash
# Build and install locally
flatpak-builder --user --install --force-clean build-dir flatpak/io.github.erenseymen.android-tv-remote.yml
```

## Project Structure

```
android-tv-remote/
├── src/gnome_adb_tv_remote/
│   ├── core/               # Core functionality
│   │   ├── adb_client.py      # ADB TCP client
│   │   ├── keystore.py        # RSA key generation
│   │   ├── network_info.py    # Network interface discovery
│   │   ├── scanner.py         # Subnet scanning
│   │   ├── scrcpy_controller.py  # Low-latency input via scrcpy-server
│   │   ├── mpris_service.py   # MPRIS D-Bus integration for desktop media controls
│   │   └── icon_cache.py      # Caching mechanism for retrieved app icons
│   ├── ui/                 # User interface
│   │   ├── main_window.py     # Main application window
│   │   ├── device_dialog.py   # Device discovery dialog
│   │   ├── remote_panel.py    # Remote control widget
│   │   ├── preferences_dialog.py  # Keyboard shortcuts configuration
│   │   ├── app_launcher_dialog.py # Installed apps browser
│   │   ├── app_switcher_dialog.py # Recent apps switcher
│   │   ├── info_dialog.py     # About/Information dialog
│   │   ├── icon_loader.py     # Asynchronous icon loading helper
│   │   └── ui_utils.py        # Shared UI utility functions
│   ├── app.py              # Application entry point
│   └── __main__.py         # Module entry point
├── data/                   # Desktop and schema files
├── flatpak/                # Flatpak build manifest
└── pyproject.toml          # Python package configuration
```


## Technical Overview

The application utilizes **[PyGObject](https://gitlab.gnome.org/GNOME/pygobject)** (GTK4/Libadwaita) to deliver a modern, native Linux user interface. Core communication with Android TV devices is handled by the **[adb-shell](https://github.com/JeffLIrion/adb_shell)** library, providing a pure Python implementation of the ADB protocol, while **[rsa](https://github.com/sybrenstuvel/python-rsa)** and **[pyasn1](https://github.com/pyasn1/pyasn1)** ensure secure key generation and authentication. Device discovery is managed via **[psutil](https://github.com/giampaolo/psutil)**, which enumerates network interfaces to locate available devices. For high-performance, low-latency input injection (~35-70ms), the app integrates **[scrcpy-server](https://github.com/Genymobile/scrcpy)**, orchestrated by **[android-tools](https://developer.android.com/studio/releases/platform-tools)** (specifically the adb binary) for efficient port forwarding and process management.

## License

Licensed under **GPL v3.0**. See [LICENSE](LICENSE).
Third-party licenses: [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
