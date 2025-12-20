# Flathub Publishing Instructions

This document provides step-by-step instructions for publishing TV Remote to Flathub.

## Prerequisites

1. A GitHub account
2. A Flathub account (sign up at https://flathub.org)
3. Your app passing validation checks

## Step 1: Choose a Proper App ID

Flathub requires app IDs to follow reverse DNS notation. You have two options:

### Option A: Use a GitHub-based ID (Recommended if you don't own a domain)

Change the app ID to: `io.github.erenseymen.TvRemote`

You'll need to update these files:
- `flatpak/Android.TV.Remote.yml` → `flatpak/io.github.erenseymen.TvRemote.yml`
- `data/Android.TV.Remote.desktop` → `data/io.github.erenseymen.TvRemote.desktop`
- `data/Android.TV.Remote.gschema.xml` → `data/io.github.erenseymen.TvRemote.gschema.xml`
- `data/Android.TV.Remote.metainfo.xml` → `data/io.github.erenseymen.TvRemote.metainfo.xml`
- `data/icons/hicolor/scalable/apps/Android.TV.Remote.svg` → `data/icons/hicolor/scalable/apps/io.github.erenseymen.TvRemote.svg`
- Update the `APP_ID` constant in `src/gnome_adb_tv_remote/app.py`
- Update references in `build-and-run.sh`

### Option B: Keep Current ID (Only if you own android.tv.remote domain)

Keep the current `Android.TV.Remote` ID only if you can verify ownership of the corresponding domain.

## Step 2: Add Screenshots

Take screenshots of your application and save them in the `screenshots/` directory:

```bash
# Take a screenshot of the main window
gnome-screenshot -w -f screenshots/main-window.png

# Take a screenshot of the device dialog
gnome-screenshot -w -f screenshots/device-dialog.png
```

Requirements:
- PNG format, at least 620px wide
- Show the main interface and key features
- Light and dark variants are appreciated

Then push them to your GitHub repository so the URLs in the metainfo.xml work.

## Step 3: Validate Your Metainfo

Install the appstream validator:

```bash
sudo dnf install appstream  # Fedora
sudo apt install appstream  # Ubuntu/Debian
```

Validate your metainfo file:

```bash
appstreamcli validate data/Android.TV.Remote.metainfo.xml
```

Fix any reported issues before proceeding.

## Step 4: Test Your Flatpak Build

```bash
# Clean build
rm -rf build-dir .flatpak-builder
./build-and-run.sh

# Test the built app
flatpak run Android.TV.Remote
```

## Step 5: Fork the Flathub Repository

1. Go to https://github.com/flathub/flathub
2. Fork the repository to your account

## Step 6: Create Your App Submission

1. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/flathub.git
   cd flathub
   ```

2. Create a new branch for your app:
   ```bash
   git checkout -b new-pr
   ```

3. Create a directory for your app:
   ```bash
   mkdir io.github.erenseymen.TvRemote
   ```

4. Copy your manifest:
   ```bash
   cp /path/to/android-tv-remote/flatpak/Android.TV.Remote.yml io.github.erenseymen.TvRemote/io.github.erenseymen.TvRemote.yml
   ```

5. **Important**: Modify the manifest for Flathub:
   - Change `app-id:` to `io.github.erenseymen.TvRemote`
   - Change the source from `type: dir` to `type: git` pointing to your GitHub repo:
   
   ```yaml
   - name: android-tv-remote
     buildsystem: simple
     build-commands:
       - pip3 install --prefix=/app --no-deps --no-build-isolation .
       - install -D data/io.github.erenseymen.TvRemote.desktop /app/share/applications/io.github.erenseymen.TvRemote.desktop
       - install -D data/io.github.erenseymen.TvRemote.metainfo.xml /app/share/metainfo/io.github.erenseymen.TvRemote.metainfo.xml
       - install -D data/icons/hicolor/scalable/apps/io.github.erenseymen.TvRemote.svg /app/share/icons/hicolor/scalable/apps/io.github.erenseymen.TvRemote.svg
       - install -D data/io.github.erenseymen.TvRemote.gschema.xml /app/share/glib-2.0/schemas/io.github.erenseymen.TvRemote.gschema.xml
       - glib-compile-schemas /app/share/glib-2.0/schemas
     sources:
       - type: git
         url: https://github.com/erenseymen/android-tv-remote.git
         tag: v0.1.0  # Use a release tag
   ```

6. Commit and push:
   ```bash
   git add .
   git commit -m "Add io.github.erenseymen.TvRemote"
   git push origin new-pr
   ```

7. Open a Pull Request on https://github.com/flathub/flathub

## Step 7: Respond to Review

The Flathub team will review your submission. Common feedback includes:

- App ID format issues
- Missing or invalid metainfo fields
- Permission concerns
- Screenshot requirements

Address any feedback promptly to get your app published.

## Step 8: After Acceptance

Once accepted, your app will be automatically built and published to Flathub. Users can then install it with:

```bash
flatpak install flathub io.github.erenseymen.TvRemote
```

## Updating Your App

For future updates:

1. Create a new release/tag on your GitHub repository
2. Update the manifest in your Flathub repository with the new tag
3. The Flathub buildbot will automatically rebuild and publish

## Resources

- [Flathub App Submission](https://github.com/flathub/flathub/wiki/App-Submission)
- [Flatpak Manifest Documentation](https://docs.flatpak.org/en/latest/manifests.html)
- [AppStream Metainfo Guidelines](https://www.freedesktop.org/software/appstream/docs/chap-Metadata.html)
- [Flathub Quality Guidelines](https://docs.flathub.org/docs/for-app-authors/metainfo-guidelines/)
