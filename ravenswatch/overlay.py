"""
Native Windows overlay showing the three melodies of the current run.

A layered, click-through, topmost win32 window (per-pixel alpha via
UpdateLayeredWindow) — the standard technique for game overlays. It works
over borderless-fullscreen games, never takes focus or mouse input, and
needs no GUI toolkit: frames are composed with Pillow and blitted via GDI.

Lifecycle (noobie-proof): start it any time. It waits for the game, shows
one icon + name above each of the three HUD staff dots while in a run
(active melody underlined, note-count color coding), hides in the lobby,
and exits automatically when the game closes.
"""

import ctypes
import ctypes.wintypes as wt
import time

from PIL import Image, ImageDraw, ImageFont

from .memory import MemoryReader
from .melody_data import Melody
from .resources import icon_path
from . import process

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- layout (relative to the game window; tuned on the live HUD) ---
STAFF_DOTS_RX = [0.749, 0.778, 0.810]
STAFF_DOT_RY = 0.912

NOTE_COLORS = {4: (0x16, 0xc7, 0x9a), 5: (0xf5, 0xa6, 0x23), 6: (0xe9, 0x45, 0x60)}
REFRESH_INTERVAL = 4.0
TOAST_SECONDS = 8.0

# reference sizes at 2160p game height, scaled by actual height
REF_H = 2160
REF_ICON = 56
REF_FONT = 15
REF_COL_W = 160

# global fade applied to the composed frame, like the old whole-window 0.3 alpha
OVERLAY_ALPHA = 0.35

# --- win32 constants ---
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020  # click-through
WS_EX_TOOLWINDOW = 0x00000080   # no taskbar / alt-tab entry
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 2
AC_SRC_ALPHA = 1
PM_REMOVE = 1

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte),
    ]


# 64-bit safe signatures for everything returning/taking pointers
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = ctypes.c_void_p
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
]
user32.GetDC.restype = ctypes.c_void_p
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.DestroyWindow.argtypes = [ctypes.c_void_p]
user32.UpdateLayeredWindow.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p, wt.COLORREF, ctypes.c_void_p, wt.DWORD,
]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
gdi32.CreateDIBSection.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wt.DWORD,
]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]


def _set_dpi_aware():
    """Opt into per-monitor DPI awareness so window coords are physical pixels."""
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except (AttributeError, OSError):
        pass


class _LayeredWindow:
    """Topmost click-through window painted from a Pillow RGBA image."""

    CLASS_NAME = "RavenswatchMelodyOverlay"

    def __init__(self):
        self._wndproc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
        hinst = kernel32.GetModuleHandleW(None)
        wc = _WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = self.CLASS_NAME
        user32.RegisterClassW(ctypes.byref(wc))  # may already exist; fine
        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            self.CLASS_NAME, "Ravenswatch Melodies", WS_POPUP,
            0, 0, 1, 1, None, None, hinst, None,
        )
        if not self.hwnd:
            raise OSError("CreateWindowExW failed")
        self._visible = False

    def show_image(self, img: Image.Image, x: int, y: int):
        """Blit an RGBA image to the window at screen position (x, y)."""
        w, h = img.size
        screen_dc = user32.GetDC(None)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), 0,
                                      ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(mem_dc, hbmp)
        ctypes.memmove(bits, img.tobytes("raw", "BGRa"), w * h * 4)  # premultiplied BGRA

        blend = _BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
        pos = wt.POINT(x, y)
        size = wt.SIZE(w, h)
        src = wt.POINT(0, 0)
        user32.UpdateLayeredWindow(self.hwnd, screen_dc, ctypes.byref(pos),
                                   ctypes.byref(size), mem_dc, ctypes.byref(src),
                                   0, ctypes.byref(blend), ULW_ALPHA)

        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
        if not self._visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self._visible = True

    def hide(self):
        if self._visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self._visible = False

    def pump(self):
        msg = wt.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def destroy(self):
        user32.DestroyWindow(self.hwnd)


def _load_font(px: int):
    for name in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


