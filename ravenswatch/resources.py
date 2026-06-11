"""Locate bundled resources (icons) in both dev and PyInstaller-frozen mode.

In dev mode resources live next to the package (project root / icons).
In a PyInstaller --onefile build they are extracted to sys._MEIPASS.
"""

import sys
from pathlib import Path

from .melody_data import ICON_FILENAMES


def icons_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "icons"
    return Path(__file__).resolve().parent.parent / "icons"


def icon_path(melody_display_name: str) -> Path | None:
    """Path to a melody's icon PNG, or None if unknown/missing."""
    fname = ICON_FILENAMES.get(melody_display_name)
    if not fname:
        return None
    path = icons_dir() / fname
    return path if path.exists() else None
