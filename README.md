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
- **Precision Input**: Ultra-low latency input injection (~35-70ms) powered by scrcpy-server, providing smooth navigation and tactile responsiveness.
- **Long Press Support**: Hold buttons (both in UI and keyboard) for secondary actions:
    - **Power**: Long-press for Power Menu (Restart/Sleep/Shutdown).
    - **OK/Select**: Long-press for Context Menus (options, add to favorites).
    - **Home/Back/Menu/Apps**: Long-press for various app-specific shortcuts.
- **Instant Seeking**: Hold any D-pad direction button (mouse or keyboard) for high-speed "Hold-to-Repeat" navigation.
- **Premium Interface Dashboard**: Modern GTK4/Libadwaita design featuring:
    - **Dynamic Dash**: A real-time "Now Playing" dashboard with glassmorphism effects and gradients.
    - **Media Control**: Play/Pause, Previous/Next track with automatic status synchronization.
- **TV Input Routing**: Dedicated dialog for switching HDMI sources, with smart support for multi-device setups (e.g., controlling TV inputs while connected to a streaming box).
- **Desktop Integration**: Full MPRIS support for controlling playback from GNOME media widgets, lock screen, and notifications.
- **Customizable Shortcuts**: All keyboard shortcuts are fully configurable in Preferences.

## Keyboard Shortcuts

*Essential shortcuts listed below. All are configurable in Preferences. Most shortcuts support **Long Press** for secondary actions.*

| Key | Action |
| --- | --- |
| Arrow Keys / **W A S D** | Navigate (Up/Down/Left/Right) — *Supports Hold-to-Repeat* |
| **Enter** / **E** | OK/Select — *Long Press for Context Menu* |
| **Esc** / **Q** / **Backspace** | Back |
| **H** | Home |
| **I** | Menu |
| **R** | Apps |
| **G** | Google Assistant |
| **Space** | Play/Pause |
| **Z** | Previous |
| **X** | Next |
| **M** | Mute |
| **+** or **.** | Volume Up |
| **-** or **,** | Volume Down |
| **Delete** | Power — *Long Press for Power Menu* |
| **C** | Captions/Subtitles |
| **T** | TV Input (Switch HDMI source) |
| **F** | Search (YouTube) |
| **Tab** | Focus Keyboard (Input text directly) |
| **N** | Notifications |


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
├── src/gnome_adb_tv_remote/     # Main Application Package
│   ├── core/                  # Engine & Domain Logic
│   │   ├── adb_client.py         # Pure-Python ADB client, media & status parsing
│   │   ├── scanner.py            # High-concurrency network discovery engine
│   │   ├── scrcpy_controller.py  # Low-latency scrcpy-server protocol handler
│   │   ├── mpris_service.py      # Linux Media Player (MPRIS) D-Bus integration
│   │   ├── keystore.py           # Secure RSA key management for ADB Auth
│   │   └── network_info.py       # Local network interface & subnet detection
│   ├── ui/                    # Gtk4/Libadwaita Interface
│   │   ├── main_window.py        # Application coordinator & event handling
│   │   ├── remote_panel.py       # Remote controls & Now Playing dashboard
│   │   ├── device_dialog.py      # Device discovery & pairing manager
│   │   ├── tv_remote_dialog.py   # HDMI/Input switching overlay
│   │   ├── input_device_dialog.py # Multi-device routing selector
│   │   ├── preferences_dialog.py # Keyboard shortcut & routing settings
│   │   ├── info_dialog.py        # Help, about and instructions
│   │   └── ui_utils.py           # Reusable UI components & animations
│   ├── app.py                 # Adw.Application lifecycle management
│   └── __main__.py            # CLI entry point
├── data/                      # GSettings schemas, .desktop, Icons
├── flatpak/                   # Flatpak manifests & build configuration
├── pyproject.toml             # Dependency & build metadata
└── screenshots/               # UI presentation assets
```


## Technical Overview

The application utilizes **[PyGObject](https://gitlab.gnome.org/GNOME/pygobject)** (GTK4/Libadwaita) to deliver a modern, native Linux user interface. Core communication with Android TV devices is handled by the **[adb-shell](https://github.com/JeffLIrion/adb_shell)** library, providing a pure Python implementation of the ADB protocol, while **[rsa](https://github.com/sybrenstuvel/python-rsa)** and **[pyasn1](https://github.com/pyasn1/pyasn1)** ensure secure key generation and authentication. Device discovery is managed via **[psutil](https://github.com/giampaolo/psutil)**, which enumerates network interfaces to locate available devices. For high-performance, low-latency input injection (~35-70ms), the app integrates **[scrcpy-server](https://github.com/Genymobile/scrcpy)**, orchestrated by **[android-tools](https://developer.android.com/studio/releases/platform-tools)** (specifically the adb binary) for efficient port forwarding and process management.

## License

Licensed under **GPL v3.0**. See [LICENSE](LICENSE).
Third-party licenses: [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
