"""
Native Windows overlay showing the three melodies of the current run.

A layered, click-through, topmost win32 window (per-pixel alpha via
UpdateLayeredWindow) — the standard technique for game overlays. It works
over borderless-fullscreen games, never takes focus or mouse input, and
needs no GUI toolkit: frames are composed with Pillow and blitted via GDI.

Lifecycle: start it any time. Only one instance can run (enforced via named
mutex). A system tray icon shows current status and provides an Exit action.
The overlay waits for the game, shows melody icons above the HUD staff dots
while in a run, hides in the lobby, and exits when the game closes.
"""

import ctypes
import ctypes.wintypes as wt
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from .memory import MemoryReader
from .melody_data import Melody
from .resources import icon_path, icons_dir
from . import process

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# --- layout (relative to the game window; tuned on the live HUD) ---
STAFF_DOTS_RX = [0.749, 0.778, 0.810]
STAFF_DOT_RY = 0.912

NOTE_COLORS = {4: (0x16, 0xc7, 0x9a), 5: (0xf5, 0xa6, 0x23), 6: (0xe9, 0x45, 0x60)}
REFRESH_INTERVAL = 4.0
ACCESS_HINT_POLLS = 3

REF_H = 2160
REF_ICON = 56
REF_FONT = 15
REF_COL_W = 160

OVERLAY_ALPHA = 0.35

# --- win32 constants ---
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 2
AC_SRC_ALPHA = 1
PM_REMOVE = 1
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_TRAYICON = 0x8000  # WM_APP
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
MF_STRING = 0
MF_SEPARATOR = 0x0800
MF_GRAYED = 1
TPM_RIGHTBUTTON = 2
IDM_EXIT = 1001
IDM_STATUS = 1000
IDM_TOGGLE = 1002
IDM_LABELS = 1003
MF_CHECKED = 0x0008
MF_UNCHECKED = 0x0000
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\RavenswatchMelodyOverlay"

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


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", ctypes.c_void_p),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wt.BOOL),
        ("xHotspot", wt.DWORD),
        ("yHotspot", wt.DWORD),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


# 64-bit safe signatures
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
gdi32.CreateBitmap.restype = ctypes.c_void_p
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wt.UINT, wt.UINT, ctypes.c_void_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.c_void_p]
shell32.Shell_NotifyIconW.restype = wt.BOOL
user32.CreatePopupMenu.restype = ctypes.c_void_p
user32.AppendMenuW.argtypes = [ctypes.c_void_p, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.argtypes = [
    ctypes.c_void_p, wt.UINT, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
]
user32.DestroyMenu.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.CreateIconIndirect.restype = ctypes.c_void_p
user32.CreateIconIndirect.argtypes = [ctypes.c_void_p]
user32.DestroyIcon.argtypes = [ctypes.c_void_p]
user32.PostMessageW.argtypes = [ctypes.c_void_p, wt.UINT, wt.WPARAM, wt.LPARAM]


def _set_dpi_aware():
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


def _create_hicon(img: Image.Image, size: int = 32):
    """Create a win32 HICON from a Pillow RGBA image."""
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    screen_dc = user32.GetDC(None)
    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(bmi)
    bmi.biWidth = size
    bmi.biHeight = -size
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bits = ctypes.c_void_p()
    hbmp_color = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), 0,
                                         ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, img.tobytes("raw", "BGRA"), size * size * 4)
    user32.ReleaseDC(None, screen_dc)
    hbmp_mask = gdi32.CreateBitmap(size, size, 1, 1, None)
    ii = _ICONINFO()
    ii.fIcon = True
    ii.hbmMask = hbmp_mask
    ii.hbmColor = hbmp_color
    hicon = user32.CreateIconIndirect(ctypes.byref(ii))
    gdi32.DeleteObject(hbmp_color)
    gdi32.DeleteObject(hbmp_mask)
    return hicon


def _load_app_icon():
    """Load the app icon (Fairy Godmother) as an HICON for the tray."""
    path = icon_path("Fairy Godmother")
    if path:
        return _create_hicon(Image.open(path), 32)
    return user32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION


# --- singleton mutex ---

def _acquire_mutex():
    """Returns mutex handle if we're the first instance, None if already running."""
    h = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(h)
        return None
    return h


# --- tray icon ---

_tray_instance = None


