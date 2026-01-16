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

- **Smart Connectivity**: Automatically discovers and reconnects to devices even if their IP addresses change, using background network scanning and model verification.
- **Full Control**: D-pad navigation, Home/Back/Menu, volume control with mute, and power functions.
- **Long Press Support**: Hold buttons (both in UI and keyboard) for secondary actions like context menus or power options.
- **Media Controls**: Play/Pause, Previous/Next track, with a premium, real-time "Now Playing" dashboard.
- **TV Input Routing**: Dedicated TV Remote dialog for switching HDMI sources, with smart support for multi-device setups (e.g., controlling TV inputs while connected to a streaming box).
- **Desktop integration**: MPRIS support for controlling playback from GNOME media widgets and notifications.
- **Premium Interface**: Modern GTK4/Libadwaita design featuring dynamic gradients, micro-animations, and a sleek dark mode.
- **Customizable Shortcuts**: All keyboard shortcuts are fully configurable in Preferences.

## Keyboard Shortcuts

*Essential shortcuts listed below. All are configurable in Preferences. Most shortcuts support **Long Press** for secondary actions.*

| Key | Action |
| --- | --- |
| Arrow Keys / W A S D | Navigate (Up/Down/Left/Right) |
| Enter / E | OK/Select |
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
| N | Notifications |

## Installation

```bash
flatpak install flathub io.github.erenseymen.android-tv-remote
flatpak run io.github.erenseymen.android-tv-remote
```

## Setup

1. Enable **Developer options** and **USB/Wireless debugging** on your TV.
2. Ensure ADB over network is enabled on **port 5555**.
3. Accept the authorization prompt on your TV during first connection.

## Tested Devices

- [Xiaomi TV Box S (2nd Gen)](https://www.epey.com/medya-oynatici/xiaomi-tv-box-s-2nd-gen.html)
- [Philips 50PUS7000](https://www.epey.com/televizyon/philips-50pus7000.html)

## Development

```bash
# Build and install locally
flatpak-builder --user --install --force-clean build-dir flatpak/io.github.erenseymen.android-tv-remote.yml

# Run locally
flatpak run io.github.erenseymen.android-tv-remote
```

## Project Structure

```
android-tv-remote/
├── src/gnome_adb_tv_remote/
│   ├── core/                  # Core Logic
│   │   ├── adb_client.py         # Pure-Python ADB client & media parsing
│   │   ├── scanner.py            # High-concurrency network discovery
│   │   ├── scrcpy_controller.py  # Low-latency input injection (~35-70ms)
│   │   ├── mpris_service.py      # D-Bus integration for desktop controls
│   │   └── keystore.py           # Secure RSA key management for ADB
│   ├── ui/                    # GTK4 User Interface
│   │   ├── main_window.py        # Main app logic & shortcut handling
│   │   ├── remote_panel.py       # Remote interface & Now Playing dashboard
│   │   ├── device_dialog.py      # Device discovery & pairing manager
│   │   ├── tv_remote_dialog.py   # HDMI/Input switching interface
│   │   └── preferences_dialog.py # Keyboard shortcut configuration
│   ├── app.py                 # Adw.Application entry point
│   └── __main__.py            # Module runner
├── data/                      # Desktop files, Icons, and GSettings
├── flatpak/                   # Flatpak build manifests
└── pyproject.toml             # Project metadata and dependencies
```

## Technical Overview

The application utilizes **[PyGObject](https://gitlab.gnome.org/GNOME/pygobject)** (GTK4/Libadwaita) to deliver a modern, native Linux user interface. Core communication with Android TV devices is handled by the **[adb-shell](https://github.com/JeffLIrion/adb_shell)** library, providing a pure Python implementation of the ADB protocol, while **[rsa](https://github.com/sybrenstuvel/python-rsa)** and **[pyasn1](https://github.com/pyasn1/pyasn1)** ensure secure key generation and authentication. Device discovery is managed via **[psutil](https://github.com/giampaolo/psutil)**, which enumerates network interfaces to locate available devices. For high-performance, low-latency input injection (~35-70ms), the app integrates **[scrcpy-server](https://github.com/Genymobile/scrcpy)**, orchestrated by **[android-tools](https://developer.android.com/studio/releases/platform-tools)** (specifically the adb binary) for efficient port forwarding and process management.

## License

Licensed under **GPL v3.0**. See [LICENSE](LICENSE).
Third-party licenses: [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
