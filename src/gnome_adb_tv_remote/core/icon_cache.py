"""
App Icon Cache.

Caches app icons fetched from Android devices to avoid repeated downloads.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adb_client import AdbTcpClient

logger = logging.getLogger(__name__)


def get_cache_dir() -> Path:
    """Get the icon cache directory."""
    # Use XDG_CACHE_HOME or fallback to ~/.cache
    cache_home = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    cache_dir = Path(cache_home) / "tv-remote" / "icons"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_icon_cache_path(package_name: str, device_ip: str) -> Path:
    """Get the cache file path for an app icon.
    
    Args:
        package_name: The app's package name.
        device_ip: The device IP (to separate icons from different devices).
    
    Returns:
        Path to the cached icon file.
    """
    # Create a hash to avoid filesystem issues with package names
    key = f"{device_ip}:{package_name}"
    filename = hashlib.md5(key.encode()).hexdigest()[:16] + ".png"
    return get_cache_dir() / filename


def get_cached_icon(package_name: str, device_ip: str) -> str | None:
    """Get cached icon path if it exists.
    
    Args:
        package_name: The app's package name.
        device_ip: The device IP.
    
    Returns:
        Path to cached icon file, or None if not cached.
    """
    cache_path = get_icon_cache_path(package_name, device_ip)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return str(cache_path)
    return None


def cache_icon(package_name: str, device_ip: str, icon_data: bytes) -> str | None:
    """Save icon data to cache.
    
    Args:
        package_name: The app's package name.
        device_ip: The device IP.
        icon_data: PNG icon data.
    
    Returns:
        Path to cached icon file, or None if caching failed.
    """
    try:
        cache_path = get_icon_cache_path(package_name, device_ip)
        cache_path.write_bytes(icon_data)
        return str(cache_path)
    except Exception as e:
        logger.error(f"Failed to cache icon for {package_name}: {e}")
        return None


def fetch_and_cache_icon(
    adb_client: "AdbTcpClient",
    package_name: str,
) -> str | None:
    """Fetch icon from device and cache it.
    
    Args:
        adb_client: The ADB client instance.
        package_name: The app's package name.
    
    Returns:
        Path to cached icon file, or None if fetch failed.
    """
    device_ip = adb_client.host
    
    # Check cache first
    cached = get_cached_icon(package_name, device_ip)
    if cached:
        return cached
    
    # Fetch from device
    try:
        icon_data = adb_client.get_app_icon(package_name)
        if icon_data:
            return cache_icon(package_name, device_ip, icon_data)
    except Exception as e:
        logger.debug(f"Failed to fetch icon for {package_name}: {e}")
    
    return None