def _tray_wndproc(hwnd, msg, wparam, lparam):
    global _tray_instance
    if msg == WM_TRAYICON and _tray_instance:
        event = lparam & 0xFFFF
        if event == 0x0205:  # WM_RBUTTONUP
            _tray_instance._show_menu()
            return 0
        if event == 0x0203:  # WM_LBUTTONDBLCLK
            _tray_instance._show_menu()
            return 0
    elif msg == WM_COMMAND and _tray_instance:
        cmd = wparam & 0xFFFF
        if cmd == IDM_EXIT:
            _tray_instance.exit_requested = True
            return 0
        if cmd == IDM_TOGGLE:
            _tray_instance.overlay_visible = not _tray_instance.overlay_visible
            return 0
        if cmd == IDM_LABELS:
            _tray_instance.show_labels = not _tray_instance.show_labels
            return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class _TrayIcon:
    CLASS_NAME = "RavenswatchTrayMsg"

    def __init__(self):
        global _tray_instance
        _tray_instance = self
        self.exit_requested = False
        self.overlay_visible = True
        self.show_labels = True
        self.melody_lines = []  # ["Galahad ♫", "Lady of the Lake", ...]
        self._hicon = _load_app_icon()

        self._wndproc_ref = WNDPROC(_tray_wndproc)
        hinst = kernel32.GetModuleHandleW(None)
        wc = _WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = self.CLASS_NAME
        user32.RegisterClassW(ctypes.byref(wc))

        self._hwnd = user32.CreateWindowExW(
            0, self.CLASS_NAME, "RavenswatchTray", 0,
            0, 0, 0, 0, None, None, hinst, None,
        )

        self._nid = _NOTIFYICONDATAW()
        self._nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        self._nid.hWnd = self._hwnd
        self._nid.uID = 1
        self._nid.uFlags = NIF_ICON | NIF_TIP | NIF_MESSAGE
        self._nid.uCallbackMessage = WM_TRAYICON
        self._nid.hIcon = self._hicon
        self._nid.szTip = "Ravenswatch Melody Overlay"
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid))

    def update_tooltip(self, text: str):
        tip = text[:127]
        self._nid.uFlags = NIF_TIP
        self._nid.szTip = tip
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def _show_menu(self):
        menu = user32.CreatePopupMenu()
        if self.melody_lines:
            for line in self.melody_lines:
                user32.AppendMenuW(menu, MF_GRAYED, 0, line)
        else:
            user32.AppendMenuW(menu, MF_GRAYED, 0, self._nid.szTip)
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        check = MF_CHECKED if self.overlay_visible else MF_UNCHECKED
        user32.AppendMenuW(menu, MF_STRING | check, IDM_TOGGLE, "Show overlay")
        check_labels = MF_CHECKED if self.show_labels else MF_UNCHECKED
        user32.AppendMenuW(menu, MF_STRING | check_labels, IDM_LABELS, "Show song labels")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, IDM_EXIT, "Exit")

        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self._hwnd)
        user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, self._hwnd, None)
        user32.DestroyMenu(menu)
        user32.PostMessageW(self._hwnd, 0, 0, 0)

    def destroy(self):
        global _tray_instance
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        user32.DestroyWindow(self._hwnd)
        if self._hicon:
            user32.DestroyIcon(self._hicon)
        _tray_instance = None


# --- layered window ---

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
        user32.RegisterClassW(ctypes.byref(wc))
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
        w, h = img.size
        screen_dc = user32.GetDC(None)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), 0,
                                      ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(mem_dc, hbmp)
        ctypes.memmove(bits, img.tobytes("raw", "BGRa"), w * h * 4)

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


# --- melody overlay ---

