"""
Memory reader for Ravenswatch process.

Two detection paths:

1. Active melody (the HUD "0/N" counter): find the MelodyUiViewerEntityCpnt via
   vtable scan, then scan its fields for pointers to MelodyEntityCpnt instances.
   The one it references is the melody being unlocked. We follow a pointer chain
   from the MelodyEntityCpnt to extract the internal name.

2. ALL THREE run melodies: the hero controller's scene context stores the run's
   predetermined melody asset GUIDs in three 16-byte slots at context+0x760
   (slot order = unlock order; slot 0 is the first/active melody at run start).
   GUIDs are resolved to melodies through the static registry of the 12 base
   MelodyEntityCpnt instances (module RVA 0x14388c8): each base cpnt leads to a
   per-melody "B" object (cpnt+0x08 -> entity+0x28) which carries both the asset
   GUID (B+0x1c8) and the name chain (B+0x70 -> C+0x48 -> D+0x18 -> path string).

   Chain summary:
     hero      = vtable scan, RVA 0xf2b930 (one instance per player; pooled)
     context   = *(*(hero+0x08) + 0x30)   (null when not in a run)
     guids     = context+0x760, 3 x 16 bytes
     states    = spawned MelodyEntityCpnt lifecycle field at cpnt+0x68
                 (1 = being collected, 2 = completed; verified live by watching
                 two completions: the field flips 1->2 exactly when the next
                 melody links). The cpnts are reached via the linked-melody
                 array at hero+0x13a0 (count u32 at +0x13a8) of EVERY hero,
                 because in multiplayer a single hero's array can lag.

   When not in a run the context is null or its slots hold garbage that does not
   match any known melody GUID, which is how we detect "no run".
"""

import ctypes
import ctypes.wintypes as wt
import struct

from . import process
from .melody_data import identify, Melody

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

UI_VIEWER_VTABLE_RVA = 0xf295a0
CPNT_VTABLE_RVA = 0xed2320
HERO_VTABLE_RVA = 0xf2b930
BASE_CPNT_REGISTRY_RVA = 0x14388c8  # static {MelodyEntityCpnt** buf, u32 count} of the 12 base instances
CTX_MELODY_SLOTS_OFFSET = 0x760     # 3 x 16-byte melody GUIDs in the hero's scene context
B_GUID_OFFSET = 0x1c8               # melody asset GUID inside the B object
HERO_MELODY_ARRAY_OFFSET = 0x13a0   # {MelodyEntityCpnt** buf} at +0x13a0, u32 count at +0x13a8
MELODY_STATE_OFFSET = 0x68          # spawned cpnt lifecycle: 1 = collecting, 2 = completed

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


def _resolve_b_name(handle, b_addr: int) -> str | None:
    """Resolve a melody name from its B object.

    Chain: B+0x70 -> C+0x48 -> D+0x18 -> name string.
    The name looks like a path ending in e.g. "Grant_Damage_Overtime.entity.ot".
    We strip the path prefix and .entity.ot suffix.
    """
    c = _read_ptr(handle, b_addr + 0x70)
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


