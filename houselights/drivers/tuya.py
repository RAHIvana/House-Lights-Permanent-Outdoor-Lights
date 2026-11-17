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
import os
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
INSTALL = ("venv\\Scripts\\pip" if os.name == "nt" else "venv/bin/pip") + " install tinytuya"


def _lib():
    try:
        import tinytuya
        return tinytuya
    except ImportError:
        return None


def available():
    return (True, "") if _lib() else (False, f"Needs the tinytuya package: {INSTALL}")


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
        raise ValueError(f"tinytuya is not installed ({INSTALL})")
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


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pct(value, top):
    """A raw level on TinyTuya's own scale (type A 0-255, type B 0-1000) as 1-100 %; None if unknown."""
    v = _int(value)
    return None if v is None else max(1, min(100, round(v * 100 / top)))


def _hexint(text, a, b):
    try:
        return int(text[a:b], 16)
    except (TypeError, ValueError):
        return None


def light_kind(dps):
    """"B" (data points 20-28), "A" (1-9) or None: TinyTuya's own tell, a power data point plus a mode
    data point that is text ("white", "colour"...). A plug has a power data point only; a dimmer switch has
    a number in data point 2; a multi-socket switch has on/off values there."""
    dps = {str(k): v for k, v in (dps or {}).items()}
    if "20" in dps and isinstance(dps.get("21"), str):
        return "B"
    if "1" in dps and isinstance(dps.get("2"), str):
        return "A"
    return None


def looks_like_light(dps):
    """A colour light: light_kind plus a colour data point. A white-only bulb has no colour, so the
    colour commands would fail on it; plugs, switches and dimmers aren't lights."""
    kind = light_kind(dps)
    dps = {str(k): v for k, v in (dps or {}).items()}
    return (kind == "B" and isinstance(dps.get("24"), str)) or (kind == "A" and isinstance(dps.get("5"), str))


