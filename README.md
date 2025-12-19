## Android TV Remote for GNOME

GNOME (Libadwaita) app to scan LAN for Android TVs, connect via ADB TCP (port 5555), and control with an on-screen remote.

### Features
- **Scan**: Auto-discovers private IPv4 /24 networks and scans for hosts with TCP 5555 open
- **Connect**: Pure-Python ADB client with on-device authorization
- **Auto-connect**: Remembers and connects to last successful IP on startup
- **Remote UI**: D-pad, Home/Back/Menu, volume, power, play/pause, apps list, text input
- **Keyboard Shortcuts**: Control TV with keyboard (see table below)
- **Low-Latency Input**: Uses scrcpy (~35-70ms) when available, falls back to ADB shell (~200-500ms)

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
| +/. | Volume Up |
| -, | Volume Down |

### Setup
1. Enable **Developer options** and **USB/Wireless debugging** on TV
2. Ensure ADB over network on **port 5555** (some TVs need `adb tcpip 5555` once via USB)
3. Accept authorization prompt on first connect

### Development
**Local run:**
```bash
python3 -m gnome_adb_tv_remote
```

**Flatpak build:**
```bash
flatpak-builder --user --install --force-clean build-dir flatpak/io.github.erens.GnomeAndroidTvRemote.yml
flatpak run io.github.erens.GnomeAndroidTvRemote
```

### Dependencies
- PyGObject (GTK4/Libadwaita), adb-shell, scrcpy (optional)
