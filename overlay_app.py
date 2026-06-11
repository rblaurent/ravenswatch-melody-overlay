"""PyInstaller entry point for the standalone melody overlay exe.

Double-click: waits for Ravenswatch, shows the run melodies over the HUD,
exits when the game closes. Equivalent to `python -m ravenswatch overlay`.
"""

from ravenswatch.overlay import MelodyOverlay

if __name__ == "__main__":
    MelodyOverlay().run()
