"""Decode DarkTales .tpi textures (serialized oCTexture).

Layout (melody icons / format enum 5 = BC3 a.k.a. DXT5):
  - 193-byte serialized header: width uint32 @137, height uint32 @141,
    format enum uint32 @149 (5 = BC3), pixel data size uint32 @153 (dup @157)
  - pixel data: standard BC3 blocks, row-major 4x4
  - 7-byte serialization footer (ends with the aa bb 22 22 end-of-object tag)

NOTE: earlier attempts assumed data at offset 200 (65736 - 65536) and got
shape-correct but color-garbage decodes — the real offset is 193.
"""
import struct
import sys
from pathlib import Path

import texture2ddecoder
from PIL import Image

FOOTER = 7


def decode_tpi(path):
    data = Path(path).read_bytes()
    w = struct.unpack_from('<I', data, 137)[0]
    h = struct.unpack_from('<I', data, 141)[0]
    fmt = struct.unpack_from('<I', data, 149)[0]
    size = struct.unpack_from('<I', data, 153)[0]
    expected = ((w + 3) // 4) * ((h + 3) // 4) * 16
    assert fmt == 5, f"{path}: unhandled format enum {fmt} (only 5=BC3 known)"
    assert size == expected, f"{path}: size {size} != expected {expected} for {w}x{h}"
    # anchor from the end: header length is 193 for these files, but this
    # survives header-size variations as long as the 7-byte footer holds
    px = data[len(data) - FOOTER - size:len(data) - FOOTER]
    bgra = texture2ddecoder.decode_bc3(px, w, h)
    return Image.frombytes("RGBA", (w, h), bgra, "raw", "BGRA")


if __name__ == "__main__":
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    data = src.read_bytes()
    print("file size:", len(data))
    print("last 24 bytes:", ' '.join(f'{b:02x}' for b in data[-24:]))
    img = decode_tpi(src)
    img.save(out)
    print("saved", out, img.size)
