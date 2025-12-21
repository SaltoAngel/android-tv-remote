"""Setup script for android-tv-remote."""
from setuptools import setup

# Read version and other metadata from pyproject.toml
# This file only handles data_files installation

setup(
    data_files=[
        # Desktop file
        ("share/applications", ["data/io.github.erenseymen.TvRemote.desktop"]),
        # Metainfo
        ("share/metainfo", ["data/io.github.erenseymen.TvRemote.metainfo.xml"]),
        # Icon
        ("share/icons/hicolor/scalable/apps", [
            "data/icons/hicolor/scalable/apps/io.github.erenseymen.TvRemote.svg"
        ]),
        # GSchema
        ("share/glib-2.0/schemas", ["data/io.github.erenseymen.TvRemote.gschema.xml"]),
        # Material icons
        ("share/io.github.erenseymen.TvRemote/icons/material", [
            "data/icons/material/fiber_manual_record-symbolic.svg",
            "data/icons/material/keyboard_arrow_down-symbolic.svg",
            "data/icons/material/keyboard_arrow_left-symbolic.svg",
            "data/icons/material/keyboard_arrow_right-symbolic.svg",
            "data/icons/material/keyboard_arrow_up-symbolic.svg",
        ]),
    ],
)