class MelodyOverlay:
    def __init__(self):
        _set_dpi_aware()
        self._win = _LayeredWindow()
        self._reader = MemoryReader()
        self._icon_cache = {}  # (name, size) -> RGBA image
        self._font_cache = {}  # px -> font

    # --- rendering ---

    def _font(self, px: int):
        if px not in self._font_cache:
            self._font_cache[px] = _load_font(px)
        return self._font_cache[px]

    def _icon(self, name: str, size: int) -> Image.Image | None:
        key = (name, size)
        if key not in self._icon_cache:
            path = icon_path(name)
            img = None
            if path:
                img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
            self._icon_cache[key] = img
        return self._icon_cache[key]

    def _render_melodies(self, melodies: list[Melody], active: Melody | None,
                         rect: tuple[int, int, int, int]):
        left, top, right, bottom = rect
        gw, gh = right - left, bottom - top
        s = gh / REF_H
        icon_px = max(24, int(REF_ICON * s))
        font_px = max(11, int(REF_FONT * s))
        col_w = max(80, int(REF_COL_W * s))
        font = self._font(font_px)
        text_h = font_px + 8
        height = text_h + 4 + icon_px + 4

        dot_xs = [int(gw * rx) for rx in STAFF_DOTS_RX]
        half = col_w // 2
        width = dot_xs[-1] - dot_xs[0] + col_w
        centers = [x - dot_xs[0] + half for x in dot_xs]

        # slots before the active one are unlocked: the game HUD itself shows
        # them on the staff, so the overlay must not draw on top of them
        active_idx = 0
        if active is not None:
            for i, m in enumerate(melodies):
                if m.internal_name == active.internal_name:
                    active_idx = i
                    break

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for slot, (m, cx) in enumerate(zip(melodies, centers)):
            if slot < active_idx:
                continue
            color = NOTE_COLORS.get(m.notes, (255, 255, 255))
            is_active = active is not None and m.internal_name == active.internal_name

            tw = draw.textlength(m.display_name, font=font)
            tx = cx - tw / 2
            draw.text((tx, 2), m.display_name, font=font, fill=color + (255,),
                      stroke_width=2, stroke_fill=(0, 0, 0, 255))
            if is_active:
                uy = 2 + font_px + 4
                draw.line([(tx, uy), (tx + tw, uy)], fill=color + (255,),
                          width=max(2, int(2 * s)))

            icon = self._icon(m.display_name, icon_px)
            if icon:
                img.alpha_composite(icon, (cx - icon_px // 2, text_h + 4))

        img.putalpha(img.getchannel("A").point(lambda v: int(v * OVERLAY_ALPHA)))

        ox = left + dot_xs[0] - half
        # icon bottoms rest on the staff dots row, like the original overlay
        oy = top + int(gh * STAFF_DOT_RY) - height + int(5 * s)
        self._win.show_image(img, ox, oy)

    def _render_toast(self, game_running: bool):
        text = ("Melody overlay active — melodies appear during runs"
                if game_running else
                "Melody overlay — waiting for Ravenswatch...")
        font = self._font(18)
        tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        tw = int(tmp.textlength(text, font=font))
        pad_x, pad_y = 22, 12
        w, h = tw + 2 * pad_x, 18 + 2 * pad_y
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2,
                               fill=(10, 12, 24, 215), outline=(245, 166, 35, 235), width=2)
        draw.text((pad_x, pad_y - 2), text, font=font, fill=(255, 255, 255, 245))
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        self._win.show_image(img, (sw - w) // 2, int(sh * 0.82))

    # --- main loop ---

    def run(self):
        seen_game = False
        toast_until = time.time() + TOAST_SECONDS
        next_poll = 0.0
        try:
            while True:
                self._win.pump()
                now = time.time()
                if now >= next_poll:
                    next_poll = now + REFRESH_INTERVAL
                    running = process.is_running()
                    if running:
                        seen_game = True
                    elif seen_game:
                        break  # game closed -> exit with it

                    info = rect = None
                    if running:
                        hwnd = process.find_window()
                        rect = process.get_window_rect(hwnd) if hwnd else None
                        try:
                            info = self._reader.read_run_info()
                        except Exception:
                            info = None

                    if info and rect:
                        self._render_melodies(info[0], info[1], rect)
                    elif now < toast_until:
                        self._render_toast(running)
                    else:
                        self._win.hide()
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self._win.destroy()
            self._reader.disconnect()
