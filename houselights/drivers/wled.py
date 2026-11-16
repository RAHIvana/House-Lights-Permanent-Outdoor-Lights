"""WLED controllers (open source firmware for ESP8266/ESP32 LED controllers), over the LAN.

Following the WLED docs (kno.wled.ge, JSON API and UDP realtime):
- GET /json/info: name, brand, MAC, version and the light count (info.leds.count).
- POST /json/state: "on", "bri" (1-255), "seg": [{"id": 0, "col": [[r, g, b]]}] for a solid
  colour, and per-light colours with "i" ([start, "RRGGBB", "RRGGBB", ...], at most 256
  colours per call). Per-light colours stay until the effect changes or the light turns off.
- Animated themes stream over UDP port 21324 as DNRGB packets (protocol 4: start index, then
  r, g, b per light, at most 489 per packet). Byte 1 is a timeout: WLED goes back to its
  normal look that many seconds after the last packet.
Tested only against tools/fake_wled.py so far, not a real WLED controller.
"""
import json
import logging
import os
import socket

from . import net
from .base import Kit as BaseKit

log = logging.getLogger("houselights")

LABEL = "WLED (open source, ESP8266/ESP32)"
NOTE = ("Any controller running WLED 0.13 or newer (DIY, open-source, ASAHOM Pro models sold with WLED). "
        "Not yet tested with real WLED hardware.")
TESTED = False

MODELS = {"WLED": {"label": "WLED controller", "lights_per_segment": 1, "max_lights": 1500}}

# HOUSELIGHTS_WLED_PORTS="http,udp" moves the ports, only for the simulator (tools/fake_wled.py).
HTTP_PORT, UDP_PORT = (int(p) for p in os.environ.get("HOUSELIGHTS_WLED_PORTS", "80,21324").split(","))
TIMEOUT_S = 2                     # realtime timeout byte: back to normal 2 s after the last frame
PER_PACKET = 489                  # DNRGB limit
PER_CALL = 256                    # "i" colours per JSON call


def _url(ip, path):
    return f"http://{ip}{'' if HTTP_PORT == 80 else f':{HTTP_PORT}'}{path}"


def available():
    return True, ""


def options(c, secret):
    return {}, {}


def _info(ip, timeout=1.5):
    info = net.http_json(_url(ip, "/json/info"), timeout=timeout)
    if not isinstance(info, dict) or "leds" not in info or "ver" not in info:
        raise ValueError("not a WLED device")
    return info


def _row(ip, info):
    leds = info.get("leds") or {}
    return {"ip": ip, "type": "wled", "model": "WLED", "supported": True,
            "label": f"WLED {info.get('ver', '')} · {info.get('name', '')}".strip(" ·"),
            "device_tail": str(info.get("mac", ""))[-5:], "lights": leds.get("count"),
            "rgbw": bool((leds.get("lc", 1) & 2) if isinstance(leds.get("lc"), int) else leds.get("rgbw"))}


def discover(targets=""):
    """Ask every address (typed, or this computer's /24 network) for /json/info."""
    from .govee import expand_targets
    ips = expand_targets(targets) if str(targets or "").strip() else expand_targets(",".join(net.local_networks()))
    found = net.probe_many(lambda ip: _info(ip, timeout=1.0), ips)
    return [_row(ip, info) for ip, info in sorted(found.items(), key=lambda kv: socket.inet_aton(kv[0]))]


def probe(info):
    ip = str(info.get("ip", "")).strip()
    try:
        return [_row(ip, _info(ip))]
    except Exception as e:
        raise ValueError(f"no WLED device answered at {ip} ({type(e).__name__})") from None


def _status_one(ip):
    st = net.http_json(_url(ip, "/json/state"), timeout=1.5)
    seg = (st.get("seg") or [{}])[0]
    col = (seg.get("col") or [[0, 0, 0]])[0]
    r, g, b = (list(col) + [0, 0, 0])[:3]
    return {"onOff": 1 if st.get("on") else 0, "brightness": max(1, round(int(st.get("bri", 255)) * 100 / 255)),
            "color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0}


def read_status(kits):
    got = net.probe_many(_status_one, sorted({k.c.ip for k in kits}), workers=16)
    return {k.c.id: got.get(k.c.ip) for k in kits}


def _hex(c):
    return "%02X%02X%02X" % tuple(c[:3])


def dnrgb_packets(colors, timeout=TIMEOUT_S):
    """UDP realtime frames: [4, timeout, start_hi, start_lo, r, g, b, ...] per 489 lights."""
    out = []
    for start in range(0, len(colors), PER_PACKET):
        chunk = colors[start:start + PER_PACKET]
        out.append(bytes([4, timeout, start >> 8, start & 0xFF]) + b"".join(bytes(c[:3]) for c in chunk))
    return out


def i_calls(colors):
    """JSON bodies setting every light: {"seg": {"id": 0, "i": [start, hex, hex, ...]}}."""
    return [{"seg": {"id": 0, "i": [start] + [_hex(c) for c in colors[start:start + PER_CALL]]}}
            for start in range(0, len(colors), PER_CALL)]


class Kit(BaseKit):
    CAPS = {"stream": True, "static": "lights", "pick": True, "status": True, "count": "reported",
            "restore": "auto"}
    max_stream_lights = 1500

    def __init__(self, controller, live):
        super().__init__(controller, live)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _post(self, body, what=None):
        self.guard()
        log.info("%s %s WLED %s", self.prefix, self.tag, what or json.dumps(body)[:160])
        if self.live:
            net.http_json(_url(self.c.ip, "/json/state"), body, timeout=3.0)

    def power(self, on):
        with self.lock:
            self._post({"on": bool(on)})

    def brightness(self, value):
        with self.lock:
            self._post({"bri": max(1, min(255, round(int(value) * 255 / 100)))})

    def color(self, rgb):
        with self.lock:
            self._post({"on": True, "seg": [{"id": 0, "fx": 0, "col": [list(rgb[:3])]}]})

    def kelvin(self, k):
        self.color(net.kelvin_to_rgb(k))

    def segments(self, segs, rgb, nseg):
        """Here a segment is one light (lights_per_segment 1). Caller holds self.lock."""
        segs = sorted(set(int(s) for s in segs))
        if not segs or segs[0] < 0 or segs[-1] >= nseg:
            raise ValueError(f"lights out of range 0..{nseg - 1}: {segs}")
        body = []
        for s in segs:
            body += [s, _hex(rgb)]
        self._post({"seg": {"id": 0, "i": body}}, f"lights {segs[:8]}{'...' if len(segs) > 8 else ''} #{_hex(rgb)}")

    def show_lights(self, colors):
        """Caller holds self.lock. Turn on first: WLED ignores per-light colours sent together with "on"."""
        self._post({"on": True}, "on")
        for k, body in enumerate(i_calls(colors)):
            self._post(body, f"per-light colours, part {k + 1} ({len(body['seg']['i']) - 1} lights)")

    def stream_begin(self):
        self.guard()

    def stream_frame(self, colors):
        if self.live:
            for pkt in dnrgb_packets(colors):
                self.udp.sendto(pkt, (self.c.ip, UDP_PORT))

    def stream_end(self):
        pass                      # WLED returns to its normal look TIMEOUT_S after the last frame
