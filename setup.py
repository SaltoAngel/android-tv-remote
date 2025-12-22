"""Setup script for android-tv-remote."""
import os
import subprocess
from setuptools import setup
from setuptools.command.install import install

class PostInstallCommand(install):
    """Post-installation: compile GSettings schemas."""
    def run(self):
        install.run(self)
        # Compile GSettings schemas
        schema_dir = os.path.join(self.install_data, 'share/glib-2.0/schemas')
        if os.path.isdir(schema_dir):
            try:
                subprocess.run(['glib-compile-schemas', schema_dir], check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass  # glib-compile-schemas not available or failed

setup(
    data_files=[
        ("share/applications", ["data/io.github.erenseymen.android-tv-remote.desktop"]),
        ("share/metainfo", ["data/io.github.erenseymen.android-tv-remote.metainfo.xml"]),
        ("share/icons/hicolor/scalable/apps", [
            "data/icons/hicolor/scalable/apps/io.github.erenseymen.android-tv-remote.svg"
        ]),
        ("share/glib-2.0/schemas", ["data/io.github.erenseymen.android-tv-remote.gschema.xml"]),
        ("share/io.github.erenseymen.android-tv-remote/icons/material", [
            "data/icons/material/fiber_manual_record-symbolic.svg",
            "data/icons/material/keyboard_arrow_down-symbolic.svg",
            "data/icons/material/keyboard_arrow_left-symbolic.svg",
            "data/icons/material/keyboard_arrow_right-symbolic.svg",
            "data/icons/material/keyboard_arrow_up-symbolic.svg",
        ]),
    ],
    cmdclass={
        'install': PostInstallCommand,
    },
)
