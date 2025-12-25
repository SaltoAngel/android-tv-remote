# TV Remote

A GTK-based remote control for Android TV devices, powered by [scrcpy](https://github.com/Genymobile/scrcpy) and ADB. Features low-latency input, keyboard shortcuts, and an intuitive interface.

![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg) ![Platform](https://img.shields.io/badge/platform-Linux-green.svg) ![GTK](https://img.shields.io/badge/GTK-4.0-orange.svg)

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

| Key | Action | Key | Action |
| --- | --- | --- | --- |
| **Arrow Keys / WASD** | Navigate | **H** | Home |
| **Enter / E** | Select | **M** | Mute |
| **Esc / Q** | Back | **T** | Switch Input |
| **Ctrl+Tab** | App Switcher | **Ctrl+A** | App Launcher |

## Installation (Flatpak)

```bash
# Build and install
flatpak-builder --user --install --force-clean build-dir flatpak/io.github.erenseymen.android-tv-remote.yml

# Run
flatpak run io.github.erenseymen.android-tv-remote
```

## Setup

1. Enable **Developer options** and **USB/Wireless debugging** onto your TV.
2. Ensure ADB over network is enabled on **port 5555**.
3. Accept the authorization prompt on your TV during first connection.

## Tested Devices

- [Xiaomi TV Box S (2nd Gen)](https://www.epey.com/medya-oynatici/xiaomi-tv-box-s-2nd-gen.html)
- [Philips 50PUS7000](https://www.epey.com/televizyon/philips-50pus7000.html)

## License

Licensed under **GPL v3.0**. See [LICENSE](LICENSE).
Third-party licenses: [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
