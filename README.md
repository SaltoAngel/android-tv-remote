## Android TV Remote for GNOME (Flatpak)

GNOME (Libadwaita) desktop app to **scan your LAN for Android TVs**, connect over **ADB TCP (port 5555)**, and control them with an on-screen remote.

### Features (current)
- **Scan**: discovers private IPv4 /24 networks from your active interfaces and scans for hosts with TCP **5555** open.
- **Connect**: pure-Python ADB client (no external `adb` binary) with on-device authorization.
- **Auto-connect**: automatically remembers and connects to the last successfully connected IP address when the app opens.
- **Remote UI**: D-pad, Home/Back/Menu, volume, power, play/pause, app switch, and text input.

### Android TV setup
1. Enable **Developer options** on the TV.
2. Enable **USB debugging** (or **ADB debugging** / **Wireless debugging**, depending on vendor/Android version).
3. Ensure ADB over network is available on **port 5555**.
   - Some TVs expose this directly.
   - Others require running `adb tcpip 5555` once from a USB-connected ADB session.
4. On first connect, **accept the authorization prompt** on the TV (“Allow USB debugging?”).

### Run locally (dev)
This repo contains a GTK4/Libadwaita Python app under `src/gnome_adb_tv_remote/`.

If your system Python has PyGObject (GTK4 + Libadwaita) available:

```bash
python3 -m gnome_adb_tv_remote
```

### Flatpak
The Flatpak manifest is:
- `flatpak/io.github.erens.GnomeAndroidTvRemote.yml`

Build/test locally (example):

```bash
flatpak-builder --user --install --force-clean build-dir flatpak/io.github.erens.GnomeAndroidTvRemote.yml
flatpak run io.github.erens.GnomeAndroidTvRemote
```

