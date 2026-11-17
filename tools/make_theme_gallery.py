"""Draw every built-in theme as a small picture and write the themes page, with plain Python.

    python tools/make_theme_gallery.py        # writes docs/themes.md and docs/themes/*.png

Each picture is a strip of 48 lights, one bar per light, drawn by the same code that plays the
theme on a house: a looping animated PNG for an animated theme, one frame for a still one. Run this
again after adding or changing a theme (tests/test_themes.py checks the page is up to date).
"""
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from houselights import patterns as P  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
PICS = os.path.join(DOCS, "themes")
LIGHTS = 48
BAR, GAP, TALL, EDGE = 7, 2, 22, 3              # pixels: a light, the gap after it, its height, the border
WIDTH, HEIGHT = 2 * EDGE + LIGHTS * (BAR + GAP) - GAP, 2 * EDGE + TALL
NIGHT = (12, 16, 30)
SECONDS, DELAY = 4.0, 8                          # the loop, and hundredths of a second a frame (12.5 frames a second)
BLEND = 0.6                                      # the end of the loop fades into its start
LONG = {"navratri": (16.0, 32), "birthday_candles": (15.0, 25), "birthday_18": (15.0, 25),
        "birthday_40": (15.0, 25), "birthday_50": (15.0, 25), "birthday_60": (15.0, 25)}     # id: (seconds, delay)


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def scanlines(colors):
    """One frame as PNG rows, before compression. A bar is the same all the way down, so
    every row but the first of each band is "same as the row above" (filter 2)."""
    night = bytes(NIGHT)
    bars = night * EDGE + b"".join(bytes(c) * BAR + night * GAP for c in colors)[:-3 * GAP] + night * EDGE
    border, same = b"\x00" + night * WIDTH, b"\x02" + bytes(3 * WIDTH)
    return border + same * (EDGE - 1) + b"\x00" + bars + same * (TALL - 1) + border + same * (EDGE - 1)


def png(frames, delay):
    """A PNG from frames of one colour per light: animated (APNG, looping) if there are several."""
    out = [b"\x89PNG\r\n\x1a\n", chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))]
    if len(frames) > 1:
        out.append(chunk(b"acTL", struct.pack(">II", len(frames), 0)))
    seq = 0
    for k, colors in enumerate(frames):
        data = zlib.compress(scanlines(colors), 9)
        if len(frames) > 1:
            out.append(chunk(b"fcTL", struct.pack(">IIIIIHHBB", seq, WIDTH, HEIGHT, 0, 0, delay, 100, 0, 0)))
            seq += 1
        if k == 0:
            out.append(chunk(b"IDAT", data))
        else:
            out.append(chunk(b"fdAT", struct.pack(">I", seq) + data))
            seq += 1
    return b"".join(out + [chunk(b"IEND", b"")])


def frames_of(pid):
    """(frames, delay): the theme on 48 lights; the last moments fade into the first frame."""
    if not P.is_animated(pid):
        return [P.frame(pid, LIGHTS, {})], 0
    seconds, delay = LONG.get(pid, (SECONDS, DELAY))
    step = delay / 100
    out = []
    for k in range(round(seconds / step)):
        t = k * step
        cols = P.frame(pid, LIGHTS, {}, t)
        if t > seconds - BLEND:
            before = P.frame(pid, LIGHTS, {}, t - seconds)
            cols = [P._mix(a, b, (t - (seconds - BLEND)) / BLEND) for a, b in zip(cols, before)]
        out.append(cols)
    return out, delay


def anchor(cat):
    return "".join(ch for ch in cat.lower().replace(" ", "-") if ch.isalnum() or ch == "-")


# What a still theme looks like, for the ones that have no description of their own.
STILL = {
    "warm_gold": "Warm gold on every light.",
    "solid": "One color of your choice on every light.",
    "alternating": "Two or more colors of your choice taking turns, 5 lights each.",
    "gradient": "One color blending into another from end to end.",
    "random": "Colors from your list in a shuffled order, 5 lights each.",
    "diwali": "Gold and amber bands with orange-red and magenta accents, 5 lights each.",
    "rangoli_bands": "Rangoli colors (magenta, orange, yellow, green, blue, purple) in bands of 5 lights.",
    "ganesh_marigold": "Marigold orange, yellow and red bands, 5 lights each.",
    "onam": "Pookalam flower colors: yellow, orange, white and red bands.",
    "indian_flag": "Saffron, white and green, a third of the run each.",
    "pumpkin_patch": "Pumpkin orange with purple, 5 lights each.",
    "candy_corn": "Yellow, orange and white bands, like candy corn.",
    "cornucopia": "Deep red, orange, gold and rust bands, 5 lights each.",
    "stars_stripes": "The US flag: a blue field with white stars, then red and white stripes.",
    "easter": "Pastel pink, yellow, mint, lavender and sky blue bands.",
    "ut_austin": "Burnt orange and white bands.",
    "aggies": "Maroon and white bands.",
    "utd": "Orange and green bands.",
    "asu": "Maroon and gold bands.",
    "team_bands": "Your team's colors in bands, 5 lights each.",
}


