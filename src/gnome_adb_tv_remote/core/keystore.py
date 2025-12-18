from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AdbKeyPaths:
    private_key: Path
    public_key: Path


def _config_dir(app_dir_name: str = "gnome-adb-tv-remote") -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / app_dir_name
    return Path.home() / ".config" / app_dir_name


def get_adb_key_paths(app_dir_name: str = "gnome-adb-tv-remote") -> AdbKeyPaths:
    base = _config_dir(app_dir_name) / "adb"
    return AdbKeyPaths(private_key=base / "adbkey", public_key=base / "adbkey.pub")


def ensure_adb_keys_exist(app_dir_name: str = "gnome-adb-tv-remote") -> AdbKeyPaths:
    """Ensure ADB RSA keypair exists and return paths.

    Keys are stored inside the Flatpak sandbox under XDG config.
    """
    paths = get_adb_key_paths(app_dir_name)
    paths.private_key.parent.mkdir(parents=True, exist_ok=True)

    if paths.private_key.exists() and paths.public_key.exists():
        return paths

    # adb-shell provides a small helper that writes <path> and <path>.pub
    from adb_shell.auth.keygen import keygen  # type: ignore

    keygen(str(paths.private_key))
    return paths


