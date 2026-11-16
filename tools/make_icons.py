"""Draw the app icons (a row of coloured lights under a roofline) with the standard library only.

    python tools/make_icons.py      -> houselights/static/icon-192.png, icon-512.png
"""
import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "houselights", "static")
BG, ROOF = (43, 46, 51), (90, 96, 106)
COLORS = [(255, 138, 28), (255, 200, 80), (255, 255, 255), (0, 160, 0), (224, 0, 122), (64, 160, 255)]


def png(path, w, h, px):
    raw = b"".join(b"\x00" + bytes(v for x in range(w) for v in px(x, y)) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def icon(size):
    s = size / 512

    def px(x, y):
        X, Y = x / s, y / s
        c = BG
        # roof: an inverted V from (96, 300) up to (256, 150) and down to (416, 300)
        if 96 <= X <= 416 and abs(Y - (150 + abs(X - 256) * 150 / 160)) < 10:
            c = ROOF
        # lights along the eave at y = 340
        for k, col in enumerate(COLORS):
            cx = 116 + k * 56
            d = math.hypot(X - cx, Y - 340)
            if d < 20:
                return col
            if d < 40:
                g = (40 - d) / 20 * 0.35
                c = tuple(round(c[j] + (col[j] - c[j]) * g) for j in range(3))
        return c
    return px


for size in (192, 512):
    png(os.path.join(OUT, f"icon-{size}.png"), size, size, icon(size))
    print("wrote", os.path.join(OUT, f"icon-{size}.png"))
