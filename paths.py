"""
Centralized, persistent path resolution for the app.

This is the single source of truth for "where is this app installed on disk".
Every other module (exiftool_manager, preset_manager, main_window, app)
should import BASE_DIR / RESOURCES_DIR from here instead of computing its
own path from __file__.

Why this matters:
When PyInstaller freezes the app into a single .exe, __file__ inside a
bundled module resolves to a path inside sys._MEIPASS -- a TEMPORARY folder
that gets extracted fresh on every launch and deleted afterwards. That's
fine for read-only assets bundled *into* the exe (icons, etc.), but it is
the wrong place to look for anything meant to persist between runs (the
bundled ExifTool binary, saved camera/lens/film-stock presets, settings).
For those, we want the folder the .exe itself lives in, which is stable
across runs.

Ported as-is from the ImageImporter project so both apps agree on layout.
"""

import sys
import os


def get_base_dir() -> str:
    """
    Returns the persistent base directory for the application:
    - When frozen (PyInstaller), this is the folder containing the .exe.
    - When running from source, this is the folder containing this file.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
RESOURCES_DIR = os.path.join(BASE_DIR, "resources")
