"""Process management for Ravenswatch: find, launch, get window handle."""

import ctypes
import ctypes.wintypes as wt
import subprocess
import time
from pathlib import Path

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

GAME_EXE = "Ravenswatch.exe"
DEFAULT_GAME_PATH = Path(r"G:\SteamLibrary\steamapps\common\Ravenswatch\Ravenswatch.exe")
STEAM_APP_ID = "2071280"


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


class _ModuleEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wt.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * 260),
    ]


def find_pid() -> int | None:
    snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    pe = _ProcessEntry()
    pe.dwSize = ctypes.sizeof(pe)
    if kernel32.Process32First(snap, ctypes.byref(pe)):
        while True:
            if pe.szExeFile.decode(errors="ignore").lower() == GAME_EXE.lower():
                pid = pe.th32ProcessID
                kernel32.CloseHandle(snap)
                return pid
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break
    kernel32.CloseHandle(snap)
    return None


def get_module_base(pid: int, module_name: str = GAME_EXE) -> int | None:
    snap = kernel32.CreateToolhelp32Snapshot(0x00000008 | 0x00000010, pid)
    me = _ModuleEntry()
    me.dwSize = ctypes.sizeof(me)
    if kernel32.Module32First(snap, ctypes.byref(me)):
        while True:
            if me.szModule.decode(errors="ignore").lower() == module_name.lower():
                base = me.modBaseAddr
                kernel32.CloseHandle(snap)
                return base
            if not kernel32.Module32Next(snap, ctypes.byref(me)):
                break
    kernel32.CloseHandle(snap)
    return None


def open_process(pid: int):
    return kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)


def close_handle(handle):
    kernel32.CloseHandle(handle)


def find_window() -> int | None:
    """Find the Ravenswatch game window handle."""
    game_pid = find_pid()
    if game_pid is None:
        return None

    pid_out = wt.DWORD()
    result = []
    fallback = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def enum_cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
        if pid_out.value != game_pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if "ravenswatch" in buf.value.strip().lower():
                result.append(hwnd)
                return True
        fallback.append(hwnd)
        return True

    user32.EnumWindows(enum_cb, 0)
    if result:
        return result[0]
    return fallback[0] if fallback else None


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Returns (left, top, right, bottom) of the window client area in screen coords."""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                     ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None

    pt = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y, pt.x + rect.right, pt.y + rect.bottom)


def is_running() -> bool:
    return find_pid() is not None


def launch(game_path: Path | None = None, via_steam: bool = True, wait_seconds: int = 30) -> bool:
    """Launch Ravenswatch. Returns True if the game process is found after launch."""
    if is_running():
        return True

    if via_steam:
        subprocess.Popen(
            ["cmd", "/c", f"start steam://rungameid/{STEAM_APP_ID}"],
            shell=False
        )
    else:
        exe = game_path or DEFAULT_GAME_PATH
        if not exe.exists():
            raise FileNotFoundError(f"Game not found at {exe}")
        subprocess.Popen([str(exe)])

    for _ in range(wait_seconds):
        time.sleep(1)
        if is_running():
            time.sleep(2)
            return True
    return False


def focus_window() -> bool:
    """Bring the Ravenswatch window to the foreground."""
    hwnd = find_window()
    if hwnd is None:
        return False
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return True
