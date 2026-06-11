"""
Live overlay showing the three melodies of the current run.
Transparent window positioned over the music staff in the game's HUD,
one faded icon + name above each of the three staff dots (unlock order).
The currently-active melody's name is underlined.
"""

import threading
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

from .memory import MemoryReader
from .melody_data import Melody
from . import process

ICONS_DIR = Path(__file__).parent.parent / "icons"

ICON_FILENAMES = {
    "Fairy Godmother": "UI_Melody_Icon_Godfairy.png",
    "Tortoise": "UI_Melody_Icon_Turtle.png",
    "Lady of the Lake": "UI_Melody_Icon_LadyLake.png",
    "Galahad": "UI_Melody_Icon_Galahad.png",
    "Merry Men": "UI_Melody_Icon_MerryMen.png",
    "Goose Girl": "UI_Melody_Icon_Goose.png",
    "Hansel & Gretel": "UI_Melody_Icon_Hansel.png",
    "Little Tailor": "UI_Melody_Icon_Tailor.png",
    "Lucky Hans": "UI_Melody_Icon_LuckyHans.png",
    "Otohime": "UI_Melody_Icon_OtoHime.png",
    "Long John Silver": "UI_Melody_Icon_LongJohnSilver.png",
    "Sheherazad": "UI_Melody_Icon_Sherazade.png",
}

STAFF_DOTS_RX = [0.749, 0.778, 0.810]
STAFF_DOT_RY = 0.912

NOTE_COLORS = {4: "#16c79a", 5: "#f5a623", 6: "#e94560"}
REFRESH_INTERVAL = 4
ICON_SIZE = 56
COLUMN_WIDTH = 160
WINDOW_HEIGHT = 80
TRANSP_COLOR = "#010101"

FONT = ("Segoe UI", 10, "bold")
FONT_ACTIVE = ("Segoe UI", 10, "bold underline")


class MelodyOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Melodies")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSP_COLOR)
        self.root.attributes("-transparentcolor", TRANSP_COLOR)
        self.root.attributes("-alpha", 0.3)

        self._icon_cache = {}
        self._game_rect = None

        # one column (name above icon) per staff dot, placed by pixel offset
        self._columns = []
        for _ in range(3):
            name = tk.Label(self.root, text="", font=FONT, fg="#fff", bg=TRANSP_COLOR)
            icon = tk.Label(self.root, bg=TRANSP_COLOR, bd=0)
            self._columns.append({"name": name, "icon": icon, "photo": None})

        self._update_game_rect()
        self._position_window()

        self._reader = MemoryReader()
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _update_game_rect(self):
        hwnd = process.find_window()
        if hwnd:
            self._game_rect = process.get_window_rect(hwnd)

    def _position_window(self) -> list[int] | None:
        """Size/position the window over the three staff dots.

        Returns the x pixel centers of the three dots within the window,
        or None if the game window is unknown.
        """
        if not self._game_rect:
            self.root.geometry(f"480x{WINDOW_HEIGHT}+100+100")
            return None
        left, top, right, bottom = self._game_rect
        w = right - left
        h = bottom - top
        dot_xs = [int(w * rx) for rx in STAFF_DOTS_RX]
        half = COLUMN_WIDTH // 2
        ox = left + dot_xs[0] - half
        oy = top + int(h * STAFF_DOT_RY) - 75
        width = dot_xs[-1] - dot_xs[0] + COLUMN_WIDTH
        self.root.geometry(f"{width}x{WINDOW_HEIGHT}+{ox}+{oy}")
        return [x - dot_xs[0] + half for x in dot_xs]

    def _load_icon(self, melody_name: str):
        if melody_name in self._icon_cache:
            return self._icon_cache[melody_name]

        fname = ICON_FILENAMES.get(melody_name)
        if not fname:
            return None

        path = ICONS_DIR / fname
        if not path.exists():
            return None

        img = Image.open(path).convert("RGBA")
        img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._icon_cache[melody_name] = photo
        return photo

    def _poll(self):
        while self._running:
            try:
                self._update_game_rect()
                info = self._reader.read_run_info()
                if info:
                    melodies, active = info
                    self.root.after(0, lambda ms=melodies, a=active: self._show(ms, a))
                else:
                    self.root.after(0, self._hide)
            except Exception:
                self.root.after(0, self._hide)
            time.sleep(REFRESH_INTERVAL)

    def _show(self, melodies: list[Melody], active: Melody | None):
        centers = self._position_window()
        if not centers:
            return
        for m, cx, col in zip(melodies, centers, self._columns):
            color = NOTE_COLORS.get(m.notes, "#fff")
            is_active = active is not None and m.internal_name == active.internal_name
            photo = self._load_icon(m.display_name)
            if photo:
                col["photo"] = photo
                col["icon"].config(image=photo)
            col["name"].config(text=m.display_name, fg=color,
                               font=FONT_ACTIVE if is_active else FONT)
            col["name"].place(x=cx, y=0, anchor="n")
            col["icon"].place(x=cx, y=20, anchor="n")
        self.root.deiconify()

    def _hide(self):
        self.root.withdraw()

    def run(self):
        self.root.mainloop()
        self._running = False
        self._reader.disconnect()
