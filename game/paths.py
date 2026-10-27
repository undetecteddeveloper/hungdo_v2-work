"""Filesystem locations: bundled resources and per-user data."""
import os
import sys

from . import config

# the repo root (the directory that holds main.py), independent of the cwd
_SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def base_dir() -> str:
    """Root that bundled resources are resolved against."""
    # PyInstaller unpacks data into sys._MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return meipass
    return _SOURCE_ROOT


def resource_path(rel: str) -> str:
    """Absolute path of a bundled resource given a '/'-separated relative path."""
    return os.path.join(base_dir(), *rel.replace("\\", "/").split("/"))


def user_data_dir() -> str:
    """Writable per-user directory (settings, saves, logs); created on demand.

    The env var HUNGDO_DATA_DIR overrides the location (used by tests so they
    never touch the real save files).
    """
    override = os.environ.get("HUNGDO_DATA_DIR")
    if override:
        candidates = [override]
    else:
        candidates = []
        appdata = os.environ.get("APPDATA")
        if sys.platform.startswith("win") and appdata:
            candidates.append(os.path.join(appdata, config.DATA_DIR_NAME))
        candidates.append(os.path.join(os.path.expanduser("~"), ".hungdo"))

    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            continue
    # Last resort: somewhere that surely exists
    return os.path.abspath(".")
