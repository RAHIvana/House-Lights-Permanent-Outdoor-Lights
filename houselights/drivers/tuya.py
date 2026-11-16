"""Tuya / Smart Life Wi-Fi light strips (many Amazon brands, e.g. most ASAHOM kits), over the
LAN with the tinytuya library (pip install tinytuya).

Local control needs each device's id, its protocol version and its 16-character "local key".
The key comes from Tuya's cloud once: run `python -m tinytuya wizard` (see the README).
These lights show one colour at a time: no per-light colours, no animated themes. A static
theme is shown as its main colour. Tests save the light's state and put it back afterwards.
Tested only with a stand-in for tinytuya so far, not a real Tuya device.
"""
import colorsys
import logging
import re

from . import net
from .base import Kit as BaseKit

log = logging.getLogger("houselights")

LABEL = "Tuya / Smart Life (one colour at a time)"
NOTE = ("For lights using the Smart Life or Tuya Smart app (most ASAHOM kits, many Amazon brands). Needs: pip install tinytuya, and each device's local key (python -m tinytuya wizard). "
        "Whole-strip colour only. Not yet tested with real Tuya hardware.")
TESTED = False

MODELS = {"Tuya light": {"label": "Tuya / Smart Life light strip", "lights_per_segment": 0, "max_lights": 2000}}
VERSIONS = ("3.1", "3.2", "3.3", "3.4", "3.5")


def _lib():
    try:
        import tinytuya
        return tinytuya
    except ImportError:
        return None


def available():
    return (True, "") if _lib() else (False, "Needs the tinytuya package: venv/bin/pip install tinytuya")


