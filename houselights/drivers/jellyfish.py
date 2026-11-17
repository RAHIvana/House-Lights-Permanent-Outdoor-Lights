"""JellyFish Lighting controllers, over the LAN.

Following JellyFish's API document and API Explorer: JSON messages over a WebSocket at
ws://<controller>:9000/ws, one connection per command, no login.
- {"cmd": "toCtlrGet", "get": [["zones"]]} lists the zones and their pixel counts.
- {"cmd": "toCtlrSet", "runPattern": {"file": "", "data": "<pattern JSON as a string>", "id": "",
  "state": 1 or 0, "zoneName": [zones]}} runs a pattern (state 0 turns the zones off).
  Brightness lives in the pattern ("runData": {"brightness": 0-100}).
- A pattern holds at most 30 colours, and there is no per-light streaming and no way to read
  what a zone shows. So: whole-zone colour, on/off and brightness work; static themes are
  sent as up to 30 colour blocks ("Multi-Paint", numOfLeds lights each), exact when the theme
  repeats with 30 colours or fewer, otherwise approximated; animated themes can't play.
Tested only against tools/fake_jellyfish.py so far, not a real JellyFish controller.
"""
import json
import logging
import os
import socket

from . import net
from .base import Kit as BaseKit

log = logging.getLogger("houselights")

LABEL = "JellyFish Lighting"
NOTE = ("Each zone becomes its own run. Static themes and colours only (no animated themes); "
        "not yet tested with real JellyFish hardware.")
TESTED = False

MODELS = {"JellyFish": {"label": "JellyFish controller zone", "lights_per_segment": 1, "max_lights": 3000}}

PORT = int(os.environ.get("HOUSELIGHTS_JELLYFISH_PORT", "9000"))   # moved only for the simulator
PATH = "/ws"
MAX_COLORS = 30


def available():
    return True, ""


def options(c, secret):
    zone = str(c.get("zone") or "").strip()
    if not zone or len(zone) > 40:
        raise ValueError("pick the JellyFish zone for this run")
    return {"zone": zone}, {}


def _zones(ip, timeout=2.0):
    r = net.ws_exchange(ip, PORT, PATH, [json.dumps({"cmd": "toCtlrGet", "get": [["zones"]]})], timeout=timeout)
    if not isinstance(r, dict) or not isinstance(r.get("zones"), dict):
        raise ValueError("not a JellyFish controller")
    return r["zones"]


def _rows(ip, zones):
    out = []
    for name, z in zones.items():
        ctlr = ((z.get("portMap") or [{}])[0] or {}).get("ctlrName", "")
        out.append({"ip": ip, "type": "jellyfish", "model": "JellyFish", "zone": name, "supported": True,
                    "lights": z.get("numPixels"), "device_tail": "",
                    "label": f"JellyFish zone {name}" + (f" ({ctlr})" if ctlr else "")})
    return out


def discover(targets="", deep=False, expect=0, known=()):
    """Ask every address (typed, or this computer's /24 network) for its zones. A deep scan
    waits longer for slow controllers."""
    from .govee import expand_targets
    ips = expand_targets(targets) if str(targets or "").strip() else expand_targets(",".join(net.local_networks()))
    ips = [ip for ip in ips if ip not in set(known)]
    found = net.probe_many(lambda ip: _zones(ip, timeout=4.0 if deep else 1.0), ips)
    rows = []
    for ip in sorted(found, key=socket.inet_aton):
        rows += _rows(ip, found[ip])
    return rows


def probe(info):
    ip = str(info.get("ip", "")).strip()
    try:
        return _rows(ip, _zones(ip))
    except Exception as e:
        raise ValueError(f"no JellyFish controller answered at {ip} ({type(e).__name__})") from None


def read_status(kits):
    """JellyFish can't report what a zone shows."""
    return {k.c.id: None for k in kits}


def pattern(colors_flat, kind="Color", num_leds=1, brightness=100, speed=10):
    """Pattern data in the field order of JellyFish's documentation."""
    return {"colors": list(colors_flat), "spaceBetweenPixels": max(1, num_leds),
            "effectBetweenPixels": "No Color Transform", "type": kind, "skip": 1, "numOfLeds": max(1, num_leds),
            "runData": {"speed": speed, "brightness": max(0, min(100, int(brightness))), "effect": "No Effect",
                        "effectValue": 0, "rgbAdj": [100, 100, 100]},
            "direction": "Right"}