def parse_dps(dps):
    """Tuya light data points -> {onOff, brightness, color, colorTemInKelvin}.
    Type B (20 power, 21 mode, 22 white brightness 10-1000, 23 temperature 0-1000, 24 colour HSV hex)
    and type A (1 power, 2 mode, 3 white brightness 25-255, 4 temperature 0-255, 5 colour hex).
    Brightness is that of the mode the light is in, on TinyTuya's own scale, so what a command sets is
    what is read back: the white level in white mode, the colour's value (V) in colour mode. None when
    the light doesn't say (never a made-up 100)."""
    dps = {str(k): v for k, v in (dps or {}).items()}
    if "20" in dps:
        on, mode, bri, temp, col = dps.get("20"), dps.get("21"), dps.get("22"), dps.get("23"), dps.get("24")
        tpct = (_int(temp) or 0) / 1000
        rgb, value = (0, 0, 0), None
        if isinstance(col, str) and len(col) >= 12:
            h, s, v = _hexint(col, 0, 4), _hexint(col, 4, 8), _hexint(col, 8, 12)
            if None not in (h, s, v):
                rgb = tuple(round(x * 255) for x in colorsys.hsv_to_rgb(h / 360, s / 1000, v / 1000))
                value = _pct(v, 1000)
        pct = value if mode == "colour" and value is not None else _pct(bri, 1000)
    elif "1" in dps:
        on, mode, bri, temp, col = dps.get("1"), dps.get("2"), dps.get("3"), dps.get("4"), dps.get("5")
        tpct = (_int(temp) or 0) / 255
        rgb, value = (0, 0, 0), None
        if isinstance(col, str) and len(col) >= 6:
            r, g, b = _hexint(col, 0, 2), _hexint(col, 2, 4), _hexint(col, 4, 6)
            if None not in (r, g, b):
                rgb = (r, g, b)
                v = _hexint(col, 12, 14) if len(col) >= 14 else None
                value = _pct(v if v is not None else max(rgb), 255)
        pct = value if mode == "colour" and value is not None else _pct(bri, 255)
    else:
        return None
    white = mode == "white"
    kelvin = round(2700 + tpct * 3800) if white else 0
    if white:
        rgb = net.kelvin_to_rgb(kelvin)
    return {"onOff": 1 if on else 0, "brightness": pct,
            "color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]}, "colorTemInKelvin": kelvin}


def discover(targets="", deep=False, expect=0, known=()):
    """Tuya devices announce themselves by UDP broadcast (ports 6666/6667/7000); listen ~6 s,
    20 s for a deep scan. Only devices on this computer's own network are heard; typed
    addresses are ignored."""
    tt = _lib()
    if not tt:
        raise ValueError(f"tinytuya is not installed ({INSTALL})")
    found = tt.deviceScan(False, 20 if deep else 6) or {}
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
    if not looks_like_light(r.get("dps")):
        raise ValueError("that Tuya device doesn't look like a colour light (a plug, switch or dimmer, or a bulb that reports no colour?)")
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
        self._bri = None            # the brightness (percent) set from the page; None until then
        self._kind = None           # "A" or "B", learned from the light's status

    def _dev(self):
        """The library's device object. Every use of it (making it included) happens with self.lock held:
        it keeps one connection's state, so two threads must never use it at once."""
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

    def _learn(self):
        """Ask the light once what kind it is and how bright it is now: the kind gives the lowest safe
        brightness, and the brightness is where colours and whites start, so the current percentage carries
        across white and colour. Caller holds self.lock. If it can't be read nothing is made up."""
        if not self.live or (self._kind is not None and self._bri is not None):
            return
        try:
            dps = _check(self._dev().status()).get("dps")
        except OSError:
            return
        if self._kind is None:
            self._kind = light_kind(dps)
        if self._bri is None:
            st = parse_dps(dps)
            self._bri = st["brightness"] if st else None

    def _min_pct(self):
        """The lowest percent TinyTuya takes without switching the light OFF (below the model's minimum it
        turns the light off): 10 for type A (25 of 255), 1 for type B (10 of 1000). Unknown: the safe 10."""
        self._learn()
        return 1 if self._kind == "B" else 10

    def brightness(self, value):
        """Brightness of the mode the light is in (the white level, or the colour's value): never below the
        minimum, so the slider can't switch the light off. It is kept for the colours and whites after it
        (and until it is set, they start from what the light has)."""
        with self.lock:
            self._bri = max(self._min_pct(), min(100, int(value)))
            self._call("brightness", "set_brightness_percentage", self._bri)

    def _colour(self, rgb):
        """Colour at the light's brightness: the one set from the page, else the one the light has. (TinyTuya
        sends a colour at its own value, so a bare full red would be 100%.) If neither is known the colour goes
        out as it is, never a made-up level. Caller holds self.lock."""
        self._learn()
        r, g, b = [int(v) for v in rgb[:3]]
        if self._bri is not None:
            r, g, b = (round(v * self._bri / 100) for v in (r, g, b))
        self._call("colour", "set_colour", r, g, b)

    def color(self, rgb):
        with self.lock:
            self._colour(rgb)

    def kelvin(self, k):
        pct = max(0, min(100, round((int(k) - 2700) * 100 / 3800)))
        with self.lock:
            self._learn()
            if self._bri is None:                 # brightness unknown: leave the light's own level alone
                self._call("white", "set_colourtemp_percentage", pct)
            else:
                self._call("white", "set_white_percentage", self._bri, pct)

    def segments(self, segs, rgb, nseg):
        """One segment: the whole strip. Caller holds self.lock."""
        self._colour(rgb)

    def status(self):
        with self.lock:                           # the dashboard asks every 15 s, whatever else is going on
            r = _check(self._dev().status())
        return parse_dps(r.get("dps"))

    def snapshot(self):
        self._bri = 100                           # only wizard tests take a snapshot: their colours show at full
        if not self.live:                         # brightness, so they can be seen whatever the light is set to
            return None
        try:
            with self.lock:
                dps = _check(self._dev().status()).get("dps") or {}
        except OSError:
            return None
        keep = [k for k in ("20", "21", "22", "23", "24", "1", "2", "3", "4", "5") if k in {str(x) for x in dps}]
        return {k: dps.get(k, dps.get(int(k)) if k.isdigit() else None) for k in keep}

    def restore(self, snap):
        if snap and self.live:
            with self.lock:
                self.guard()
                log.info("%s %s Tuya restore %s", self.prefix, self.tag, snap)
                _check(self._dev().set_multiple_values(snap))
