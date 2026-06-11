"""
Live overlay showing the melody currently being unlocked.
Transparent window positioned over the correct dot on the game's music staff.
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

STAFF_DOTS_RX = [0.749, 0.789, 0.829]
STAFF_DOT_RY = 0.912

NOTE_COLORS = {4: "#16c79a", 5: "#f5a623", 6: "#e94560"}
REFRESH_INTERVAL = 4
ICON_SIZE = 56
TRANSP_COLOR = "#010101"


class MelodyOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Melody")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSP_COLOR)
        self.root.attributes("-transparentcolor", TRANSP_COLOR)
        self.root.attributes("-alpha", 0.5)

        self._icon_cache = {}
        self._current_photo = None
        self._game_rect = None

        self.name_label = tk.Label(
            self.root, text="",
            font=("Segoe UI", 10, "bold"), fg="#fff", bg=TRANSP_COLOR,
        )
        self.name_label.pack(pady=(0, 2))

        self.icon_label = tk.Label(self.root, bg=TRANSP_COLOR, bd=0)
        self.icon_label.pack()

        self._update_game_rect()
        self._position_on_dot(0)

        self._reader = MemoryReader()
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _update_game_rect(self):
        hwnd = process.find_window()
        if hwnd:
            self._game_rect = process.get_window_rect(hwnd)

    def _position_on_dot(self, slot: int):
        if not self._game_rect:
            self.root.geometry("160x80+100+100")
            return
        left, top, right, bottom = self._game_rect
        w = right - left
        h = bottom - top
        rx = STAFF_DOTS_RX[min(slot, 2)]
        ry = STAFF_DOT_RY
        cx = left + int(w * rx)
        cy = top + int(h * ry)
        ox = cx - 80
        oy = cy - 75
        self.root.geometry(f"160x80+{ox}+{oy}")

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
                result = self._reader.read_active_melody_with_slot()
                if result:
                    melody, slot = result
                    self.root.after(0, lambda m=melody, s=slot: self._show(m, s))
                else:
                    self.root.after(0, self._hide)
            except Exception:
                self.root.after(0, self._hide)
            time.sleep(REFRESH_INTERVAL)

    def _show(self, m: Melody, slot: int):
        color = NOTE_COLORS.get(m.notes, "#fff")
        photo = self._load_icon(m.display_name)
        if photo:
            self._current_photo = photo
            self.icon_label.config(image=photo)
        self.name_label.config(text=m.display_name, fg=color)
        self._position_on_dot(slot)
        self.root.deiconify()

    def _hide(self):
        self.root.withdraw()

    def run(self):
        self.root.mainloop()
        self._running = False
        self._reader.disconnect()
