"""Settings: <home>/config.json, written by the setup wizard.

<home> is --home on the command line (or HOUSELIGHTS_HOME); by default the `data` folder next
to the houselights package. Nothing secret is stored: the lights are controlled over the LAN.
"""
import ipaddress
import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

log = logging.getLogger("houselights")

PKG = os.path.dirname(os.path.abspath(__file__))
CONFIG_NAME = "config.json"
VERSION = 1


def home():
    return os.path.abspath(os.environ.get("HOUSELIGHTS_HOME") or os.path.join(os.path.dirname(PKG), "data"))


def path(*parts):
    return os.path.join(home(), *parts)


def forced_dry():
    """--dry on the command line: practice mode whatever the config says."""
    return os.environ.get("HOUSELIGHTS_DRY") == "1"


@dataclass
class Controller:
    id: str
    type: str                 # driver: "govee"
    model: str                # e.g. "H806A"
    ip: str
    name: str = ""
    enabled: bool = True


@dataclass
class Section:
    """One run of lights on one controller ("run" in the page and the config)."""
    id: str
    name: str
    short: str
    subtitle: str
    start: str                # where light 1 is, e.g. "left end, seen from the street"
    controller: Controller
    lights: int
    reverse: bool
    baseline: dict = field(default_factory=dict)
    lights_per_segment: int = 0

    @property
    def enabled(self):
        return self.controller.enabled

    @property
    def segments(self):
        lps = self.lights_per_segment
        return -(-self.lights // lps) if lps else 1

    @property
    def used_segments(self):
        return self.segments

    @property
    def reachable(self):
        return self.lights

    def public(self):
        return {"id": self.id, "name": self.name, "short": self.short, "subtitle": self.subtitle,
                "start": self.start, "ip": self.controller.ip, "controller": self.controller.id,
                "model": self.controller.model, "type": self.controller.type,
                "enabled": self.enabled, "lights": self.lights,
                "segments": self.segments, "lights_per_segment": self.lights_per_segment,
                "reachable": self.reachable, "transport": "lan", "reverse": self.reverse,
                "baseline": self.baseline}


@dataclass
class Settings:
    mode: str
    host: str
    port: int
    controllers: dict
    sections: dict
    stream_fps: int = 15
    location: tuple | None = None       # (lat, lon) for sunrise/sunset schedules
    timezone: str = "UTC"
    configured: bool = True
    raw: dict = field(default_factory=dict)
    error: str = ""                      # config.json exists but has a problem: the wizard shows it

    @property
    def live(self):
        return self.mode == "live"


def default_config():
    """What the wizard starts from."""
    return {"version": VERSION, "mode": "live", "listen": {"host": "0.0.0.0", "port": 8090},
            "stream_fps": 15, "timezone": "UTC", "location": None, "controllers": [], "runs": []}


_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _text(v, what, limit, required=False):
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise ValueError(f"{what} is empty")
    if len(v) > limit:
        raise ValueError(f"{what} is longer than {limit} characters")
    return v


def _num(v, what, lo, hi, kind=int):
    try:
        x = kind(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number") from None
    if isinstance(x, float) and not math.isfinite(x):
        raise ValueError(f"{what} must be a number")
    if not lo <= x <= hi:
        raise ValueError(f"{what} must be between {lo} and {hi}")
    return x


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")[:32]
    return s or "run"


def validate(raw):
    """Check a config (from the wizard or the file) and return a clean copy.
    Raises ValueError with a message the wizard can show."""
    from . import drivers                       # drivers know their models
    if not isinstance(raw, dict):
        raise ValueError("config must be a JSON object")
    out = default_config()
    out["mode"] = raw.get("mode", "live")
    if out["mode"] not in ("dry", "live"):
        raise ValueError("mode must be live or dry")
    listen = raw.get("listen") or {}
    out["listen"] = {"host": _text(listen.get("host", "0.0.0.0"), "listen host", 64, True),
                     "port": _num(listen.get("port", 8090), "listen port", 1, 65535)}
    out["stream_fps"] = _num(raw.get("stream_fps", 15), "stream_fps", 1, 30)
    tz = _text(raw.get("timezone") or "UTC", "time zone", 64, True)
    try:
        ZoneInfo(tz)
    except Exception:
        raise ValueError(f"unknown time zone {tz!r} (use a name like America/New_York)") from None
    out["timezone"] = tz
    loc = raw.get("location") or {}
    if loc.get("lat") not in (None, "") or loc.get("lon") not in (None, ""):
        out["location"] = {"lat": round(_num(loc.get("lat"), "latitude", -90, 90, float), 4),
                           "lon": round(_num(loc.get("lon"), "longitude", -180, 180, float), 4)}

    ctrls, ips = [], set()
    for i, c in enumerate(raw.get("controllers") or []):
        what = f"controller {i + 1}"
        cid = _text(c.get("id"), f"{what} id", 32, True).lower()
        if not _ID.match(cid):
            raise ValueError(f"{what} id {cid!r}: use lower-case letters, digits, - and _")
        ctype = c.get("type", "govee")
        drv = drivers.get(ctype)
        if not drv:
            raise ValueError(f"{what}: controller type {ctype!r} is not supported")
        model = _text(c.get("model"), f"{what} model", 32, True)
        if model not in drv.MODELS:
            raise ValueError(f"{what}: model {model!r} is not supported yet (supported: {', '.join(drv.MODELS)})")
        try:
            ip = str(ipaddress.ip_address(_text(c.get("ip"), f"{what} IP address", 45, True)))
        except ValueError:
            raise ValueError(f"{what}: {c.get('ip')!r} is not an IP address") from None
        if ip in ips:
            raise ValueError(f"{what}: IP address {ip} is used twice")
        ips.add(ip)
        ctrls.append({"id": cid, "type": ctype, "model": model, "ip": ip,
                      "name": _text(c.get("name"), f"{what} name", 40), "enabled": bool(c.get("enabled", True))})
    if len({c["id"] for c in ctrls}) != len(ctrls):
        raise ValueError("two controllers have the same id")
    out["controllers"] = ctrls

    by_id = {c["id"]: c for c in ctrls}
    runs, used = [], set()
    for i, r in enumerate(raw.get("runs") or []):
        what = f"run {i + 1}"
        name = _text(r.get("name"), f"{what} name", 40, True)
        rid = _text(r.get("id") or slug(name), f"{what} id", 32, True).lower()
        if not _ID.match(rid):
            raise ValueError(f"{what} id {rid!r}: use lower-case letters, digits, - and _")
        cid = r.get("controller")
        if cid not in by_id:
            raise ValueError(f"{what} ({name}): pick its controller")
        if cid in used:
            raise ValueError(f"{what} ({name}): controller {cid} already has a run (one run per controller)")
        used.add(cid)
        model = drivers.get(by_id[cid]["type"]).MODELS[by_id[cid]["model"]]
        base = r.get("baseline") or {}
        runs.append({"id": rid, "name": name,
                     "short": _text(r.get("short") or name[:12], f"{what} short name", 12, True),
                     "subtitle": _text(r.get("subtitle"), f"{what} note", 60),
                     "start": _text(r.get("start"), f"{what} start", 80),
                     "controller": cid,
                     "lights": _num(r.get("lights"), f"{what} ({name}) lights", 1, model["max_lights"]),
                     "reverse": bool(r.get("reverse", False)),
                     "baseline": {"brightness": _num(base.get("brightness", 50), f"{what} brightness", 1, 100),
                                  "kelvin": _num(base.get("kelvin", 2200), f"{what} kelvin", 2000, 9000)}})
    if len({r["id"] for r in runs}) != len(runs):
        raise ValueError("two runs have the same id (give them different names)")
    if not runs:
        raise ValueError("add at least one run of lights")
    out["runs"] = runs
    return out


def read_raw():
    """The config file as written, or None if there is none yet (first start: wizard)."""
    try:
        with open(path(CONFIG_NAME)) as f:
            raw = json.load(f)
    except FileNotFoundError:
        return None
    except ValueError as e:
        raise ValueError(f"{CONFIG_NAME} is not valid JSON ({e})") from None
    if not isinstance(raw, dict):
        raise ValueError(f"{CONFIG_NAME} must hold a JSON object")
    return raw


def save(raw):
    """Validate and write the config atomically. Returns the clean config."""
    clean = validate(raw)
    os.makedirs(home(), exist_ok=True)
    tmp = path(CONFIG_NAME + ".tmp")
    with open(tmp, "w") as f:
        json.dump(clean, f, indent=2)
        f.write("\n")
    os.replace(tmp, path(CONFIG_NAME))
    log.info("config saved: %d controller(s), %d run(s)", len(clean["controllers"]), len(clean["runs"]))
    return clean


def load():
    """Settings from config.json; with no file, an empty setup (the page opens the wizard)."""
    from . import drivers
    try:
        raw = read_raw()
        c = validate(raw) if raw is not None else None
    except ValueError as e:
        log.error("settings problem, opening the setup wizard: %s", e)
        raw, c, error = None, None, str(e)
    else:
        error = ""
    if c is None:
        d = default_config()
        return Settings(mode="dry" if forced_dry() else "live", host=d["listen"]["host"], port=d["listen"]["port"],
                        controllers={}, sections={}, configured=False, raw=d, error=error)
    controllers = {x["id"]: Controller(x["id"], x["type"], x["model"], x["ip"], x["name"], x["enabled"])
                   for x in c["controllers"]}
    sections = {}
    for r in c["runs"]:
        ctrl = controllers[r["controller"]]
        sections[r["id"]] = Section(
            id=r["id"], name=r["name"], short=r["short"], subtitle=r["subtitle"], start=r["start"],
            controller=ctrl, lights=r["lights"], reverse=r["reverse"], baseline=r["baseline"],
            lights_per_segment=drivers.get(ctrl.type).MODELS[ctrl.model].get("lights_per_segment", 0))
    loc = c["location"]
    return Settings(mode="dry" if forced_dry() else c["mode"], host=c["listen"]["host"], port=c["listen"]["port"],
                    controllers=controllers, sections=sections, stream_fps=c["stream_fps"],
                    location=(loc["lat"], loc["lon"]) if loc else None, timezone=c["timezone"], raw=c)