class MelodyOverlay:
    def __init__(self):
        _set_dpi_aware()
        self._win = _LayeredWindow()
        self._reader = MemoryReader()
        self._icon_cache = {}
        self._font_cache = {}
        self._prev_states = None

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

    def _wrap_text(self, text: str, font, max_width: int) -> list[str]:
        """Split text into lines that fit within max_width."""
        if font.getlength(text) <= max_width:
            return [text]
        words = text.split()
        if len(words) == 1:
            return [text]
        best_split = len(words) // 2
        best_diff = float('inf')
        for i in range(1, len(words)):
            line1 = ' '.join(words[:i])
            line2 = ' '.join(words[i:])
            diff = abs(font.getlength(line1) - font.getlength(line2))
            if diff < best_diff:
                best_diff = diff
                best_split = i
        return [' '.join(words[:best_split]), ' '.join(words[best_split:])]

    def _render_melodies(self, melodies: list[Melody], states: list[int],
                         rect: tuple[int, int, int, int], show_labels: bool = True):
        left, top, right, bottom = rect
        gw, gh = right - left, bottom - top
        s = gh / REF_H
        icon_px = max(24, int(REF_ICON * s))
        font_px = max(11, int(REF_FONT * s))
        font = self._font(font_px)

        dot_xs = [int(gw * rx) for rx in STAFF_DOTS_RX]
        col_w = min(dot_xs[i + 1] - dot_xs[i] for i in range(len(dot_xs) - 1))

        line_h = font_px + 4
        max_lines = 1
        if show_labels:
            for m in melodies:
                lines = self._wrap_text(m.display_name, font, col_w - 4)
                max_lines = max(max_lines, len(lines))
        text_h = (line_h * max_lines + 4) if show_labels else 0
        height = text_h + 4 + icon_px + 4

        half = col_w // 2
        width = dot_xs[-1] - dot_xs[0] + col_w
        centers = [x - dot_xs[0] + half for x in dot_xs]

        prev = self._prev_states if self._prev_states is not None else states
        self._prev_states = states
        hidden = [st >= 2 and pv >= 2 for st, pv in zip(states, prev)]
        if all(hidden):
            self._win.hide()
            return

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for slot, (m, cx) in enumerate(zip(melodies, centers)):
            if hidden[slot]:
                continue
            color = NOTE_COLORS.get(m.notes, (255, 255, 255))

            if show_labels:
                lines = self._wrap_text(m.display_name, font, col_w - 4)
                y_off = (max_lines - len(lines)) * line_h
                for li, line in enumerate(lines):
                    tw = draw.textlength(line, font=font)
                    tx = cx - tw / 2
                    ty = 2 + y_off + li * line_h
                    draw.text((tx, ty), line, font=font, fill=color + (255,),
                              stroke_width=2, stroke_fill=(0, 0, 0, 255))

            icon = self._icon(m.display_name, icon_px)
            if icon:
                img.alpha_composite(icon, (cx - icon_px // 2, text_h + 4))

        img.putalpha(img.getchannel("A").point(lambda v: int(v * OVERLAY_ALPHA)))

        ox = left + dot_xs[0] - half
        oy = top + int(gh * STAFF_DOT_RY) - height + int(5 * s)
        self._win.show_image(img, ox, oy)

    def _status_text(self, running: bool, connected: bool,
                     info: tuple | None, denied: int) -> str:
        if not running:
            return "Waiting for Ravenswatch..."
        if denied >= ACCESS_HINT_POLLS:
            return "Can't read game (run as admin?)"
        if not connected:
            return "Connecting..."
        if info:
            melodies, states = info
            parts = []
            for m, st in zip(melodies, states):
                label = m.display_name
                if st == 1:
                    label += " ♫"
                elif st >= 2:
                    label += " ✓"
                parts.append(label)
            return " | ".join(parts)
        return "In lobby"

    def _poll_loop(self):
        """Background thread: polls game memory, stores results."""
        denied_polls = 0
        while not self._stop_event.is_set():
            running = process.is_running()

            info = None
            rect = None
            connected = False
            if running:
                hwnd = process.find_window()
                rect = process.get_window_rect(hwnd) if hwnd else None
                if self._reader.connected or self._reader.connect():
                    denied_polls = 0
                    connected = True
                    try:
                        info = self._reader.read_run_info()
                    except Exception:
                        info = None
                else:
                    denied_polls += 1
            else:
                if self._reader._handle is not None:
                    self._reader.disconnect()
                denied_polls = 0

            self._poll_result = (running, connected, info, rect, denied_polls)
            self._stop_event.wait(REFRESH_INTERVAL)

    def run(self):
        mutex = _acquire_mutex()
        if not mutex:
            return

        tray = _TrayIcon()
        self._stop_event = threading.Event()
        self._poll_result = (False, False, None, None, 0)

        poller = threading.Thread(target=self._poll_loop, daemon=True)
        poller.start()

        try:
            while not tray.exit_requested:
                self._win.pump()

                running, connected, info, rect, denied_polls = self._poll_result

                status = self._status_text(running, connected, info, denied_polls)
                tray.update_tooltip(status)
                if info:
                    melodies, states = info
                    lines = []
                    for m, st in zip(melodies, states):
                        marker = " ♫" if st == 1 else (" ✓" if st >= 2 else "")
                        lines.append(f"{m.display_name} ({m.notes} notes){marker}")
                    tray.melody_lines = lines
                else:
                    tray.melody_lines = []

                if info and rect and tray.overlay_visible:
                    self._render_melodies(info[0], info[1], rect, tray.show_labels)
                else:
                    self._prev_states = None
                    self._win.hide()

                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop_event.set()
            poller.join(timeout=2)
            tray.destroy()
            self._win.destroy()
            self._reader.disconnect()
            kernel32.CloseHandle(mutex)
