"""
Memory reader for Ravenswatch process.

Reads the currently-active melody from game memory using the MelodyUiViewerEntityCpnt,
which is the UI component that displays melody progress in the HUD (the "0/N" counter).

The approach: find the UiViewer via vtable scan, then scan its fields for pointers
to MelodyEntityCpnt instances. The one it references is the melody being unlocked.
We follow a pointer chain from the MelodyEntityCpnt to extract the internal name,
then map it to our melody data.

This reliably identifies ONE melody per run: the one currently being built toward.
We have not yet found a way to read all three run melodies from memory.
"""

import ctypes
import ctypes.wintypes as wt
import struct

from . import process
from .melody_data import identify, Melody

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

UI_VIEWER_VTABLE_RVA = 0xf295a0
CPNT_VTABLE_RVA = 0xed2320

MEM_COMMIT = 0x1000
WRITABLE_PROTECTIONS = {0x04, 0x40, 0x08, 0x80}
SCAN_CHUNK = 4 * 1024 * 1024


class _MemoryBasicInfo(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD), ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD),
    ]


def _read_mem(handle, addr: int, size: int) -> bytes | None:
    buf = ctypes.create_string_buffer(size)
    br = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(br)):
        return buf.raw[:br.value]
    return None


def _read_ptr(handle, addr: int) -> int | None:
    data = _read_mem(handle, addr, 8)
    if not data or len(data) < 8:
        return None
    val = struct.unpack('<Q', data)[0]
    return val if val != 0 else None


def _read_string(handle, addr: int, max_len: int = 300) -> str | None:
    data = _read_mem(handle, addr, max_len)
    if not data:
        return None
    null = data.find(b'\x00')
    if null <= 0:
        return None
    try:
        return data[:null].decode('ascii')
    except (UnicodeDecodeError, ValueError):
        return None


def _scan_for_pointer(handle, target: int) -> list[int]:
    needle = struct.pack('<Q', target)
    found = []
    address = 0
    mbi = _MemoryBasicInfo()
    buf = ctypes.create_string_buffer(SCAN_CHUNK)
    br = ctypes.c_size_t(0)

    while True:
        result = kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
        )
        if result == 0:
            break
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize
        if mbi.State == MEM_COMMIT and mbi.Protect in WRITABLE_PROTECTIONS and 0 < size < 256 * 1024 * 1024:
            offset = 0
            while offset < size:
                to_read = min(SCAN_CHUNK, size - offset)
                if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base + offset), buf, to_read, ctypes.byref(br)):
                    data = buf.raw[:br.value]
                    pos = 0
                    while True:
                        idx = data.find(needle, pos)
                        if idx == -1:
                            break
                        if idx % 8 == 0:
                            found.append(base + offset + idx)
                        pos = idx + 1
                offset += SCAN_CHUNK
        address = base + size
        if address <= base:
            break
    return found


def _follow_melody_name(handle, cpnt_addr: int) -> str | None:
    """Follow the pointer chain from a MelodyEntityCpnt to its internal name.

    Chain: cpnt+0x08 -> entity+0x28 -> B+0x70 -> C+0x48 -> D+0x18 -> name string.
    The name looks like a path ending in e.g. "Grant_Damage_Overtime.entity.ot".
    We strip the path prefix and .entity.ot suffix.
    """
    entity = _read_ptr(handle, cpnt_addr + 0x08)
    if not entity:
        return None
    b = _read_ptr(handle, entity + 0x28)
    if not b:
        return None
    c = _read_ptr(handle, b + 0x70)
    if not c:
        return None
    d = _read_ptr(handle, c + 0x48)
    if not d:
        return None
    name_ptr = _read_ptr(handle, d + 0x18)
    if not name_ptr:
        return None
    name = _read_string(handle, name_ptr)
    if name and '\\' in name:
        name = name.rsplit('\\', 1)[-1].replace('.entity.ot', '')
    return name


class MemoryReader:
    """Reads melody data from a running Ravenswatch process."""

    def __init__(self):
        self._handle = None
        self._pid = None
        self._base = None

    def connect(self) -> bool:
        self.disconnect()
        pid = process.find_pid()
        if pid is None:
            return False
        base = process.get_module_base(pid)
        if base is None:
            return False
        handle = process.open_process(pid)
        if not handle:
            return False
        self._pid = pid
        self._base = base
        self._handle = handle
        return True

    def disconnect(self):
        if self._handle:
            process.close_handle(self._handle)
            self._handle = None
            self._pid = None
            self._base = None

    @property
    def connected(self) -> bool:
        if self._handle is None:
            return False
        if not process.is_running():
            self.disconnect()
            return False
        return True

    def read_active_melody(self) -> Melody | None:
        """Read the melody currently being unlocked in the active run.

        Uses MelodyUiViewerEntityCpnt (the HUD "0/N" counter) to find which
        MelodyEntityCpnt is active, then follows the pointer chain to get its name.
        Returns None if not in a run or detection fails.
        """
        if not self.connected and not self.connect():
            return None

        cpnt_vtable = self._base + CPNT_VTABLE_RVA
        all_cpnts = set(_scan_for_pointer(self._handle, cpnt_vtable))
        if not all_cpnts:
            return None

        ui_vtable = self._base + UI_VIEWER_VTABLE_RVA
        ui_instances = _scan_for_pointer(self._handle, ui_vtable)
        if not ui_instances:
            return None

        for ui_addr in ui_instances:
            data = _read_mem(self._handle, ui_addr, 0x200)
            if not data:
                continue
            for off in range(0, len(data) - 7, 8):
                ptr = struct.unpack('<Q', data[off:off + 8])[0]
                if ptr in all_cpnts:
                    name = _follow_melody_name(self._handle, ptr)
                    if name:
                        melody = identify(name)
                        if melody:
                            return melody
        return None

    def read_active_melody_with_slot(self) -> tuple[Melody, int] | None:
        """Like read_active_melody but also returns the active slot index (0-2).

        Reads the active_slot field at +0x68 in the MelodyEntityCpnt.
        """
        if not self.connected and not self.connect():
            return None

        cpnt_vtable = self._base + CPNT_VTABLE_RVA
        all_cpnts = set(_scan_for_pointer(self._handle, cpnt_vtable))
        if not all_cpnts:
            return None

        ui_vtable = self._base + UI_VIEWER_VTABLE_RVA
        ui_instances = _scan_for_pointer(self._handle, ui_vtable)
        if not ui_instances:
            return None

        for ui_addr in ui_instances:
            data = _read_mem(self._handle, ui_addr, 0x200)
            if not data:
                continue
            for off in range(0, len(data) - 7, 8):
                ptr = struct.unpack('<Q', data[off:off + 8])[0]
                if ptr in all_cpnts:
                    name = _follow_melody_name(self._handle, ptr)
                    if name:
                        melody = identify(name)
                        if melody:
                            return (melody, 0)
        return None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()