def blurb(pid, pat):
    text = pat.get("describe") or STILL.get(pid)
    if not text:
        raise SystemExit(f"{pid}: no description. Give the theme one, or add it to STILL in this file.")
    return text.replace("Dynamic. ", "", 1).replace("Fast. ", "", 1)


INTRO = """# House Lights themes

**{total} built-in themes**, {animated} of them animated light by light, and you can
[make your own](../README.md#themes). Every picture on this page is drawn by the same code that
plays the theme on your house: 48 lights, one bar per light.

The apps that come with the lights show a handful of scenes. House Lights plays every light on
its own, {fps} times a second, so a comet can race the whole roofline, snow can drift past the
windows and fireworks can go off over the garage. Pick a theme on the dashboard's **Quick
Settings** tab, or put it on a schedule (sunset to 11 pm, say) and it starts by itself.

**New for the holidays:** the **[Animated-fast](#animated-fast)** group ({fast} fast, showy themes
to stand out on your street), {thanksgiving} themes for **[Thanksgiving](#thanksgiving)** and
{christmas} for **[Christmas](#christmas)**.

Jump to: {jump}

Good to know:

- Animated themes play light by light on **Govee H806A** (tested on real lights) and **WLED**
  controllers (tested with a simulator); other Govee permanent outdoor lights can try. On other
  kinds they show as a still picture or the theme's main color (see
  [Supported controllers](../README.md#supported-controllers)).
- Animated themes play while the dashboard is running; still themes stay on the lights.
- Fast means fast movement, not strobing: the beat themes pulse about twice a second, and no theme
  flashes the whole house more than 3 times a second (a test checks it).
- Any theme can be changed (colors, speed, size) and saved as your own in the **Themes** tab.
"""

SECTION_NOTE = {
    P.FAST: "Fast movement for any night: racing comets, marquee bulbs, color wipes, dance beats and "
            "fireworks. The fast holiday themes are here too.",
}


def page():
    pats = P.PATTERNS
    count = lambda cat: sum(1 for v in pats.values() if cat in v["cats"])       # noqa: E731
    lines = [INTRO.format(total=len(pats), animated=sum(1 for v in pats.values() if v.get("animated")), fps=15,
                          fast=count(P.FAST), thanksgiving=count("Thanksgiving"), christmas=count("Christmas"),
                          jump=" · ".join(f"[{c}](#{anchor(c)})" for c in P.CATEGORIES))]
    for cat in P.CATEGORIES:
        rows = [(pid, v) for pid, v in pats.items() if cat in v["cats"]]
        lines += [f"## {cat}", ""]
        if cat in SECTION_NOTE:
            lines += [SECTION_NOTE[cat], ""]
        lines += [f"{len(rows)} themes.", "", "| Theme | On 48 lights | What you see |", "|---|---|---|"]
        for pid, v in rows:
            kind = "animated, fast" if P.FAST in v["cats"] else "animated" if v.get("animated") else "still"
            pick = "" if v.get("tile", True) else "<br>pick your colors"
            lines.append(f'| **{v["label"]}**<br>{kind}{pick} | <img src="themes/{pid}.png" width="{WIDTH}" '
                         f'height="{HEIGHT}" alt="{v["label"]}"> | {blurb(pid, v)} |')
        lines.append("")
    lines += ["---", "", "This page is made by `tools/make_theme_gallery.py`; run it again after adding a theme.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    os.makedirs(PICS, exist_ok=True)
    wanted, total = {f"{pid}.png" for pid in P.PATTERNS}, 0
    for old in sorted(set(os.listdir(PICS)) - wanted):
        if old.endswith(".png"):                 # a theme that was removed
            os.remove(os.path.join(PICS, old))
            print("removed", old)
    for pid in P.PATTERNS:
        data = png(*frames_of(pid))
        total += len(data)
        with open(os.path.join(PICS, f"{pid}.png"), "wb") as f:
            f.write(data)
    with open(os.path.join(DOCS, "themes.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(page())
    print(f"wrote docs/themes.md and {len(P.PATTERNS)} pictures in docs/themes ({total // 1024} KB)")
