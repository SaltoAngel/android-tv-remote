## Android TV Remote for Linux

GNOME (Libadwaita) app to scan LAN for Android TVs, connect via ADB TCP (port 5555), and control with an on-screen remote.

### Features
- **Scan**: Auto-discovers private IPv4 /24 networks and scans for hosts with TCP 5555 open
- **Connect**: Pure-Python ADB client with on-device authorization
- **Auto-connect**: Remembers and connects to last successful IP on startup
- **Remote UI**: D-pad, Home/Back/Menu, volume, power, play/pause, apps list, search, text input
- **Keyboard Shortcuts**: Control TV with keyboard (see table below)
- **Low-Latency Input**: Uses scrcpy-server (~35-70ms) for high-performance input. No FFmpeg or scrcpy binary required on host.

### Keyboard Shortcuts
| Key | Action |
| --- | --- |
| Arrows | Navigate |
| Enter | Select/OK |
| Backspace/Esc | Back |
| Home | Home |
| Space | Play/Pause |
| M | Menu |
| P | Power |
| A | All Apps |
| S | Search (YouTube) |
| +/. | Volume Up |
| -, | Volume Down |

### Setup
1. Enable **Developer options** and **USB/Wireless debugging** on TV
2. Ensure ADB over network on **port 5555** (some TVs need `adb tcpip 5555` once via USB)
3. Accept authorization prompt on first connect

### Tested Devices
- **Xiaomi TV Box S (2nd Gen)** - [Product page](https://www.epey.com/medya-oynatici/xiaomi-tv-box-s-2nd-gen.html)

### Development
**Flatpak build:**
```bash
flatpak-builder --user --install --force-clean build-dir flatpak/io.github.AndroidTvRemote.yml
flatpak run io.github.AndroidTvRemote
```

### Dependencies
- PyGObject (GTK4/Libadwaita), adb-shell, scrcpy-server (bundled)

### License
This project is licensed under the **GNU General Public License v3.0**. See the [LICENSE](LICENSE) file for details. Third-party licenses are listed in [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
