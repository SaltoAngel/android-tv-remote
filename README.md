# TV Remote

A GNOME (Libadwaita) application to control Android TV devices over the network via ADB.

![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Linux-green.svg)
![GTK](https://img.shields.io/badge/GTK-4.0-orange.svg)

| Light Mode | Dark Mode |
| :---: | :---: |
| ![Light Mode](screenshots/light.png) | ![Dark Mode](screenshots/dark.png) |

## Usage


[▶️ Watch Usage Demo](screenshots/usage.mp4)

## Features

- **Network Scanning**: Auto-discovers Android TV devices on your local network by scanning for hosts with ADB port (5555) open
- **ADB Connection**: Pure-Python ADB client with RSA key authentication
- **Auto-Connect**: Remembers and connects to the last successful device on startup
- **Remote Control UI**: Full-featured remote with D-pad, Home/Back/Menu, volume controls, power, media buttons, and app launcher
- **Keyboard Shortcuts**: Control your TV with keyboard shortcuts (all configurable)
- **Text Input**: Type text directly to your TV for search and input fields
- **Low-Latency Input**: Uses scrcpy-server technology for fast input response (~35-70ms)

## Keyboard Shortcuts

All shortcuts are configurable through the Preferences dialog.

| Key | Action |
| --- | --- |
| Arrow Keys / W A S D | Navigate (Up/Down/Left/Right) |
| Enter / E | OK / Select |
| Esc / Q | Back |
| H | Home |
| I | Menu |
| Space | Play/Pause |
| M | Mute |
| Delete | Power |
| R | Apps |
| F | Search (YouTube) |
| K | Focus Keyboard |
| + or . | Volume Up |
| - or , | Volume Down |

## Installation

### Flatpak (Recommended)

```bash
# Build and install locally
flatpak-builder --user --install --force-clean build-dir flatpak/io.github.erenseymen.TvRemote.yml

# Run
flatpak run io.github.erenseymen.TvRemote
```

### Requirements

The application runs in a Flatpak sandbox and includes all dependencies. The build requires:
- `flatpak`
- `flatpak-builder`

## Setup

1. Enable **Developer options** on your Android TV
2. Enable **USB debugging** or **Wireless debugging**  
3. Ensure ADB over network is enabled on **port 5555** (some TVs may need `adb tcpip 5555` via USB first)
4. On first connection, accept the "Allow USB debugging?" authorization prompt on the TV

## Tested Devices

- **Xiaomi TV Box S (2nd Gen)** - [Product page](https://www.epey.com/medya-oynatici/xiaomi-tv-box-s-2nd-gen.html)

## Project Structure

```
android-tv-remote/
├── src/gnome_adb_tv_remote/
│   ├── core/               # Core functionality
│   │   ├── adb_client.py      # ADB TCP client
│   │   ├── keystore.py        # RSA key generation
│   │   ├── network_info.py    # Network interface discovery
│   │   ├── scanner.py         # Subnet scanning
│   │   └── scrcpy_controller.py  # Low-latency input via scrcpy-server
│   ├── ui/                 # User interface
│   │   ├── main_window.py     # Main application window
│   │   ├── device_dialog.py   # Device discovery dialog
│   │   ├── remote_panel.py    # Remote control widget
│   │   └── preferences_dialog.py  # Keyboard shortcuts configuration
│   ├── app.py              # Application entry point
│   └── __main__.py         # Module entry point
├── data/                   # Desktop and schema files
├── flatpak/                # Flatpak build manifest
└── pyproject.toml          # Python package configuration
```

## Dependencies

- **PyGObject** (GTK4/Libadwaita) - UI framework
- **adb-shell** - ADB protocol implementation
- **psutil** - Network interface discovery
- **rsa** / **pyasn1** - RSA key generation
- **scrcpy-server** (bundled) - Low-latency input injection

## License

This project is licensed under the **GNU General Public License v3.0**. See the [LICENSE](LICENSE) file for details.

Third-party component licenses are documented in [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
