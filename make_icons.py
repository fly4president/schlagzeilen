"""Erzeugt die App-Icons (blaues Feld mit stilisierten Schlagzeilen-Zeilen) ohne Zusatzpakete."""
import struct
import zlib
from pathlib import Path

BG = (29, 92, 134)
FG = (243, 245, 247)
SOFT = (150, 190, 218)


def make(size):
    s = size / 512
    # Rechtecke (x0, y0, x1, y1, farbe) im 512er-Raster, mittig in der sicheren Zone
    bars = [
        (136, 150, 376, 196, FG),   # dicke Schlagzeile
        (136, 220, 330, 262, FG),
        (136, 300, 376, 318, SOFT),  # Textzeilen
        (136, 336, 376, 354, SOFT),
        (136, 372, 290, 390, SOFT),
    ]
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            c = BG
            for x0, y0, x1, y1, col in bars:
                if x0 * s <= x < x1 * s and y0 * s <= y < y1 * s:
                    c = col
                    break
            row += bytes(c)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


out = Path(__file__).resolve().parent / "docs"
for n in (192, 512):
    (out / f"icon-{n}.png").write_bytes(make(n))
print("Icons erstellt")
