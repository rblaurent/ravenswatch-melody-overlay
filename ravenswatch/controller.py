"""
Game controller for Ravenswatch.
Provides screenshot capture, mouse clicks, and keyboard input
relative to the game window. Designed for AI-driven automation.
"""

import ctypes
import ctypes.wintypes as wt
import struct
import time
from pathlib import Path

from . import process

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_MOVE = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_SPACE = 0x20

NAMED_KEYS = {
    "escape": VK_ESCAPE, "esc": VK_ESCAPE,
    "enter": VK_RETURN, "return": VK_RETURN,
    "space": VK_SPACE,
}


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KeybdInput(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeybdInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _InputUnion)]


def _send_input(*inputs):
    arr = (_Input * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(_Input))


class GameController:
    """Controls Ravenswatch via window-relative input and screen capture."""

    def __init__(self, screenshot_dir: Path | str | None = None):
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else Path("screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_counter = 0

    def _get_window(self) -> tuple[int, tuple[int, int, int, int]]:
        hwnd = process.find_window()
        if hwnd is None:
            raise RuntimeError("Ravenswatch window not found")
        rect = process.get_window_rect(hwnd)
        if rect is None:
            raise RuntimeError("Cannot get window rect")
        return hwnd, rect

    @property
    def window_size(self) -> tuple[int, int]:
        _, (l, t, r, b) = self._get_window()
        return (r - l, b - t)

    def screenshot(self, name: str | None = None) -> Path:
        """Capture the game window to a PNG file. Returns the file path."""
        try:
            import mss
            import mss.tools
        except ImportError:
            raise ImportError("mss is required: pip install mss")

        _, (left, top, right, bottom) = self._get_window()
        monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}

        with mss.mss() as sct:
            img = sct.grab(monitor)
            self._screenshot_counter += 1
            fname = name or f"screenshot_{self._screenshot_counter:04d}"
            if not fname.endswith(".png"):
                fname += ".png"
            path = self.screenshot_dir / fname
            mss.tools.to_png(img.rgb, img.size, output=str(path))
        return path

    def click(self, x: int, y: int, delay: float = 0.08):
        """Click at (x, y) relative to the game window's client area."""
        _, (left, top, _, _) = self._get_window()
        abs_x = left + x
        abs_y = top + y

        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        norm_x = int(abs_x * 65535 / screen_w)
        norm_y = int(abs_y * 65535 / screen_h)

        move = _Input()
        move.type = INPUT_MOUSE
        move.union.mi.dx = norm_x
        move.union.mi.dy = norm_y
        move.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
        _send_input(move)

        time.sleep(0.02)

        down = _Input()
        down.type = INPUT_MOUSE
        down.union.mi.dx = norm_x
        down.union.mi.dy = norm_y
        down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE
        _send_input(down)

        time.sleep(delay)

        up = _Input()
        up.type = INPUT_MOUSE
        up.union.mi.dx = norm_x
        up.union.mi.dy = norm_y
        up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE
        _send_input(up)

        time.sleep(0.05)

    def click_center(self):
        """Click the center of the game window."""
        w, h = self.window_size
        self.click(w // 2, h // 2)

    def click_relative(self, rx: float, ry: float, delay: float = 0.08):
        """Click at a position relative to window size (0.0-1.0 for both axes)."""
        w, h = self.window_size
        self.click(int(w * rx), int(h * ry), delay)

    def press_key(self, key: str | int, hold: float = 0.05):
        """Press a key. Accepts key name ('escape', 'enter', 'space') or VK code."""
        process.focus_window()

        if isinstance(key, str):
            vk = NAMED_KEYS.get(key.lower())
            if vk is None:
                if len(key) == 1:
                    vk = ord(key.upper())
                else:
                    raise ValueError(f"Unknown key: {key}")
        else:
            vk = key

        scan = user32.MapVirtualKeyW(vk, 0)

        down = _Input()
        down.type = INPUT_KEYBOARD
        down.union.ki.wVk = vk
        down.union.ki.wScan = scan
        down.union.ki.dwFlags = 0
        _send_input(down)

        time.sleep(hold)

        up = _Input()
        up.type = INPUT_KEYBOARD
        up.union.ki.wVk = vk
        up.union.ki.wScan = scan
        up.union.ki.dwFlags = KEYEVENTF_KEYUP
        _send_input(up)

        time.sleep(0.05)

    def wait(self, seconds: float):
        """Wait for a specified duration."""
        time.sleep(seconds)

    def launch_and_wait(self, timeout: int = 60) -> bool:
        """Launch the game via Steam and wait for the window to appear."""
        if not process.launch(wait_seconds=timeout):
            return False
        for _ in range(timeout):
            if process.find_window() is not None:
                time.sleep(2)
                return True
            time.sleep(1)
        return False

    @property
    def is_running(self) -> bool:
        return process.is_running()
