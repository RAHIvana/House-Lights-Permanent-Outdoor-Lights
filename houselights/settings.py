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
SECRETS_NAME = "secrets.json"          # e.g. Tuya local keys: kept out of config.json, mode 600
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
    type: str                 # driver: "govee", "wled", "jellyfish", "tuya"
    model: str                # e.g. "H806A"
    ip: str
    name: str = ""
    enabled: bool = True
    options: dict = field(default_factory=dict)     # per driver, e.g. {"zone": "Zone1"}
    secret: dict = field(default_factory=dict)      # from secrets.json, never sent to the page


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
    light1: str = ""          # "left", "right" (as you face the lights) or "" (not checked yet)

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

    @property
    def info(self):
        """The controller model's {label, tier, caps, max_lights, lights_per_segment, note}."""
        from . import drivers
        return drivers.model_info(self.controller.type, self.controller.model) or {}

    @property
    def caps(self):
        """What this run's controller can do: per model (e.g. a Govee model's tier)."""
        from . import drivers
        return drivers.model_caps(self.controller.type, self.controller.model)

    def public(self):
        info = self.info
        return {"id": self.id, "name": self.name, "short": self.short, "subtitle": self.subtitle,
                "start": self.start, "ip": self.controller.ip, "controller": self.controller.id,
                "model": self.controller.model, "type": self.controller.type,
                "model_label": info.get("label", self.controller.model), "tier": info.get("tier"),
                "tier_note": info.get("note", ""),
                "zone": self.controller.options.get("zone", ""), "caps": self.caps,
                "enabled": self.enabled, "lights": self.lights,
                "segments": self.segments, "lights_per_segment": self.lights_per_segment,
                "reachable": self.reachable, "transport": "lan", "reverse": self.reverse,
                "light1": self.light1, "baseline": self.baseline}


@dataclass
class Settings:
    mode: str
    host: str
    port: int
    controllers: dict
    sections: dict
    stream_fps: int = 15
    location: tuple | None = None       # (lat, lon) for sunrise/sunset schedules (config: also zip, place)
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


LIGHT1 = ("left", "right", "")


def _light1(r, what):
    """Where light 1 is, as you face the lights: "left", "right" or "" (not checked yet).
    reverse (themes run from the last light) follows from it: light 1 at the right end. Old
    files without light1 keep their reverse."""
    if r.get("light1") is None:
        reverse = bool(r.get("reverse", False))
        return ("right" if reverse else ""), reverse
    light1 = str(r.get("light1")).strip().lower()
    if light1 not in LIGHT1:
        raise ValueError(f"{what}: light 1 must be at the left or right end")
    return light1, light1 == "right"


def validate(raw, secrets=None):
    """Check a config (from the wizard or the file) and return a clean copy.
    Raises ValueError with a message the wizard can show. Secrets typed in the wizard (e.g. a
    Tuya local key) are moved out of the config into the returned "_secrets" entry."""
    from . import drivers                       # drivers know their models
    secrets = secrets if secrets is not None else read_secrets()
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
        for k, what, limit in (("zip", "ZIP code", 10), ("place", "place name", 64)):
            v = _text(loc.get(k), what, limit)
            if v:
                out["location"][k] = v

    ctrls, ips, found_secrets = [], set(), {}
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
        info = drivers.model_info(ctype, model)
        if not info:
            hint = (f"a {ctype} model name looks like H806A" if hasattr(drv, "model_info")
                    else f"supported: {', '.join(drv.MODELS)}")
            raise ValueError(f"{what}: model {model!r} is not supported yet ({hint})")
        model = info["model"]
        try:
            ip = str(ipaddress.ip_address(_text(c.get("ip"), f"{what} IP address", 45, True)))
        except ValueError:
            raise ValueError(f"{what}: {c.get('ip')!r} is not an IP address") from None
        if not drivers.net.is_home_address(ip):
            raise ValueError(f"{what}: {ip} isn't on your own network ({drivers.net.HOME_ADDRESSES})")
        try:
            opts, sec = drv.options(c, secrets.get(cid) or {})
        except ValueError as e:
            raise ValueError(f"{what} ({ip}): {e}") from None
        where = (ip, opts.get("zone", ""))
        if where in ips:
            raise ValueError(f"{what}: {ip}{' zone ' + where[1] if where[1] else ''} is used twice")
        ips.add(where)
        if sec:
            found_secrets[cid] = sec
        ctrls.append({"id": cid, "type": ctype, "model": model, "ip": ip,
                      "name": _text(c.get("name"), f"{what} name", 40), "enabled": bool(c.get("enabled", True)),
                      **opts})
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
        model = drivers.model_info(by_id[cid]["type"], by_id[cid]["model"])
        base = r.get("baseline") or {}
        light1, reverse = _light1(r, f"{what} ({name})")
        runs.append({"id": rid, "name": name,
                     "short": _text(r.get("short") or name[:12], f"{what} short name", 12, True),
                     "subtitle": _text(r.get("subtitle"), f"{what} note", 60),
                     "start": _text(r.get("start"), f"{what} start", 80),
                     "controller": cid,
                     "lights": _num(r.get("lights"), f"{what} ({name}) lights", 1, model["max_lights"]),
                     "light1": light1,
                     "reverse": reverse,
                     "baseline": {"brightness": _num(base.get("brightness", 50), f"{what} brightness", 1, 100),
                                  "kelvin": _num(base.get("kelvin", 2200), f"{what} kelvin", 2000, 9000)}})
    if len({r["id"] for r in runs}) != len(runs):
        raise ValueError("two runs have the same id (give them different names)")
    if not runs:
        raise ValueError("add at least one run of lights")
    out["runs"] = runs
    out["_secrets"] = found_secrets
    return out