def _follow_melody_name(handle, cpnt_addr: int) -> str | None:
    """Follow the pointer chain from a MelodyEntityCpnt to its internal name.

    Chain: cpnt+0x08 -> entity+0x28 -> B, then the B name chain.
    """
    entity = _read_ptr(handle, cpnt_addr + 0x08)
    if not entity:
        return None
    b = _read_ptr(handle, entity + 0x28)
    if not b:
        return None
    return _resolve_b_name(handle, b)


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

    def _melody_guid_map(self) -> dict[bytes, Melody]:
        """Build the {16-byte asset GUID: Melody} map from the static registry
        of the 12 base MelodyEntityCpnt instances. No memory scan needed."""
        h = self._handle
        guid_map = {}
        reg_buf = _read_ptr(h, self._base + BASE_CPNT_REGISTRY_RVA)
        cnt_data = _read_mem(h, self._base + BASE_CPNT_REGISTRY_RVA + 8, 4)
        if not reg_buf or not cnt_data:
            return guid_map
        count = struct.unpack('<I', cnt_data)[0]
        if not 0 < count <= 16:
            return guid_map
        buf = _read_mem(h, reg_buf, count * 8)
        if not buf or len(buf) < count * 8:
            return guid_map
        for i in range(count):
            cpnt = struct.unpack_from('<Q', buf, i * 8)[0]
            entity = _read_ptr(h, cpnt + 0x08) if cpnt else None
            b = _read_ptr(h, entity + 0x28) if entity else None
            if not b:
                continue
            guid = _read_mem(h, b + B_GUID_OFFSET, 16)
            name = _resolve_b_name(h, b)
            melody = identify(name) if name else None
            if guid and len(guid) == 16 and melody:
                guid_map[bytes(guid)] = melody
        return guid_map

    def read_run_info(self) -> tuple[list[Melody], list[int]] | None:
        """Read the current run's three melodies plus a per-slot state.

        Returns ([melody1, melody2, melody3], [state1, state2, state3]) in
        unlock order, or None if not in a run. States:
          0 = not started yet, 1 = being collected (active), 2 = completed
          (the game's own HUD shows completed melodies on the staff).

        The trio comes from the first hero context whose GUID slots resolve.
        States are read from the spawned MelodyEntityCpnt lifecycle field at
        +0x68, reached through the linked-melody arrays of ALL heroes: the
        melodies are group-wide, but in multiplayer a single hero's array can
        lag, so we take the max state across heroes.
        """
        if not self.connected and not self.connect():
            return None
        h = self._handle

        guid_map = self._melody_guid_map()
        if len(guid_map) < 3:
            return None

        heroes = _scan_for_pointer(h, self._base + HERO_VTABLE_RVA)

        melodies = None
        for hero in heroes:
            entity = _read_ptr(h, hero + 0x08)
            ctx = _read_ptr(h, entity + 0x30) if entity else None
            if not ctx:
                continue
            slots = _read_mem(h, ctx + CTX_MELODY_SLOTS_OFFSET, 48)
            if not slots or len(slots) < 48:
                continue
            trio = [guid_map.get(bytes(slots[k * 16:(k + 1) * 16])) for k in range(3)]
            if None not in trio:
                melodies = trio
                break
        if melodies is None:
            return None  # lobby/stale context: slots don't hold melody GUIDs

        states: dict[str, int] = {}
        for hero in heroes:
            arr = _read_mem(h, hero + HERO_MELODY_ARRAY_OFFSET, 12)
            if not arr or len(arr) < 12:
                continue
            arr_ptr, arr_cnt = struct.unpack('<QI', arr)
            if not arr_ptr or not 0 < arr_cnt <= 8:
                continue
            elements = _read_mem(h, arr_ptr, arr_cnt * 8)
            if not elements or len(elements) < arr_cnt * 8:
                continue
            for i in range(arr_cnt):
                cpnt = struct.unpack_from('<Q', elements, i * 8)[0]
                name = _follow_melody_name(h, cpnt) if cpnt else None
                melody = identify(name) if name else None
                if not melody:
                    continue
                raw = _read_mem(h, cpnt + MELODY_STATE_OFFSET, 4)
                if not raw or len(raw) < 4:
                    continue
                state = struct.unpack('<i', raw)[0]
                if not 0 <= state <= 8:
                    continue  # implausible value: misread, ignore
                key = melody.internal_name
                states[key] = max(states.get(key, 0), state)

        return (melodies, [min(states.get(m.internal_name, 0), 2) for m in melodies])

    def read_all_melodies(self) -> list[Melody] | None:
        """Read all three run melodies in unlock order. None if not in a run."""
        info = self.read_run_info()
        return info[0] if info else None

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
