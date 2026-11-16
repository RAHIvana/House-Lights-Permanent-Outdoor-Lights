"""Patterns render one colour per *light*.

Static patterns are applied as segment colours (quantise(); 5 lights per segment on
Govee H806A) or streamed per light. Animated patterns are functions of time t (seconds)
and are only sent by streaming one colour per light.

Every animated pattern is stateless: colour(i, t) depends only on its inputs, so the
browser preview (frames computed here) and the live stream look the same.
"""
import colorsys
import math
import random

RGB = tuple  # (r, g, b)


def hex_to_rgb(h):
    h = h.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"bad colour {h!r}")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def _colors(param):
    return [hex_to_rgb(c) for c in str(param).split(",") if c.strip()]


def _bands(n, colors, width):
    width = max(1, int(width))
    return [colors[(i // width) % len(colors)] for i in range(n)]


# --- helpers for animation --------------------------------------------------------------
def _h(i, k, seed=0):
    """Deterministic hash of (light, time step, seed) -> [0, 1)."""
    x = (i * 0x9E3779B1 ^ (k & 0xFFFFFFFF) * 0x85EBCA77 ^ seed * 0xC2B2AE3D) & 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= x >> 16
    return x / 4294967296.0


def _smooth(i, t, rate, seed=0):
    """Smooth per-light noise in [0, 1) that changes `rate` times per second."""
    k = t * rate
    k0 = math.floor(k)
    f = k - k0
    f = f * f * (3 - 2 * f)
    return _h(i, k0, seed) * (1 - f) + _h(i, k0 + 1, seed) * f


def _mix(a, b, f):
    f = max(0.0, min(1.0, f))
    return tuple(round(a[j] + (b[j] - a[j]) * f) for j in range(3))


def _scale(c, f):
    f = max(0.0, min(1.0, f))
    return tuple(round(v * f) for v in c)


def _add(a, b):
    return tuple(min(255, a[j] + b[j]) for j in range(3))


def _hsv(h, s=1.0, v=1.0):
    return tuple(round(x * 255) for x in colorsys.hsv_to_rgb(h % 1.0, s, v))


WHITE = (255, 255, 255)
GOLD = (255, 200, 80)
SAFFRON, INDIA_WHITE, INDIA_GREEN = (255, 106, 0), (255, 255, 255), (0, 160, 0)


# --- static patterns: fn(n, seg_width, params) -> [rgb] ---------------------------------
def _christmas(n, width, white_ends):
    out = _bands(n, [hex_to_rgb("#ff0000"), hex_to_rgb("#00a000")], width)
    if white_ends:
        for i in list(range(min(width, n))) + list(range(max(0, n - width), n)):
            out[i] = WHITE
    return out


def _gradient(n, a, b):
    return [tuple(round(a[k] + (b[k] - a[k]) * (i / max(1, n - 1))) for k in range(3)) for i in range(n)]


def _random(n, colors, width, seed):
    rnd = random.Random(int(seed))
    width = max(1, int(width))
    picks = [rnd.choice(colors) for _ in range((n + width - 1) // width)]
    return [picks[i // width] for i in range(n)]


# --- animated patterns: fn(n, t, params) -> [rgb] ---------------------------------------
def _diya_glow(n, t, p):
    """Candle flames: amber base, each light flickering on its own, slow golden flares."""
    base, speed = hex_to_rgb(p["color"]), p["speed"]
    out = []
    for i in range(n):
        flick = 0.5 + 0.5 * _smooth(i, t, 7 * speed, 1) * (0.6 + 0.4 * _smooth(i, t, 1.1 * speed, 2))
        slot = math.floor(t * 0.4 * speed)
        flare = 0.0
        if _h(i // 3, slot, 3) > 0.88:                    # a few groups flare per slot
            ph = t * 0.4 * speed - slot
            flare = math.sin(math.pi * ph) ** 2
        out.append(_scale(_mix(base, GOLD, flare), flick + 0.35 * flare))
    return out


def _rangoli_chase(n, t, p):
    """Rangoli colours in bands sliding along the roofline with soft edges."""
    pal, width, speed = _colors(p["colors"]), max(1, p["width"]), p["speed"]
    out = []
    for i in range(n):
        pos = (i - t * speed) / width
        k = math.floor(pos)
        f = pos - k
        c1, c2 = pal[k % len(pal)], pal[(k + 1) % len(pal)]
        col = _mix(c1, c2, (f - 0.75) / 0.25) if f > 0.75 else c1
        out.append(_scale(col, 0.85 + 0.15 * math.sin(2 * math.pi * (t * 0.7 + i / 9))))
    return out


def _anar_fireworks(n, t, p):
    """Anar / sky-shot bursts: a white flash, then a coloured ring racing outwards and fading."""
    pal = _colors(p["colors"])
    every, life, speed = 1.0 / max(0.1, p["rate"]), 1.8, 14.0
    bg = (26, 8, 0)
    out = [bg] * n
    now = math.floor(t / every)
    for s in range(now - 2, now + 1):
        for b in range(2):
            if _h(b, s, 10) < 0.35 and b == 1:          # sometimes only one burst per slot
                continue
            t0 = (s + _h(b, s, 11)) * every
            age = t - t0
            if not 0 <= age < life:
                continue
            c = _h(b, s, 12) * n
            col = pal[int(_h(b, s, 13) * len(pal)) % len(pal)]
            fade = (1 - age / life) ** 1.6
            front = age * speed
            for i in range(max(0, int(c - front - 4)), min(n, int(c + front + 5))):
                d = abs(i - c)
                ring = math.exp(-((front - d) / 2.5) ** 2) + 0.35 * max(0.0, 1 - d / max(front, 1))
                spark = 0.55 + 0.45 * _h(i, math.floor(t * 25), s * 7 + b)
                glow = _scale(col, fade * ring * spark)
                if age < 0.15 and d < 3:
                    glow = _add(glow, _scale(WHITE, 1 - age / 0.15))
                out[i] = _add(out[i], glow)
    return out


def _phuljhadi(n, t, p):
    """Sparklers: dim warm gold, with bright white and gold sparks popping everywhere."""
    base, density, rate = hex_to_rgb(p["color"]), p["density"], 12.0
    out = []
    for i in range(n):
        k = math.floor(t * rate)
        col = _scale(base, 0.28 + 0.07 * _smooth(i, t, 2, 4))
        for back in range(3):                             # sparks decay over three steps
            if _h(i, k - back, 21) < density:
                f = (1 - (t * rate - k)) if back == 0 else 0.5 ** (back + (t * rate - k))
                spark = WHITE if _h(i, k - back, 22) < 0.5 else GOLD
                col = _add(col, _scale(spark, f))
        out.append(col)
    return out


def _lakshmi_wave(n, t, p):
    """Golden waves rolling along the house, with white glints on each crest."""
    a, b = hex_to_rgb("#ff5a00"), hex_to_rgb("#ffd060")
    wl, speed = max(4, p["wavelength"]), p["speed"]
    out = []
    for i in range(n):
        w = 0.5 + 0.5 * math.sin(2 * math.pi * (i / wl - t * speed / wl))
        col = _scale(_mix(a, b, w), 0.3 + 0.7 * w)
        if w > 0.94 and _h(i, math.floor(t * 8), 31) > 0.4:
            col = _mix(col, WHITE, (w - 0.94) / 0.06)
        out.append(col)
    return out


def _deepavali_rainbow(n, t, p):
    """A slow rainbow flowing along the run with a gentle shimmer."""
    spread, speed = p["spread"], p["speed"]
    return [_scale(_hsv(i / max(1, n) * spread - t * speed * 0.05), 0.75 + 0.25 * _smooth(i, t, 3, 5))
            for i in range(n)]


def _candy_cane(n, t, p):
    """Red and white stripes marching along the roofline."""
    width, speed = max(1, p["width"]), p["speed"]
    return [(255, 0, 0) if math.floor((i - t * speed) / width) % 2 == 0 else WHITE for i in range(n)]


def _twinkle_tree(n, t, p):
    """Evergreen base with red, gold and white ornaments twinkling on and off."""
    green, orn = (0, 110, 20), [(255, 0, 0), GOLD, WHITE]
    out = []
    for i in range(n):
        tw = _smooth(i, t, 1.5 * p["speed"], 41)
        if tw > 0.62:
            out.append(_mix(green, orn[int(_h(i, 0, 42) * 3) % 3], (tw - 0.62) / 0.38))
        else:
            out.append(_scale(green, 0.6 + 0.4 * tw))
    return out


def _tiranga_wave(n, t, p):
    """Tricolour (saffron, white, green) with a waving-flag ripple."""
    out = []
    for i in range(n):
        c = SAFFRON if i < n / 3 else INDIA_WHITE if i < 2 * n / 3 else INDIA_GREEN
        out.append(_scale(c, 0.55 + 0.45 * (0.5 + 0.5 * math.sin(2 * math.pi * (i / 14 - t * 0.6 * p["speed"])))))
    return out


def _breathe(n, t, p):
    """One colour slowly breathing in and out."""
    c = hex_to_rgb(p["color"])
    return [_scale(c, 0.15 + 0.85 * (0.5 - 0.5 * math.cos(2 * math.pi * t * 0.25 * p["speed"])))] * n


# --- shared effects: most holiday themes are one of these with its own colours
def _twinkle(n, t, p):
    """Base colours in segment-wide bands; some lights rise to an accent colour and fade back."""
    base, acc, dens, speed, level = _colors(p["colors"]), _colors(p["accents"]), p["density"], p["speed"], p["level"]
    thr = 1 - max(0.02, min(0.9, dens))
    out = []
    for i in range(n):
        c = _scale(base[(i // 5) % len(base)], level * (0.85 + 0.15 * _smooth(i, t, 0.7 * speed, 50)))
        tw = _smooth(i, t, 1.2 * speed, 51)
        if tw > thr:
            a = acc[int(_h(i, math.floor(t * 0.3 * speed), 52) * len(acc)) % len(acc)]
            c = _mix(c, a, ((tw - thr) / (1 - thr)) ** 0.7)
        out.append(c)
    return out


def _drift(n, t, p):
    """Things moving along the run over a background: snowflakes, leaves, kites, lanterns
    (speed 0 = they stay put and sway), or one comet with a trail (a sleigh)."""
    pal, bg = _colors(p["colors"]), hex_to_rgb(p["bg"])
    size, trail, sway = max(0.3, p["size"]), max(0, int(p["trail"])), p["sway"]
    out = [_scale(bg, 0.8 + 0.2 * _smooth(i, t, 0.5, 60)) for i in range(n)]
    k = max(1, round(p["count"] * n / 50))
    span = n + 2 * size + trail + 2
    for m in range(k):
        sp = p["speed"] * (0.55 + 0.9 * _h(m, 0, 61))
        center = (_h(m, 0, 62) * span + t * sp) % span - size - 1 + sway * math.sin(t * (0.8 + _h(m, 0, 63)) + m)
        col = pal[m % len(pal)]
        glow = 0.75 + 0.25 * math.sin(t * 3 + m * 1.7)
        for i in range(max(0, int(center - size - 1)), min(n, int(center + size + 2))):
            out[i] = _mix(out[i], col, glow * max(0.0, 1 - abs(i - center) / (size + 0.5)))
        for j in range(1, trail + 1):
            i = int(center) - j if sp >= 0 else int(center) + j
            if 0 <= i < n:
                out[i] = _mix(out[i], col, 0.7 * (1 - j / (trail + 1)) * (0.6 + 0.4 * _h(i, math.floor(t * 20), 64)))
    return out


def _bursts(n, t, p):
    """Bursts at random points: an optional white flash, then a ring spreading out and fading."""
    pal, bg = _colors(p["colors"]), hex_to_rgb(p["bg"])
    every, life, speed = 1.0 / max(0.1, p["rate"]), max(0.5, p["life"]), max(1.0, p["spread"])
    out = [bg] * n
    now = math.floor(t / every)
    for s in range(now - int(life / every) - 1, now + 1):
        for b in range(2):
            if b == 1 and _h(b, s, 70) < 0.4:
                continue
            age = t - (s + _h(b, s, 71)) * every
            if not 0 <= age < life:
                continue
            c, col = _h(b, s, 72) * n, pal[int(_h(b, s, 73) * len(pal)) % len(pal)]
            fade, front = (1 - age / life) ** 1.4, age * speed
            for i in range(max(0, int(c - front - 4)), min(n, int(c + front + 5))):
                d = abs(i - c)
                ring = math.exp(-((front - d) / 2.5) ** 2) + 0.4 * max(0.0, 1 - d / max(front, 1))
                glow = _scale(col, fade * min(1.0, ring) * (0.6 + 0.4 * _h(i, math.floor(t * 20), s)))
                if p["flash"] and age < 0.15 and d < 3:
                    glow = _add(glow, _scale(WHITE, 1 - age / 0.15))
                out[i] = _add(out[i], glow)
    return out


_FIRE = [(0.0, (20, 0, 0)), (0.35, (170, 20, 0)), (0.6, (255, 80, 0)), (0.85, (255, 160, 20)), (1.0, (255, 220, 120))]


def _fire(n, t, p):
    """Flames: heat from fast and slow noise, coloured dark red -> orange -> yellow."""
    out = []
    for i in range(n):
        h = 0.55 * _smooth(i, t, 7 * p["speed"], 75) + 0.45 * _smooth(i // 4, t, 1.6 * p["speed"], 76)
        h = max(0.0, min(1.0, (h - 0.15) / 0.8))
        for (a, ca), (b, cb) in zip(_FIRE, _FIRE[1:]):
            if h <= b:
                out.append(_mix(ca, cb, (h - a) / (b - a)))
                break
    return out


def _swirl(n, t, p):
    """Colours from a palette blending slowly into each other along the run."""
    pal, speed = _colors(p["colors"]), p["speed"]
    out = []
    for i in range(n):
        v = _smooth(i // 2, t, 0.6 * speed, 80) * (len(pal) - 1)
        k = min(int(v), len(pal) - 2) if len(pal) > 1 else 0
        c = _mix(pal[k], pal[min(k + 1, len(pal) - 1)], v - k)
        out.append(_scale(c, 0.6 + 0.4 * _smooth(i, t, 1.5 * speed, 81)))
    return out


def _steps(n, t, p):
    """The whole run steps through a palette, holding each colour, with a soft cross-fade."""
    pal, hold = _colors(p["colors"]), max(0.5, p["hold"])
    k = math.floor(t / hold)
    f = (t / hold - k)
    f = 0.0 if f < 0.8 else (f - 0.8) / 0.2
    c = _mix(pal[k % len(pal)], pal[(k + 1) % len(pal)], f * f * (3 - 2 * f))
    return [_scale(c, 0.8 + 0.2 * math.sin(2 * math.pi * (i / 16 - t * 0.3))) for i in range(n)]


def _glide(n, t, p):
    """Bands of `width` lights in palette order, sliding along the run at `speed` lights/s
    (negative = the other way). `soft` (0-1) is how much of each band blends into the next:
    small widths give soft stripes, large widths give slow waves of colour. `blink` (0-1): coloured lights flicker like diya
    flames, white lights shimmer slowly like light on water."""
    pal, w, speed = _colors(p["colors"]), max(0.5, p["width"]), p["speed"]
    soft, blink = max(0.0, min(1.0, p["soft"])), max(0.0, min(1.0, p["blink"]))
    out = []
    for i in range(n):
        pos = (i - t * speed) / w
        k = math.floor(pos)
        f = pos - k
        c = pal[k % len(pal)]
        if soft > 0 and f > 1 - soft:
            g = (f - (1 - soft)) / soft
            c = _mix(c, pal[(k + 1) % len(pal)], g * g * (3 - 2 * g))
        if blink:
            hi = max(c)
            sat = (hi - min(c)) / hi if hi else 0.0
            flame = 0.35 + 0.65 * _smooth(i, t, 7, 90) * (0.6 + 0.4 * _smooth(i, t, 1.1, 91))
            water = 0.6 + 0.4 * _smooth(i, t, 1.5, 92)
            c = _scale(c, 1 - blink * (1 - (sat * flame + (1 - sat) * water)))
        out.append(c)
    return out


def _rhythm(n, t, p):
    """Dance beat: on every beat the colours step one group along and flash, then ease off."""
    pal, width, bpm = _colors(p["colors"]), max(1, p["width"]), max(30.0, p["bpm"])
    beat = t * bpm / 60
    k, ph = math.floor(beat), beat - math.floor(beat)
    env = 0.45 + 0.55 * math.exp(-ph * 4)
    return [_scale(pal[(i // width + k) % len(pal)], env) for i in range(n)]


def _heartbeat(n, t, p):
    """A double pulse (lub-dub) from a soft base colour to a strong one."""
    base, beat_c = hex_to_rgb(p["color"]), hex_to_rgb(p["beat"])
    ph = (t * p["bpm"] / 60) % 1
    env = math.exp(-(ph / 0.07) ** 2) + 0.75 * math.exp(-((ph - 0.22) / 0.07) ** 2)
    return [_mix(_scale(base, 0.45), beat_c, min(1.0, env) * (0.85 + 0.15 * math.sin(i / 3))) for i in range(n)]


def _storm(n, t, p):
    """Dim stormy colour; now and then lightning flashes white over part of the house."""
    base, rate = hex_to_rgb(p["color"]), max(0.05, p["rate"])
    out = [_scale(base, 0.3 + 0.15 * _smooth(i // 3, t, 0.6, 90)) for i in range(n)]
    slot = math.floor(t * rate)
    for s in (slot - 1, slot):
        if _h(0, s, 91) > 0.65:
            continue
        age = t - (s + 0.7 * _h(1, s, 92)) / rate
        env = 1.0 if 0 <= age < 0.07 else 0.7 if 0.15 <= age < 0.22 else (0.35 * max(0.0, 1 - (age - 0.22) / 0.5) if age >= 0.22 else 0)
        if env <= 0:
            continue
        start, length = _h(2, s, 93) * n, n * (0.25 + 0.5 * _h(3, s, 94))
        for i in range(n):
            if (i - start) % n < length:
                out[i] = _mix(out[i], WHITE, env)
    return out


def _haunted(n, t, p):
    """A failing bulb: the colour flickers, groups stutter and black out, sometimes all of it."""
    c, k = hex_to_rgb(p["color"]), math.floor(t * 7)
    dip = 0.25 if _h(0, math.floor(t * 2), 95) > 0.93 else 1.0          # rare whole-house brown-out
    out = []
    for i in range(n):
        g = _h(i // 5, k, 96)
        lvl = 0.03 if g < 0.07 else 0.35 if g < 0.18 else 0.8 + 0.2 * _smooth(i, t, 9, 97)
        out.append(_scale(c, lvl * dip))
    return out


def _candles(n, t, p):
    """Birthday: one candle flame per year (spread along the run, up to one per light), over
    slowly twinkling party colours. Every ~15 s they're blown out, confetti, and relit."""
    pal, age = _colors(p["colors"]), max(1, min(n, int(p["age"])))
    flame = (255, 150, 40)
    cyc = t % 15
    out = []
    candles = {round((j + 0.5) * n / age - 0.5) for j in range(age)}
    for i in range(n):
        c = _scale(pal[(i // 3) % len(pal)], 0.25 + 0.2 * _smooth(i, t, 1.0, 98))
        if i in candles:
            c = _mix(c, flame, 0.75 + 0.25 * _smooth(i, t, 8, 99))
        if 12 <= cyc < 13.2 and i in candles:                     # blown out
            c = _scale(c, 0.1)
        elif 13.2 <= cyc < 15:                                    # confetti
            if _h(i, math.floor(t * 12), 100) < 0.35:
                c = _add(c, pal[int(_h(i, math.floor(t * 12), 101) * len(pal)) % len(pal)])
        out.append(c)
    return out


def _gameday(n, t, p):
    """Team colours chasing along the house with white sparkles."""
    pal, width, speed = _colors(p["colors"]), max(1, p["width"]), p["speed"]
    out = []
    for i in range(n):
        c = pal[math.floor((i - t * speed) / width) % len(pal)]
        if _h(i, math.floor(t * 10), 102) < 0.05:
            c = _mix(c, WHITE, 0.8)
        out.append(c)
    return out


def _chakra(n, t, p):
    """Tricolour, with a navy-blue chakra pulse travelling through the white band."""
    out = []
    lo, hi = n / 3, 2 * n / 3
    pos = lo + (hi - lo) * (0.5 + 0.5 * math.sin(t * 0.8 * p["speed"]))
    for i in range(n):
        c = SAFFRON if i < lo else INDIA_WHITE if i < hi else INDIA_GREEN
        c = _scale(c, 0.8 + 0.2 * math.sin(2 * math.pi * (i / 14 - t * 0.4)))
        if lo <= i < hi:
            c = _mix(c, (20, 30, 200), max(0.0, 1 - abs(i - pos) / 2.5))
        out.append(c)
    return out


US_RED, US_WHITE, US_BLUE = (220, 0, 20), (255, 255, 255), (20, 40, 200)


def _stars_stripes(n, t, p):
    """US flag along the run: a blue field with twinkling white stars, then red and white
    stripes, all rippling like a flag in the wind (t = 0 gives the still flag)."""
    field, width = max(1, n // 4), max(1, p["width"])
    out = []
    for i in range(n):
        if i < field:
            c = US_WHITE if (i % 3 == 1 and (t == 0 or _smooth(i, t, 2, 103) > 0.35)) else US_BLUE
        else:
            c = US_RED if ((i - field) // width) % 2 == 0 else US_WHITE
        if t:
            c = _scale(c, 0.6 + 0.4 * (0.5 + 0.5 * math.sin(2 * math.pi * (i / 16 - t * 0.5 * p["speed"]))))
        out.append(c)
    return out


# --- registry ---------------------------------------------------------------------------
RANGOLI = "#e0007a,#ff7a00,#ffd000,#00b050,#0060ff,#8a2be2"
FIREWORK = "#ffc850,#ff3030,#30ff60,#ff40ff,#40a0ff,#ffffff"

# Quick Settings' category pull-down, in this order. A theme can be in several; its first
# category groups it in the theme lists.
CATEGORIES = ["Everyday", "Diwali", "Hindu festivals", "India", "Christmas", "Halloween", "Thanksgiving",
              "USA", "More US holidays", "Celebration", "School spirit"]


def _hx(*cols):
    return ",".join(rgb_to_hex(c) for c in cols)


def _bands_fn(n, w, p):
    return _bands(n, _colors(p["colors"]), p["width"] or w)


def S(label, cats, colors, describe="", tile=True):
    """Static theme: colour bands, one segment (5 lights) each unless width is set."""
    return dict(label=label, cats=cats, params={"colors": ("colors", colors), "width": ("int", 0)},
                fn=_bands_fn, face=colors, describe=describe, tile=tile)


def A(label, cats, fn, params, face, describe, tile=True):
    """Animated theme (played live, light by light)."""
    return dict(label=label, cats=cats, animated=True, fn=fn, params=params, face=face, describe=describe, tile=tile)


def TW(colors, accents, density=0.25, speed=1.0, level=0.6):
    return {"colors": ("colors", colors), "accents": ("colors", accents), "density": ("float", density),
            "speed": ("float", speed), "level": ("float", level)}


def DR(colors, bg, count=6.0, speed=3.0, size=1.0, trail=0, sway=1.5):
    return {"colors": ("colors", colors), "bg": ("color", bg), "count": ("float", count), "speed": ("float", speed),
            "size": ("float", size), "trail": ("int", trail), "sway": ("float", sway)}


def BU(colors, bg, rate=1.2, spread=14.0, life=1.8, flash=True):
    return {"colors": ("colors", colors), "bg": ("color", bg), "rate": ("float", rate), "spread": ("float", spread),
            "life": ("float", life), "flash": ("bool", flash)}


def SWP(colors, speed=1.0):
    return {"colors": ("colors", colors), "speed": ("float", speed)}


def GL(colors, width, speed, soft, blink=0.0):
    return {"colors": ("colors", colors), "width": ("float", width), "speed": ("float", speed), "soft": ("float", soft),
            "blink": ("float", blink)}


def CAND(age, colors):
    return {"age": ("int", age), "colors": ("colors", colors)}


# LED-friendly school colours: very dark shades (maroon) are lifted so they read as colour.
UT_ORANGE, AGGIE_MAROON, UTD_ORANGE, UTD_GREEN = (204, 85, 0), (150, 0, 25), (232, 117, 0), (0, 120, 55)
ASU_MAROON, ASU_GOLD = (150, 20, 65), (255, 198, 39)

# id -> dict(label, cats, animated, params {name: (type, default)}, fn, face, describe, tile)
# describe: text for Govee's AI mode. face: tile colours. tile=False: in the theme lists
# but not a Quick Settings tile (tools that need you to pick colours first).
PATTERNS = {
    # --- Everyday ---
    "warm_gold": dict(label="Warm gold", cats=["Everyday", "Diwali"], params={}, face="#ffb040,#ffb040",
                      fn=lambda n, w, p: [hex_to_rgb("#ffb040")] * n),
    "candlelight": A("Candlelight", ["Everyday"], _diya_glow, {"color": ("color", "#ff9a3c"), "speed": ("float", 0.5)},
                     "#ffb46b,#ff9a3c,#ffb46b", "Dynamic. Warm white candlelight with a barely-there flicker."),
    "moonlight": A("Moonlight", ["Everyday"], _swirl, SWP(_hx((90, 110, 190), (170, 190, 255), (120, 140, 220)), 0.3),
                   "#5a6ebe,#aabeff,#788cdc", "Dynamic. Cool soft moonlight, slowly shifting."),
    "breathe": A("Breathing color", ["Everyday", "Celebration"], _breathe,
                 {"color": ("color", "#ff8a1c"), "speed": ("float", 1.0)}, "#3a1a00,#ff8a1c,#3a1a00",
                 "Dynamic. One color slowly fading in and out, about every 4 seconds.", tile=False),
    "solid": dict(label="Solid color", cats=["Everyday"], params={"color": ("color", "#ffb347")}, face="#ffb347,#ffb347",
                  fn=lambda n, w, p: [hex_to_rgb(p["color"])] * n, tile=False),
    "alternating": dict(label="Alternating", cats=["Everyday"], params={"colors": ("colors", "#ff0000,#0000ff"), "width": ("int", 0)},
                        fn=_bands_fn, face="#ff0000,#0000ff", tile=False),
    "gradient": dict(label="Gradient", cats=["Everyday"], params={"from": ("color", "#ff0000"), "to": ("color", "#0000ff")},
                     fn=lambda n, w, p: _gradient(n, hex_to_rgb(p["from"]), hex_to_rgb(p["to"])), face="#ff0000,#0000ff", tile=False),
    "random": dict(label="Random from palette", cats=["Everyday"],
                   params={"colors": ("colors", "#ff0000,#00a000,#ffffff,#ffb000"), "width": ("int", 0), "seed": ("int", 1)},
                   fn=lambda n, w, p: _random(n, _colors(p["colors"]), p["width"] or w, p["seed"]),
                   face="#ff0000,#00a000,#ffffff,#ffb000", tile=False),

    # --- Diwali ---
    "diya_glow": A("Diya glow", ["Diwali"], _diya_glow, {"color": ("color", "#ff8a1c"), "speed": ("float", 1.0)},
                   "#ff8a1c,#ffc850,#ff6a00", "Dynamic. Warm amber diya flames: every light flickers independently like a "
                   "candle, with slow golden flares drifting along the roofline."),
    "rangoli_chase": A("Rangoli chase", ["Diwali"], _rangoli_chase,
                       {"colors": ("colors", RANGOLI), "width": ("int", 5), "speed": ("float", 6.0)},
                       "#e0007a,#ff7a00,#ffd000,#00b050,#0060ff", "Dynamic. Bands of magenta, orange, yellow, green, blue "
                       "and purple, 5 lights each, chasing smoothly along the strip with soft blended edges."),
    "anar_fireworks": A("Anar fireworks", ["Diwali"], _anar_fireworks, {"colors": ("colors", FIREWORK), "rate": ("float", 1.2)},
                        "#ffc850,#ff3030,#30ff60,#ff40ff", "Dynamic. Firework bursts at random points: a white flash, then "
                        "a gold, red, green, pink or blue ring racing outwards and fading, over a dim warm glow."),
    "phuljhadi": A("Phuljhadi sparklers", ["Diwali"], _phuljhadi, {"color": ("color", "#ffa020"), "density": ("float", 0.08)},
                   "#ffa020,#ffffff,#ffc850", "Dynamic. Dim warm gold background with bright white and gold sparks "
                   "popping randomly all along the strip, like sparklers."),
    "lakshmi_wave": A("Lakshmi gold wave", ["Diwali"], _lakshmi_wave, {"wavelength": ("int", 18), "speed": ("float", 8.0)},
                      "#ff5a00,#ffd060,#ffffff", "Dynamic. Saffron-to-gold waves rolling along the house, with white "
                      "glints sparkling on each wave crest."),
    "flowing_diyas": A("Flowing diyas", ["Diwali"], _glide,
                       GL(_hx((255, 110, 0), (205, 230, 255), (255, 175, 30), (205, 230, 255)), 3, 1.0, 0.4, 0.8),
                       "#ff6e00,#cde6ff,#ffaf1e",
                       "Dynamic. Groups of 3 flickering orange and gold diyas floating on groups of 3 shimmering "
                       "white water lights, the river flowing slowly along the roofline."),
    "diwali_river": A("Diwali river", ["Diwali"], _glide, GL(_hx((255, 100, 0), WHITE), 10, 3.0, 0.6, 0.6),
                      "#ff6400,#ffffff,#ff6400",
                      "Dynamic. Wide bands of orange and white flowing along the roofline, blending into each "
                      "other, the orange flickering like flames and the white shimmering like water."),
    "akash_kandil": A("Akash kandil lanterns", ["Diwali"], _drift,
                      DR(_hx((255, 90, 0), (255, 40, 20), (255, 170, 30), (220, 0, 90)), "#190800", 6, 0, 1.5, 0, 1.2),
                      "#ff5a00,#ff2814,#ffaa1e,#dc005a", "Dynamic. Glowing paper lanterns in orange, red, gold and pink, "
                      "hanging along the roofline and gently swaying, over a dim warm glow."),
    "diwali": S("Diwali gold and amber", ["Diwali"], "#ffb000,#ff8c00,#ffb000,#ff4500,#ffb000,#d0007a"),
    "rangoli_bands": S("Rangoli bands", ["Diwali", "Hindu festivals"], RANGOLI),
    "toran": S("Toran garland", ["Diwali", "Hindu festivals"], _hx((255, 150, 0), (255, 150, 0), (40, 160, 20)),
               "Marigold orange with mango-leaf green, like a toran over the door."),

    # --- Hindu festivals ---
    "navratri": A("Navratri nine colors", ["Hindu festivals"], _steps,
                  {"colors": ("colors", _hx((255, 100, 0), WHITE, (230, 0, 20), (30, 60, 255), (255, 210, 0), (0, 190, 40),
                                            (150, 150, 175), (140, 0, 220), (0, 160, 140))), "hold": ("float", 4.0)},
                  "#ff6400,#e60014,#1e3cff,#ffd200,#00be28,#8c00dc", "Dynamic. The whole house steps through the nine "
                  "Navratri colors, holding each for a few seconds with a soft cross-fade."),
    "garba": A("Garba nights", ["Hindu festivals"], _rhythm,
               {"colors": ("colors", _hx((230, 0, 30), (255, 200, 0), (0, 180, 60), (220, 0, 150), (255, 110, 0), (0, 90, 255))),
                "width": ("int", 3), "bpm": ("float", 116.0)},
               "#e6001e,#ffc800,#00b43c,#dc0096", "Dynamic. Festive colors stepping along the house on a dandiya beat, "
               "flashing on each beat."),
    "bonfire": A("Bonfire", ["Hindu festivals"], _fire, {"speed": ("float", 1.0)}, "#aa1400,#ff5000,#ffa014,#ffdc78",
                 "Dynamic. Flickering flames, dark red to orange and yellow, for Dussehra and Lohri."),
    "holi": A("Holi color splash", ["Hindu festivals", "Celebration"], _bursts,
              BU(_hx((255, 0, 150), (0, 220, 60), (255, 220, 0), (0, 120, 255), (255, 110, 0), (150, 0, 255)),
                 "#140014", 1.6, 7.0, 3.2, False),
              "#ff0096,#00dc3c,#ffdc00,#0078ff,#9600ff", "Dynamic. Bright splashes of pink, green, yellow, blue, orange and "
              "purple bursting at random spots and spreading out."),
    "ganesh_marigold": S("Ganesh marigold", ["Hindu festivals"], _hx((255, 140, 0), (255, 200, 0), (220, 20, 0))),
    "peacock": A("Janmashtami peacock", ["Hindu festivals"], _swirl,
                 SWP(_hx((0, 50, 200), (0, 170, 150), (100, 0, 180), (0, 120, 60), (0, 50, 200)), 0.6),
                 "#0032c8,#00aa96,#6400b4,#00783c", "Dynamic. Peacock-feather blues, teals, greens and purples, slowly "
                 "blending along the house."),
    "kites": A("Sankranti kites", ["Hindu festivals"], _drift,
               DR(_hx((255, 40, 40), (255, 210, 0), (0, 200, 80), (0, 130, 255), (230, 0, 180)), "#001430", 5, 2.5, 1.5, 0, 2.5),
               "#001430,#ff2828,#ffd200,#0082ff", "Dynamic. Colorful kites drifting across a dark blue sky at different "
               "speeds, swaying in the wind."),
    "rakhi": A("Rakhi threads", ["Hindu festivals"], _rangoli_chase,
               {"colors": ("colors", _hx((220, 0, 20), (255, 190, 40), (220, 0, 20), (255, 110, 0))), "width": ("int", 2),
                "speed": ("float", 3.0)},
               "#dc0014,#ffbe28,#ff6e00", "Dynamic. Red, gold and saffron twisting along like rakhi threads."),
    "onam": S("Onam pookalam", ["Hindu festivals"], _hx((255, 210, 0), (255, 120, 0), WHITE, (220, 0, 20), (255, 120, 0))),
    "shivratri": A("Shivratri glow", ["Hindu festivals"], _swirl,
                   SWP(_hx((0, 15, 110), (0, 40, 200), (0, 15, 110), (190, 210, 255)), 0.3),
                   "#000f6e,#0028c8,#bed2ff", "Dynamic. Deep blue with a slow, soft white glow drifting through."),

    # --- India ---
    "indian_flag": dict(label="Indian flag", cats=["India"], params={}, face="#ff6a00,#ffffff,#00a000",
                        fn=lambda n, w, p: [SAFFRON if i < n / 3 else INDIA_WHITE if i < 2 * n / 3 else INDIA_GREEN
                                            for i in range(n)]),
    "tiranga_wave": A("Tiranga wave", ["India", "Celebration"], _tiranga_wave, {"speed": ("float", 1.0)},
                      "#ff6a00,#ffffff,#00a000", "Dynamic. Saffron, white and green thirds with a gentle waving-flag ripple."),
    "tricolor_fireworks": A("Tricolor fireworks", ["India"], _bursts,
                            BU(_hx(SAFFRON, WHITE, INDIA_GREEN), "#0a0500", 1.3), "#ff6a00,#ffffff,#00a000",
                            "Dynamic. Saffron, white and green firework bursts over a dark sky."),
    "chakra": A("Chakra chase", ["India"], _chakra, {"speed": ("float", 1.0)}, "#ff6a00,#ffffff,#141ec8,#00a000",
                "Dynamic. Saffron, white and green thirds, with a navy-blue chakra pulse moving through the white."),

    # --- Christmas ---
    "christmas": dict(label="Christmas", cats=["Christmas"], params={"width": ("int", 0), "white_ends": ("bool", True)},
                      fn=lambda n, w, p: _christmas(n, p["width"] or w, p["white_ends"]), face="#ff0000,#00a000,#ffffff"),
    "retro_c9": S("Retro C9 bulbs", ["Christmas"], _hx((230, 0, 0), (0, 170, 30), (20, 60, 255), (255, 110, 0), (255, 200, 0)),
                  "Old-style big Christmas bulbs: red, green, blue, orange and yellow."),
    "gingerbread": S("Gingerbread house", ["Christmas"], _hx((170, 70, 10), (170, 70, 10), WHITE),
                     "Warm gingerbread brown-orange with white icing."),
    "candy_cane": A("Candy cane chase", ["Christmas"], _candy_cane, {"width": ("int", 3), "speed": ("float", 4.0)},
                    "#ff0000,#ffffff,#ff0000", "Dynamic. Red and white stripes, 3 lights each, marching along the roofline."),
    "twinkle_tree": A("Twinkling tree", ["Christmas"], _twinkle_tree, {"speed": ("float", 1.0)}, "#006e14,#ff0000,#ffc850",
                      "Dynamic. Evergreen green base with red, gold and white ornaments twinkling."),
    "silent_night": A("Silent night", ["Christmas", "Everyday"], _twinkle,
                      TW(_hx((255, 150, 60)), _hx((255, 200, 120), WHITE), 0.2, 0.5, 0.45), "#ff963c,#ffc878,#ff963c",
                      "Dynamic. Soft warm white with a slow, gentle twinkle."),
    "snowfall": A("Snowfall", ["Christmas"], _drift, DR(_hx(WHITE, (200, 230, 255)), "#001e46", 8, 2.0, 0.6, 0, 1.5),
                  "#001e46,#ffffff,#c8e6ff", "Dynamic. White snowflakes drifting slowly along the roofline over icy blue."),
    "santa_sleigh": A("Santa's sleigh", ["Christmas"], _drift, DR(_hx((255, 220, 140)), "#000a1e", 0.4, 12.0, 1.0, 10, 0),
                      "#000a1e,#ffdc8c,#ffffff", "Dynamic. A bright golden streak racing across the house with a long "
                      "sparkling trail, over a dark night sky."),
    "red_green_chase": A("Red & green chase", ["Christmas"], _rangoli_chase,
                         {"colors": ("colors", "#ff0000,#00b020"), "width": ("int", 5), "speed": ("float", 4.0)},
                         "#ff0000,#00b020,#ff0000", "Dynamic. Red and green bands chasing along the roofline."),
    "north_pole": A("North Pole ice", ["Christmas"], _twinkle, TW(_hx((0, 90, 200), (0, 140, 220)), _hx(WHITE), 0.3, 1.0, 0.55),
                    "#005ac8,#ffffff,#008cdc", "Dynamic. Icy blues with white shimmering across them."),

    # --- Halloween ---
    "pumpkin_patch": S("Pumpkin patch", ["Halloween"], _hx((255, 90, 0), (255, 90, 0), (120, 0, 200))),
    "candy_corn": S("Candy corn", ["Halloween"], _hx((255, 200, 0), (255, 100, 0), WHITE)),
    "haunted": A("Haunted flicker", ["Halloween"], _haunted, {"color": ("color", "#ff5a00")}, "#ff5a00,#200800,#ff5a00",
                 "Dynamic. Orange lights that flicker, stutter and black out like failing bulbs."),
    "witch_brew": A("Witch's brew", ["Halloween"], _swirl, SWP(_hx((100, 0, 180), (40, 200, 0), (60, 0, 110), (120, 255, 0)), 1.2),
                    "#6400b4,#28c800,#3c006e", "Dynamic. Purple and toxic green bubbling and swirling together."),
    "lightning": A("Lightning storm", ["Halloween"], _storm, {"color": ("color", "#5a0096"), "rate": ("float", 0.35)},
                   "#3c0064,#ffffff,#5a0096", "Dynamic. Dim stormy purple with sudden white lightning flashes."),

    # --- Thanksgiving ---
    "harvest_glow": A("Harvest glow", ["Thanksgiving"], _swirl, SWP(_hx((255, 140, 0), (255, 190, 40), (170, 20, 0), (220, 80, 0)), 0.4),
                      "#ff8c00,#ffbe28,#aa1400", "Dynamic. Amber, gold, deep red and burnt orange slowly shimmering."),
    "autumn_leaves": A("Autumn leaves", ["Thanksgiving"], _drift,
                       DR(_hx((220, 30, 0), (255, 120, 0), (255, 190, 30), (170, 60, 0)), "#280c00", 7, 3.0, 1.0, 0, 2.0),
                       "#dc1e00,#ff7800,#ffbe1e", "Dynamic. Red, orange and gold leaves drifting along the house."),
    "cornucopia": S("Cornucopia", ["Thanksgiving"], _hx((170, 20, 0), (255, 120, 0), (255, 190, 40), (200, 80, 0))),

    # --- USA ---
    "stars_stripes": dict(label="Stars & stripes", cats=["USA"], params={"width": ("int", 0), "speed": ("float", 1.0)},
                          fn=lambda n, w, p: _stars_stripes(n, 0, {**p, "width": p["width"] or w}),
                          face="#1428c8,#ffffff,#dc0014,#ffffff"),
    "usa_fireworks": A("Red, white & blue fireworks", ["USA"], _bursts, BU(_hx(US_RED, US_WHITE, US_BLUE), "#00000f", 1.3),
                       "#dc0014,#ffffff,#1428c8", "Dynamic. Red, white and blue firework bursts over a dark sky."),
    "patriotic_wave": A("Patriotic wave", ["USA"], _stars_stripes, {"width": ("int", 4), "speed": ("float", 1.0)},
                        "#1428c8,#dc0014,#ffffff", "Dynamic. A blue field of twinkling stars, then red and white stripes, "
                        "all rippling like a flag in the wind."),
    "remembrance": S("Remembrance", ["USA"], _hx((150, 0, 15), (180, 180, 180), (15, 30, 140)),
                     "Soft, steady red, white and blue for Memorial Day and Veterans Day."),

    # --- More US holidays ---
    "valentine": A("Valentine heartbeat", ["More US holidays"], _heartbeat,
                   {"color": ("color", "#ff4f9a"), "beat": ("color", "#ff0020"), "bpm": ("float", 66.0)},
                   "#ff4f9a,#ff0020,#ff4f9a", "Dynamic. Soft pink with a red lub-dub heartbeat pulse."),
    "shamrock": A("Shamrock shimmer", ["More US holidays"], _twinkle,
                  TW(_hx((0, 170, 40), (0, 200, 90), (0, 110, 30)), _hx((255, 200, 60), WHITE), 0.2, 1.0, 0.7),
                  "#00aa28,#00c85a,#ffc83c", "Dynamic. St. Patrick's greens with gold and white twinkles."),
    "easter": S("Easter pastels", ["More US holidays"], _hx((255, 120, 170), (255, 230, 110), (120, 255, 170), (190, 140, 255), (120, 190, 255))),
    "new_year": A("New Year's sparkle", ["More US holidays", "Celebration"], _bursts,
                  BU(_hx((255, 200, 80), WHITE, (200, 220, 255)), "#0a0814", 1.6), "#ffc850,#ffffff,#c8dcff",
                  "Dynamic. Gold, white and silver firework sparkles bursting all over the house."),

    # --- Celebration ---
    "deepavali_rainbow": A("Festival rainbow", ["Celebration"], _deepavali_rainbow,
                           {"spread": ("float", 1.0), "speed": ("float", 1.0)}, "#ff0000,#ffd000,#00c000,#0060ff,#a000ff",
                           "Dynamic. A full rainbow flowing slowly along the strip with a soft shimmer."),
    "birthday_confetti": A("Birthday confetti", ["Celebration"], _twinkle,
                           TW(_hx((255, 0, 120), (0, 160, 255), (255, 200, 0), (140, 0, 255)),
                              _hx((255, 0, 120), (0, 220, 80), (255, 200, 0), (0, 160, 255), WHITE), 0.45, 2.0, 0.35),
                           "#ff0078,#00a0ff,#ffc800,#8c00ff", "Dynamic. Party colors with bright confetti popping everywhere."),
    "birthday_candles": A("Birthday candles", ["Celebration"], _candles,
                          CAND(30, _hx((255, 0, 120), (0, 160, 255), (255, 200, 0), (140, 0, 255))),
                          "#ff0078,#ff9628,#00a0ff,#ff9628", "Dynamic. One candle flame per year along the house over party "
                          "colors; every 15 seconds they're blown out, confetti pops, and they relight. Set the age."),
    "birthday_18": A("18th birthday", ["Celebration"], _candles, CAND(18, _hx((255, 0, 150), (150, 0, 255), (0, 220, 220), WHITE)),
                     "#ff0096,#9600ff,#00dcdc", "Dynamic. 18 candle flames over neon pink, purple and teal party colors."),
    "birthday_40": A("40th birthday", ["Celebration"], _candles, CAND(40, _hx((255, 190, 40), (60, 40, 10), (255, 220, 120))),
                     "#ffbe28,#3c280a,#ffdc78", "Dynamic. 40 candle flames over black-and-gold party colors."),
    "birthday_50": A("50th birthday", ["Celebration"], _candles, CAND(50, _hx((255, 190, 40), (200, 210, 230), (255, 220, 120))),
                     "#ffbe28,#c8d2e6,#ffdc78", "Dynamic. 50 candle flames over gold and silver."),
    "birthday_60": A("60th birthday", ["Celebration"], _candles, CAND(60, _hx(WHITE, (150, 200, 255), (200, 210, 230))),
                     "#ffffff,#96c8ff,#c8d2e6", "Dynamic. 60 candle flames over diamond white and ice blue."),
    "wedding": A("Wedding red & gold", ["Celebration"], _twinkle,
                 TW(_hx((180, 0, 20), (220, 10, 30)), _hx((255, 190, 40), WHITE), 0.3, 1.2, 0.7),
                 "#b40014,#ffbe28,#dc0a1e", "Dynamic. Deep wedding red shimmering with gold and white."),

    # --- School spirit ---
    "ut_austin": S("UT Austin bands", ["School spirit"], _hx(UT_ORANGE, WHITE)),
    "ut_austin_gameday": A("UT Austin game day", ["School spirit"], _gameday,
                           {"colors": ("colors", _hx(UT_ORANGE, WHITE)), "width": ("int", 4), "speed": ("float", 4.0)},
                           "#cc5500,#ffffff,#cc5500", "Dynamic. Burnt orange and white chasing along the house with sparkles."),
    "aggies": S("Texas A&M bands", ["School spirit"], _hx(AGGIE_MAROON, WHITE)),
    "aggies_gameday": A("Texas A&M game day", ["School spirit"], _gameday,
                        {"colors": ("colors", _hx(AGGIE_MAROON, WHITE)), "width": ("int", 4), "speed": ("float", 4.0)},
                        "#960019,#ffffff,#960019", "Dynamic. Maroon and white chasing along the house with sparkles."),
    "utd": S("UT Dallas bands", ["School spirit"], _hx(UTD_ORANGE, UTD_GREEN)),
    "utd_gameday": A("UT Dallas game day", ["School spirit"], _gameday,
                     {"colors": ("colors", _hx(UTD_ORANGE, UTD_GREEN, WHITE)), "width": ("int", 4), "speed": ("float", 4.0)},
                     "#e87500,#007837,#ffffff", "Dynamic. Orange, green and white chasing along the house with sparkles."),
    "asu": S("Arizona State bands", ["School spirit"], _hx(ASU_MAROON, ASU_GOLD)),
    "asu_gameday": A("Arizona State game day", ["School spirit"], _gameday,
                     {"colors": ("colors", _hx(ASU_MAROON, ASU_GOLD)), "width": ("int", 4), "speed": ("float", 4.0)},
                     "#960041,#ffc627,#960041", "Dynamic. Maroon and gold chasing along the house with sparkles."),
    "graduation": A("Graduation", ["School spirit", "Celebration"], _twinkle,
                    TW(_hx((255, 190, 40)), _hx(WHITE, (255, 230, 150)), 0.35, 1.5, 0.6), "#ffbe28,#ffffff,#ffbe28",
                    "Dynamic. Gold with bright white sparkles. Change the colors to a school's."),
    "team_bands": S("Team bands (pick colors)", ["School spirit"], _hx((255, 0, 0), WHITE), tile=False),
    "team_chase": A("Team chase (pick colors)", ["School spirit"], _gameday,
                    {"colors": ("colors", _hx((255, 0, 0), WHITE)), "width": ("int", 4), "speed": ("float", 4.0)},
                    "#ff0000,#ffffff", "Dynamic. Two team colors chasing along the house with sparkles.", tile=False),
    "team_sparkle": A("Team sparkle (pick colors)", ["School spirit"], _twinkle,
                      TW(_hx((255, 0, 0)), _hx(WHITE), 0.3, 1.5, 0.7), "#ff0000,#ffffff",
                      "Dynamic. A team color with white sparkles.", tile=False),
}


def catalogue():
    return [{"id": k, "label": v["label"], "group": v["cats"][0], "categories": v["cats"],
             "animated": bool(v.get("animated")), "describe": v.get("describe", ""), "face": v.get("face", ""),
             "tile": v.get("tile", True),
             "params": {p: {"type": t, "default": d} for p, (t, d) in v["params"].items()}}
            for k, v in PATTERNS.items()]


def _coerce(spec, params):
    out = {}
    for name, (typ, default) in spec.items():
        v = params.get(name, default)
        if typ == "int":
            v = int(v or 0)
        elif typ == "float":
            v = float(v if v not in (None, "") else default)
        elif typ == "bool":
            v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
        elif typ == "color":
            hex_to_rgb(v)
        elif typ == "colors":
            if not _colors(v):
                raise ValueError(f"{name}: need at least one colour")
        out[name] = v
    return out


def get(name):
    if name not in PATTERNS:
        raise ValueError(f"unknown pattern {name!r}")
    return PATTERNS[name]


def is_animated(name):
    return bool(get(name).get("animated"))


def frame(name, lights, params, t=0.0, reverse=False, seg_width=5):
    """One colour per light at time t (static patterns ignore t)."""
    pat = get(name)
    p = _coerce(pat["params"], params or {})
    colors = pat["fn"](lights, t, p) if pat.get("animated") else pat["fn"](lights, seg_width, p)
    return list(reversed(colors)) if reverse else colors


def segment_of(i, lights, segments, lps=0):
    """Light index -> segment, or None if no segment reaches that light.
    With lps (lights per segment; 5 on Govee H806A) segments are fixed-size from the
    start of the run; without it, an even split."""
    if lps:
        s = i // lps
        return s if s < segments else None
    return i * segments // lights


def render(name, lights, segments, params, reverse=False, lps=0):
    return frame(name, lights, params, 0.0, reverse, lps or max(1, lights // segments))


def quantise(colors, segments, lps=0):
    """Per-light colours -> (per-segment colour, mixed flags). Most common colour wins;
    on a tie, the colour of the middle light of that segment."""
    n = len(colors)
    out, mixed = [], []
    for s in range(segments):
        members = [colors[i] for i in range(n) if segment_of(i, n, segments, lps) == s]
        if not members:                          # segment past the end of the run
            break
        counts = {}
        for c in members:
            counts[c] = counts.get(c, 0) + 1
        top = max(counts.values())
        tied = [c for c in counts if counts[c] == top]
        out.append(tied[0] if len(tied) == 1 else members[len(members) // 2])
        mixed.append(len(counts) > 1)
    return out, mixed


def plan_calls(seg_colors):
    """Group segments by colour: one call per distinct colour."""
    groups = {}
    for s, c in enumerate(seg_colors):
        groups.setdefault(tuple(c), []).append(s)
    return [(list(c), segs) for c, segs in groups.items()]
