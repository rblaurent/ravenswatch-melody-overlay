"""Batch-convert DarkTales .tpi melody icons to PNG with deciphered names."""
from pathlib import Path

from tpi_decode import decode_tpi

# DarkTales cooked-name substitution cipher (cipher char -> plain char),
# derived from known strings: Hqlrtdqv=Melodies, Qqpiwuq=Texture, jzy=png,
# Kglgngt=Galahad, HquusHqz=MerryMen, GrzyErnzFdlkqu=LongJohnSilver, ...
DECODE_LOWER = {
    'a': 'b', 'b': 'c', 'd': 'i', 'e': 'z', 'g': 'a', 'h': 'f', 'i': 't',
    'j': 'p', 'k': 'v', 'l': 'l', 'm': 'k', 'n': 'h', 'p': 'x', 'q': 'e',
    'r': 'o', 's': 'y', 't': 'd', 'u': 'r', 'v': 's', 'w': 'u', 'x': 'm',
    'y': 'g', 'z': 'n',
}
DECODE_UPPER = {
    'A': 'H', 'E': 'J', 'F': 'S', 'G': 'L', 'H': 'M', 'J': 'U', 'K': 'G',
    'O': 'O', 'Q': 'T', 'X': 'I',
}

def decipher(name):
    out = []
    for ch in name:
        if ch in DECODE_LOWER:
            out.append(DECODE_LOWER[ch])
        elif ch in DECODE_UPPER:
            out.append(DECODE_UPPER[ch])
        elif ch.isalpha():
            out.append('?')  # unmapped letter — surface it
        else:
            out.append(ch)
    return ''.join(out)

SRC = Path(r"G:\SteamLibrary\steamapps\common\Ravenswatch\DarkTalesResources\_Cooking\Jd\Hqlrtdqv")
OUT = Path(r"T:\Projects\gdq\ravenswatch\icons")
TEMP = Path(r"T:\Projects\nova\nova-workspace\memory\temp")
OUT.mkdir(exist_ok=True)

for f in sorted(SRC.glob("*.tpi")):
    plain = decipher(f.name)
    # "UI_Melody_Icon_Galahad.png.Texture.tpi" -> "UI_Melody_Icon_Galahad.png"
    base = plain.split('.')[0] + ".png"
    img = decode_tpi(f)
    img.save(OUT / base)
    img.save(TEMP / base)
    print(f"{f.name}  ->  {base}  {img.size}")