def blocks(colors, limit=MAX_COLORS):
    """(palette, lights per block) that shows `colors` with at most `limit` colours:
    exact if the frame is made of equal blocks repeating within the limit, else rounded."""
    import math
    n = len(colors)
    runs, start = [], 0
    for i in range(1, n + 1):
        if i == n or colors[i] != colors[start]:
            runs.append(i - start)
            start = i
    full = runs[:-1] or runs                               # the last run may be cut short
    b = 0
    for r in full:
        b = math.gcd(b, r)
    if runs[-1] > b and len(runs) > 1 and runs[-1] % b:
        b = math.gcd(b, runs[-1])
    seq = [colors[i] for i in range(0, n, b)]
    for p in range(1, min(limit, len(seq)) + 1):
        if all(seq[k] == seq[k % p] for k in range(len(seq))):
            return seq[:p], b
    b = max(1, -(-n // limit))
    pal = []
    for start in range(0, n, b):
        chunk = colors[start:start + b]
        pal.append(max(set(chunk), key=chunk.count))
    return pal, b


def expand(pal, b, n):
    return [pal[(i // b) % len(pal)] for i in range(n)]


class Kit(BaseKit):
    CAPS = {"stream": False, "static": "palette", "pick": False, "status": False, "count": "reported",
            "restore": "none"}
    slow_fps = 1.0

    def __init__(self, controller, live):
        super().__init__(controller, live)
        self.zone = (controller.options or {}).get("zone", "")
        self._bri = 100
        self._data = None                     # the last pattern sent, for brightness and power on
        self._on = None                       # whether the zone was last switched on or off (None: not yet)

    def _run(self, data, state, what):
        self.guard()
        msg = {"cmd": "toCtlrSet", "runPattern": {"file": "", "data": json.dumps(data, separators=(",", ":")),
                                                  "id": "", "state": state, "zoneName": [self.zone]}}
        log.info("%s %s JellyFish %s", self.prefix, self.tag, what)
        if self.live:
            # Wait for the controller's "fromCtlr" answer, so the next command can't overtake this one.
            if net.ws_exchange(self.c.ip, PORT, PATH, [json.dumps(msg)], reply=True, timeout=3.0) is None:
                log.warning("%s JellyFish didn't confirm %s", self.tag, what)

    def _solid(self, rgb):
        return pattern(list(rgb[:3]), "Color", 1, self._bri)

    def power(self, on):
        with self.lock:
            self._data = self._data or self._solid((255, 160, 80))        # what we sent is what it shows
            self._run(self._data, 1 if on else 0, "on" if on else "off")
            self._on = bool(on)

    def brightness(self, value):
        """Brightness is a field of the pattern, so it needs a pattern we sent. A zone that was switched off
        stays off (the next power on uses the new level)."""
        with self.lock:
            if not self._data:
                raise ValueError("JellyFish can't report what a zone is showing: pick a colour or theme first, "
                                 "then change the brightness")
            self._bri = max(1, min(100, int(value)))
            self._data["runData"]["brightness"] = self._bri
            self._run(self._data, 0 if self._on is False else 1, f"brightness {self._bri}")

    def color(self, rgb):
        with self.lock:
            self._data = self._solid(rgb)
            self._run(self._data, 1, "colour #%02X%02X%02X" % tuple(rgb[:3]))
            self._on = True

    def kelvin(self, k):
        self.color(net.kelvin_to_rgb(k))

    def preview_static(self, colors):
        pal, b = blocks([tuple(c) for c in colors])
        return expand(pal, b, len(colors))

    def show_lights(self, colors):
        """Caller holds self.lock."""
        pal, b = blocks([tuple(c) for c in colors])
        if len(pal) == 1:
            self._data = self._solid(pal[0])
        else:
            flat = [v for c in pal for v in c[:3]]
            self._data = pattern(flat, "Multi-Paint", b, self._bri, speed=100)
        self._run(self._data, 1, f"{len(pal)} colour(s), {b} light(s) each")
        self._on = True