def options(c, secret):
    dev = str(c.get("device_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{8,40}", dev):
        raise ValueError("type the Tuya device id (letters and digits)")
    ver = str(c.get("version") or "3.3").strip()
    if ver not in VERSIONS:
        raise ValueError(f"Tuya protocol version must be one of {', '.join(VERSIONS)}")
    key = str(c.get("local_key") or secret.get("local_key") or "").strip()
    if len(key) != 16:
        raise ValueError("the Tuya local key is 16 characters (from python -m tinytuya wizard)")
    return {"device_id": dev, "version": ver}, {"local_key": key}


def _device(dev_id, ip, key, version):
    tt = _lib()
    if not tt:
        raise ValueError("tinytuya is not installed (venv/bin/pip install tinytuya)")
    try:
        d = tt.BulbDevice(dev_id, ip, key, version=float(version), connection_timeout=3, connection_retry_limit=2)
    except TypeError:                                 # older tinytuya without those arguments
        d = tt.BulbDevice(dev_id, ip, key)
        d.set_version(float(version))
    d.set_socketTimeout(3)
    return d


def _check(r):
    if isinstance(r, dict) and r.get("Error"):
        raise OSError(f"Tuya: {r.get('Error')} ({r.get('Err', '')})")
    return r


def parse_dps(dps):
    """Tuya light data points -> {onOff, brightness, color, colorTemInKelvin}.
    Type B (20 power, 21 mode, 22 brightness 10-1000, 23 temperature 0-1000, 24 colour HSV hex)
    and type A (1 power, 2 mode, 3 brightness 25-255, 4 temperature 0-255, 5 colour hex)."""
    dps = {str(k): v for k, v in (dps or {}).items()}
    if "20" in dps:
        on, mode, bri, temp, col = dps.get("20"), dps.get("21"), dps.get("22"), dps.get("23"), dps.get("24")
        pct = round((int(bri) - 10) * 100 / 990) if bri is not None else 100
        tpct = int(temp) / 1000 if temp is not None else 0
        rgb = (0, 0, 0)
        if isinstance(col, str) and len(col) >= 12:
            h, s, v = int(col[0:4], 16), int(col[4:8], 16), int(col[8:12], 16)
            rgb = tuple(round(x * 255) for x in colorsys.hsv_to_rgb(h / 360, s / 1000, v / 1000))
    elif "1" in dps:
        on, mode, bri, temp, col = dps.get("1"), dps.get("2"), dps.get("3"), dps.get("4"), dps.get("5")
        pct = round((int(bri) - 25) * 100 / 230) if bri is not None else 100
        tpct = int(temp) / 255 if temp is not None else 0
        rgb = (0, 0, 0)
        if isinstance(col, str) and len(col) >= 6:
            rgb = (int(col[0:2], 16), int(col[2:4], 16), int(col[4:6], 16))
    else:
        return None
    white = mode == "white"
    kelvin = round(2700 + tpct * 3800) if white else 0
    if white:
        rgb = net.kelvin_to_rgb(kelvin)
    return {"onOff": 1 if on else 0, "brightness": max(1, min(100, pct)),
            "color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]}, "colorTemInKelvin": kelvin}


def discover(targets=""):
    """Tuya devices announce themselves by UDP broadcast (ports 6666/6667/7000); listen ~6 s.
    Only devices on this computer's own network are heard; typed addresses are ignored."""
    tt = _lib()
    if not tt:
        raise ValueError("tinytuya is not installed (venv/bin/pip install tinytuya)")
    found = tt.deviceScan(False, 6) or {}
    rows = []
    for ip, d in found.items():
        dev = str(d.get("gwId") or d.get("id") or "")
        rows.append({"ip": d.get("ip", ip), "type": "tuya", "model": "Tuya light", "supported": True,
                     "device_id": dev, "version": str(d.get("version") or "3.3"), "needs_key": True,
                     "device_tail": dev[-5:], "lights": None,
                     "label": f"Tuya device {d.get('name') or dev[-6:]}"})
    return rows


def probe(info):
    ip = str(info.get("ip", "")).strip()
    opts, sec = options(info, {})
    r = _check(_device(opts["device_id"], ip, sec["local_key"], opts["version"]).status())
    if not parse_dps(r.get("dps")):
        raise ValueError("that Tuya device doesn't look like a light")
    return [{"ip": ip, "type": "tuya", "model": "Tuya light", "supported": True, "device_id": opts["device_id"],
             "version": opts["version"], "device_tail": opts["device_id"][-5:], "lights": None,
             "label": "Tuya light (key works)"}]


def read_status(kits):
    out = net.probe_many(lambda k: k.status(), list(kits), workers=8)
    return {k.c.id: out.get(k) for k in kits}


class Kit(BaseKit):
    CAPS = {"stream": False, "static": "segments", "pick": False, "status": True, "count": "display",
            "restore": "snapshot"}
    slow_fps = 0.5

    def __init__(self, controller, live):
        super().__init__(controller, live)
        o, s = controller.options or {}, controller.secret or {}
        self.dev_id, self.version, self.key = o.get("device_id", ""), o.get("version", "3.3"), s.get("local_key", "")
        self._d = None
        self._bri = 100

    def _dev(self):
        if self._d is None:
            self._d = _device(self.dev_id, self.c.ip, self.key, self.version)
        return self._d

    def _call(self, what, fn, *args):
        self.guard()
        log.info("%s %s Tuya %s %s", self.prefix, self.tag, what, args or "")
        if self.live:
            _check(getattr(self._dev(), fn)(*args))

    def power(self, on):
        with self.lock:
            self._call("on" if on else "off", "turn_on" if on else "turn_off")

    def brightness(self, value):
        with self.lock:
            self._bri = max(1, min(100, int(value)))
            self._call("brightness", "set_brightness_percentage", self._bri)

    def _colour(self, rgb):
        self._call("colour", "set_colour", *[int(v) for v in rgb[:3]])

    def color(self, rgb):
        with self.lock:
            self._colour(rgb)

    def kelvin(self, k):
        pct = max(0, min(100, round((int(k) - 2700) * 100 / 3800)))
        with self.lock:
            self._call("white", "set_white_percentage", self._bri, pct)

    def segments(self, segs, rgb, nseg):
        """One segment: the whole strip. Caller holds self.lock."""
        self._colour(rgb)

    def status(self):
        r = _check(self._dev().status())
        return parse_dps(r.get("dps"))

    def snapshot(self):
        if not self.live:
            return None
        try:
            dps = _check(self._dev().status()).get("dps") or {}
        except OSError:
            return None
        keep = [k for k in ("20", "21", "22", "23", "24", "1", "2", "3", "4", "5") if k in {str(x) for x in dps}]
        return {k: dps.get(k, dps.get(int(k)) if k.isdigit() else None) for k in keep}

    def restore(self, snap):
        if snap and self.live:
            with self.lock:
                log.info("%s %s Tuya restore %s", self.prefix, self.tag, snap)
                _check(self._dev().set_multiple_values(snap))
