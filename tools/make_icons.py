"""Draw the House Lights logo (houselights/static/icon.svg) as PNG app icons, with plain Python.

    python tools/make_icons.py            # writes icon-192.png and icon-512.png next to icon.svg

The logo: the bulb of the Tabler "bulb" icon (MIT license, tabler.io/icons), amber strokes on a
night-blue rounded square. The shapes here are the same as in icon.svg; keep the two in step.
"""
import math
import os
import struct
import zlib

STATIC = os.path.join(os.path.dirname(__file__), "..", "houselights", "static")
NAVY = (0x1C, 0x25, 0x41)
AMBER = (0xF2, 0xB5, 0x44)
STROKE = 2.0            # in the icon's 24-unit grid, before the 0.8 scale of the bulb
CORNER = 5.0


def arc(p0, p1, r, large, sweep, steps=32):
    """Points along an SVG arc (equal radii, no rotation) from p0 to p1."""
    (x0, y0), (x1, y1) = p0, p1
    mx, my = (x0 - x1) / 2, (y0 - y1) / 2
    d2 = mx * mx + my * my
    r = max(r, math.sqrt(d2))
    k = math.sqrt(max(0.0, (r * r - d2) / d2)) * (1 if large != sweep else -1)
    cx, cy = (x0 + x1) / 2 + k * (my), (y0 + y1) / 2 - k * (mx)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    da = a1 - a0
    if sweep and da < 0:
        da += 2 * math.pi
    if not sweep and da > 0:
        da -= 2 * math.pi
    return [(cx + r * math.cos(a0 + da * i / steps), cy + r * math.sin(a0 + da * i / steps)) for i in range(steps + 1)]


def bulb():
    """The strokes of the bulb as polylines, in the 24-unit grid of the Tabler icon."""
    rays = [[(3, 12), (4, 12)], [(12, 3), (12, 4)], [(20, 12), (21, 12)],
            [(4.6, 5.6), (5.3, 6.3)], [(19.4, 5.6), (18.7, 6.3)]]
    glass = (arc((9, 16), (15, 16), 5, 1, 1) + arc((15, 16), (14, 19), 3.5, 0, 0)[1:]
             + arc((14, 19), (10, 19), 2, 0, 1)[1:] + arc((10, 19), (9, 16), 3.5, 0, 0)[1:])
    return rays + [glass, [(9.7, 17), (14.3, 17)]]


def segments():
    """Line segments in the 24-unit icon grid (the bulb scaled 0.8 about the middle)."""
    out = []
    for line in bulb():
        pts = [(2.4 + 0.8 * x, 2.4 + 0.8 * y) for x, y in line]
        out += list(zip(pts, pts[1:]))
    return out


def dist(px, py, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def render(size):
    unit = size / 24.0
    half = STROKE * 0.8 / 2
    segs = segments()
    rows = []
    for j in range(size):
        row = bytearray()
        y = (j + 0.5) / unit
        for i in range(size):
            x = (i + 0.5) / unit
            # rounded square: coverage from the distance to its edge
            qx, qy = max(abs(x - 12) - (12 - CORNER), 0), max(abs(y - 12) - (12 - CORNER), 0)
            edge = CORNER - math.hypot(qx, qy)
            bg = max(0.0, min(1.0, edge * unit + 0.5))
            d = min(dist(x, y, a, b) for a, b in segs) if 2 < x < 22 and 2 < y < 22 else 99
            fg = max(0.0, min(1.0, (half - d) * unit + 0.5))
            rgb = [round(n * (1 - fg) + a * fg) for n, a in zip(NAVY, AMBER)]
            row += bytes(rgb + [round(255 * bg)])
        rows.append(b"\0" + bytes(row))
    return png(size, b"".join(rows))


def png(size, raw):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    for n in (192, 512):
        path = os.path.join(STATIC, f"icon-{n}.png")
        with open(path, "wb") as f:
            f.write(render(n))
        print("wrote", os.path.normpath(path))