def public_config(clean):
    """The config for the page: no secrets, but say which controllers have one."""
    out = {k: v for k, v in clean.items() if k != "_secrets"}
    have = clean.get("_secrets") or {}
    out["controllers"] = [dict(c, has_secret=c["id"] in have) for c in clean["controllers"]]
    return out


def read_secrets():
    try:
        with open(path(SECRETS_NAME), encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _owner_only(p):
    """Windows ignores the 0o600 mode, and a folder like C:\\Projects lets every account on the
    computer read what is in it. Replace the file's permissions with one entry: this user."""
    import subprocess
    quiet = {"capture_output": True, "check": True, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        out = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], **quiet).stdout
        sid = out.decode("ascii", "replace").strip().split(",")[-1].strip('"')
        if not sid.startswith("S-1-"):
            raise OSError("whoami did not give this user's id")
        subprocess.run(["icacls", p, "/inheritance:r", "/grant:r", f"*{sid}:(F)"], **quiet)
    except (OSError, subprocess.CalledProcessError) as e:
        raise ValueError(f"could not make {SECRETS_NAME} readable only by you ({e})") from None


def _write_private(name, data):
    os.makedirs(home(), exist_ok=True)
    tmp = path(name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if os.name == "nt":
                _owner_only(tmp)              # before anything secret is in it
            json.dump(data, f, indent=2)
    except ValueError:
        os.remove(tmp)
        raise
    os.replace(tmp, path(name))               # the file keeps its permissions when moved


def read_raw():
    """The config file as written, or None if there is none yet (first start: wizard)."""
    try:
        with open(path(CONFIG_NAME), encoding="utf-8-sig") as f:
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
    secrets = clean.pop("_secrets")
    if secrets or os.path.exists(path(SECRETS_NAME)):
        _write_private(SECRETS_NAME, secrets)       # first: if it fails, config.json is unchanged
    os.makedirs(home(), exist_ok=True)
    tmp = path(CONFIG_NAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
        f.write("\n")
    os.replace(tmp, path(CONFIG_NAME))
    clean["_secrets"] = secrets
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
    base = ("id", "type", "model", "ip", "name", "enabled")
    controllers = {x["id"]: Controller(x["id"], x["type"], x["model"], x["ip"], x["name"], x["enabled"],
                                       {k: v for k, v in x.items() if k not in base},
                                       c["_secrets"].get(x["id"], {}))
                   for x in c["controllers"]}
    sections = {}
    for r in c["runs"]:
        ctrl = controllers[r["controller"]]
        sections[r["id"]] = Section(
            id=r["id"], name=r["name"], short=r["short"], subtitle=r["subtitle"], start=r["start"],
            controller=ctrl, lights=r["lights"], reverse=r["reverse"], baseline=r["baseline"], light1=r["light1"],
            lights_per_segment=(drivers.model_info(ctrl.type, ctrl.model) or {}).get("lights_per_segment", 0))
    loc = c["location"]
    return Settings(mode="dry" if forced_dry() else c["mode"], host=c["listen"]["host"], port=c["listen"]["port"],
                    controllers=controllers, sections=sections, stream_fps=c["stream_fps"],
                    location=(loc["lat"], loc["lon"]) if loc else None, timezone=c["timezone"], raw=c)
