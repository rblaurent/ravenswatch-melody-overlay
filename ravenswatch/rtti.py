"""RTTI-based vtable discovery for version-resilient game memory reading.

Scans the game binary's .data section for MSVC RTTI TypeDescriptors by class
name, then traces through the Complete Object Locator to find each vtable.
Survives game patches because class names don't change across recompiles.

Chain: TypeDescriptor name string (.data) → COL (.rdata/.data) → vtable (.rdata)
"""

import ctypes
import ctypes.wintypes as wt
import struct

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

RTTI_NAMES = {
    'hero_controller': b'.?AVoCDtEntityCpntHeroController@@\x00',
    'melody_cpnt': b'.?AVMelodyEntityCpnt@dt@oe@@\x00',
    'melody_ui_viewer': b'.?AVMelodyUiViewerEntityCpnt@dt@oe@@\x00',
}

SCAN_CHUNK = 4 * 1024 * 1024


def _read_mem(handle, addr, size):
    buf = ctypes.create_string_buffer(size)
    br = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(br)):
        return buf.raw[:br.value]
    return None


def _parse_pe_sections(handle, base):
    dos = _read_mem(handle, base, 0x40)
    if not dos or dos[:2] != b'MZ':
        return []
    e_lfanew = struct.unpack_from('<I', dos, 0x3c)[0]
    pe_hdr = _read_mem(handle, base + e_lfanew, 0x18)
    if not pe_hdr or pe_hdr[:4] != b'PE\x00\x00':
        return []
    num_sections = struct.unpack_from('<H', pe_hdr, 6)[0]
    opt_size = struct.unpack_from('<H', pe_hdr, 20)[0]
    so = e_lfanew + 0x18 + opt_size
    secs = []
    for i in range(num_sections):
        sd = _read_mem(handle, base + so + i * 40, 40)
        if not sd:
            continue
        name = sd[:8].rstrip(b'\x00').decode('ascii', errors='replace')
        vsize, vaddr = struct.unpack_from('<II', sd, 8)
        secs.append({'name': name, 'vaddr': vaddr, 'vsize': vsize})
    return secs


def _scan_section(handle, base, section, pattern):
    start = base + section['vaddr']
    size = section['vsize']
    results = []
    offset = 0
    overlap = len(pattern)
    while offset < size:
        to_read = min(SCAN_CHUNK, size - offset)
        data = _read_mem(handle, start + offset, to_read)
        if not data:
            offset += SCAN_CHUNK
            continue
        pos = 0
        while True:
            idx = data.find(pattern, pos)
            if idx == -1:
                break
            results.append(start + offset + idx)
            pos = idx + 1
        offset += SCAN_CHUNK - overlap
    return results


def _resolve_one_vtable(handle, base, data_sec, search_sections, rtti_name_bytes):
    """Resolve a single vtable from its RTTI name. Returns RVA or None."""
    td_name_hits = _scan_section(handle, base, data_sec, rtti_name_bytes)
    if not td_name_hits:
        return None

    td_addr = td_name_hits[0] - 0x10
    td_rva = td_addr - base
    td_rva_bytes = struct.pack('<I', td_rva & 0xFFFFFFFF)

    for sec in search_sections:
        refs = _scan_section(handle, base, sec, td_rva_bytes)
        for ref_addr in refs:
            col_addr = ref_addr - 0x0c
            col_data = _read_mem(handle, col_addr, 0x18)
            if not col_data:
                continue
            sig = struct.unpack_from('<I', col_data, 0)[0]
            self_rva = struct.unpack_from('<I', col_data, 0x14)[0]
            if sig != 1 or (base + self_rva) != col_addr:
                continue

            col_ptr = struct.pack('<Q', col_addr)
            for sec2 in search_sections:
                vt_refs = _scan_section(handle, base, sec2, col_ptr)
                if vt_refs:
                    return (vt_refs[0] + 8) - base
    return None


def resolve_vtables(handle, base):
    """Resolve vtable RVAs for all target classes using MSVC RTTI.

    Returns dict: {'hero_controller': int|None, 'melody_cpnt': int|None, ...}
    """
    sections = _parse_pe_sections(handle, base)
    data_sec = next((s for s in sections if s['name'] == '.data'), None)
    rdata_sec = next((s for s in sections if s['name'] == '.rdata'), None)
    if not data_sec or not rdata_sec:
        return {k: None for k in RTTI_NAMES}

    search_sections = [rdata_sec, data_sec]
    return {
        key: _resolve_one_vtable(handle, base, data_sec, search_sections, name)
        for key, name in RTTI_NAMES.items()
    }


def find_melody_registry(handle, base, melody_cpnt_vtable_rva):
    """Find the static registry of 12 base MelodyEntityCpnt instances.

    Scans .data for a {ptr:8, count:4} where count is 10-14 and the ptr
    leads to an array of pointers to objects with the MelodyEntityCpnt vtable.
    Returns the registry RVA, or None.
    """
    sections = _parse_pe_sections(handle, base)
    data_sec = next((s for s in sections if s['name'] == '.data'), None)
    if not data_sec:
        return None

    vtable_abs = base + melody_cpnt_vtable_rva
    data_start = base + data_sec['vaddr']
    data_size = data_sec['vsize']

    offset = 0
    while offset < data_size:
        to_read = min(SCAN_CHUNK, data_size - offset)
        data = _read_mem(handle, data_start + offset, to_read)
        if not data:
            offset += SCAN_CHUNK
            continue

        for i in range(0, len(data) - 12, 8):
            ptr = struct.unpack_from('<Q', data, i)[0]
            count = struct.unpack_from('<I', data, i + 8)[0]

            if not (10 <= count <= 14) or ptr < 0x10000 or ptr > 0x7fffffffffff:
                continue

            arr = _read_mem(handle, ptr, count * 8)
            if not arr or len(arr) < count * 8:
                continue

            matches = 0
            for j in range(count):
                entry = struct.unpack_from('<Q', arr, j * 8)[0]
                if entry < 0x10000:
                    break
                vt = _read_mem(handle, entry, 8)
                if vt and struct.unpack_from('<Q', vt)[0] == vtable_abs:
                    matches += 1

            if matches >= 10:
                return (data_start + offset + i) - base

        offset += SCAN_CHUNK - 16
    return None
