"""Build the standalone RavenswatchOverlay.exe (PyInstaller --onefile).

Usage (from the project root):
    .\\.venv\\Scripts\\Activate.ps1
    pip install -r requirements.txt -r requirements-dev.txt
    python build.py              -> dist/RavenswatchOverlay.exe
    python build.py --debug      -> also builds dist/RavenswatchOverlay-debug.exe
                                    (console window, no UAC prompt; for testing)

The exe bundles Python, tkinter, Pillow and the icons/ directory — end users
need no Python install. It carries a UAC manifest (requireAdministrator)
because reading game memory needs admin rights on most setups.

Double-click the exe to launch the overlay. `RavenswatchOverlay.exe serve`
runs the OBS browser-source server instead (see ravenswatch/server.py).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICO_SOURCE = ROOT / "icons" / "UI_Melody_Icon_Godfairy.png"
ICO_PATH = ROOT / "build" / "app_icon.ico"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def make_icon():
    from PIL import Image
    ICO_PATH.parent.mkdir(exist_ok=True)
    img = Image.open(ICO_SOURCE).convert("RGBA")
    img.save(ICO_PATH, sizes=ICO_SIZES)
    print(f"Icon: {ICO_PATH}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--debug", action="store_true",
                        help="Also build a console/no-UAC debug exe")
    args = parser.parse_args()

    make_icon()

    env = os.environ.copy()
    if args.debug:
        env["RAVENSWATCH_DEBUG_EXE"] = "1"

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "RavenswatchOverlay.spec"],
        check=True, cwd=ROOT, env=env,
    )

    for name in ["RavenswatchOverlay.exe", "RavenswatchOverlay-debug.exe"]:
        exe = ROOT / "dist" / name
        if exe.exists():
            print(f"Built: {exe} ({exe.stat().st_size / 1_000_000:.1f} MB)")


if __name__ == "__main__":
    main()
