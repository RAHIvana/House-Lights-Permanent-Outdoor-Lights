"""Setup wizard API (/api/setup/...): find controllers, play test patterns, save settings.

Used on the first start (no config.json yet) and later from the Settings tab. Test patterns
stop by themselves after TEST_SECONDS. Controllers that stream (Govee, WLED) go back to what
they showed when a test stops; Tuya lights are saved and put back; JellyFish can't be
(the wizard says so).
"""
import datetime as dt
import json
import logging
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from . import drivers, runtime, settings
from .settings import Controller
from .stream import Streamer

log = logging.getLogger("houselights")
router = APIRouter(prefix="/api/setup")

TEST_SECONDS = 60
DEEP_SECONDS = 30                  # longest deep scan (Govee: keeps asking silent addresses)
TESTS = {}                    # (ip, zone) -> Streamer playing a test
HOOKS = {"before_test": None, "settings": None}     # set by app.py

RED, GREEN, BLUE, WHITE, OFF = (255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)
DIM_WHITE = (120, 120, 120)
ORANGE = (255, 110, 0)
EXTRA = 20                         # "check" test: orange lights past the last one, to spot a short count
ZIP_URL = "https://api.zippopotam.us/{country}/{code}"
ZIP_TIMEOUT = 5


# --- test patterns: fn(n, t) -> [rgb] * n, in the run's own light order ---------------------
def _identify(n, t):
    """The whole run blinks white once a second: which run is this?"""
    return [WHITE if (t % 1.0) < 0.5 else OFF] * n


def _identify_slow(n, t, fps=1.0):
    """Blink for controllers that change at most `fps` times a second: white, then blue."""
    return [WHITE if int(t * fps + 1e-6) % 2 == 0 else BLUE] * n


def _ruler(n, t):
    """Light 1 red, last light blue, every 10th light white, every 5th dim: count the lights."""
    out = []
    for i in range(n):
        if i == 0:
            out.append(RED)
        elif i == n - 1:
            out.append(BLUE)
        elif (i + 1) % 10 == 0:
            out.append(WHITE)
        elif (i + 1) % 5 == 0:
            out.append((60, 60, 60))
        else:
            out.append(OFF)
    return out


def _check(n, t, lights=None):
    """Light 1 red, the lights between dim white, light `lights` blue, and orange after it
    (the frame is longer than the count): orange lights mean the count is too low, no blue
    means it's too high. Red shows which end light 1 is at."""
    lights = n if lights is None else max(1, min(n, lights))
    out = [DIM_WHITE] * lights + [ORANGE] * (n - lights)
    out[lights - 1] = BLUE
    out[0] = RED
    return out


def _chase(n, t):
    """A white dot runs from light 1 (red) to the last light (blue), 8 lights a second."""
    pos = int(t * 8) % (n + 8)
    out = [OFF] * n
    out[0], out[-1] = RED, BLUE
    for k in range(3):
        if 0 <= pos - k < n:
            out[pos - k] = tuple(round(v * (1 - k * 0.35)) for v in WHITE)
    return out


def _rgb(n, t):
    """First third red, middle green, last third blue: are the colours right?"""
    return [RED if i < n / 3 else GREEN if i < 2 * n / 3 else BLUE for i in range(n)]


def _segments(n, t, lps=5):
    """Alternating colours per segment-sized group: shows how the run splits into segments."""
    return [((255, 120, 0) if (i // lps) % 2 == 0 else (0, 120, 255)) for i in range(n)]


def _markers(n, t, lps=5):
    """Counting step 1: dim white, with the first light of every segment red or green in
    turn (every 10th marker blue). Sent as a full-length frame, so the count isn't needed:
    the controller shows as many as it has. Number of markers = number of segments."""
    out = []
    for i in range(n):
        k = i // lps
        if i % lps:
            out.append(DIM_WHITE)
        else:
            out.append(BLUE if (k + 1) % 10 == 0 else RED if k % 2 == 0 else GREEN)
    return out


def _tail(n, t, lps=5, markers=1):
    """Counting step 2: the first markers-1 segments dim white, the rest red. The red lights
    are the last segment: lights = lps * (markers - 1) + red."""
    edge = lps * max(0, markers - 1)
    return [DIM_WHITE if i < edge else RED for i in range(n)]


# Counting tests send a full frame whatever the light count; reverse doesn't apply to them.
COUNTING = {"markers", "tail"}
# Tests about where light 1 really is: never reversed.
PHYSICAL = COUNTING | {"check"}

PATTERNS = {"identify": ("Blink the whole run", _identify, True),
            "markers": ("Count: segment markers", _markers, False),
            "tail": ("Count: last segment", _tail, False),
            "check": ("Check the count and light 1", _check, False),
            "ruler": ("Check the count", _ruler, False),
            "chase": ("Direction: dot from light 1", _chase, True),
            "rgb": ("Colours: red, green, blue", _rgb, False),
            "segments": ("Segment groups", _segments, False)}


def allowed_tests(caps):
    """Which tests a controller can show."""
    if caps.get("stream"):
        names = list(PATTERNS)
    elif caps.get("static") in ("lights", "palette"):
        names = ["identify", "rgb"]
    else:
        names = ["identify"]
    if caps.get("count") != "manual":
        names = [n for n in names if n not in COUNTING]
    return names


def _frame(name, lights, max_lights):
    """How many lights a test sends: counting tests the most the model takes, "check" the
    count plus EXTRA (orange), others the count."""
    if name in COUNTING:
        return max_lights
    if name == "check":
        return min(lights + EXTRA, max_lights)
    return lights


def _pattern(name, n, t, lps=5, markers=1, slow_fps=None, lights=None):
    if name == "identify" and slow_fps:
        return _identify_slow(n, t, slow_fps)
    if name == "check":
        return _check(n, t, lights)
    if name == "segments":
        return _segments(n, t, lps)
    if name == "markers":
        return _markers(n, t, lps)
    if name == "tail":
        return _tail(n, t, lps, markers)
    return PATTERNS[name][1](n, t)


def _cfg():
    return HOOKS["settings"]() if HOOKS["settings"] else None


def _live():
    s = _cfg()
    return s.live if s is not None else not settings.forced_dry()


def _server_tz():
    try:
        return str(dt.datetime.now().astimezone().tzinfo)
    except Exception:
        return "UTC"


# --- endpoints -----------------------------------------------------------------------------
@router.get("")
def state():
    s = _cfg()
    error = ""
    try:
        raw = settings.read_raw()
        config = (settings.public_config(settings.validate(raw)) if raw is not None
                  else settings.default_config())
    except ValueError as e:                        # broken config.json: start the wizard from it
        error = str(e)
        try:
            raw = settings.read_raw()
        except ValueError:
            raw = None
        config = {**settings.default_config(), **(raw or {})}
    cat = drivers.catalog()
    for d in cat:
        d["tests"] = allowed_tests(d["caps"])
        d["max_lights"] = {m: v.get("max_lights", 3000) for m, v in drivers.get(d["type"]).MODELS.items()}
        d["lights_per_segment"] = {m: v.get("lights_per_segment", 0) for m, v in drivers.get(d["type"]).MODELS.items()}
    return {"configured": bool(s and s.configured),
            "error": error,
            "config": config,
            "drivers": cat,
            "tests": {k: v[0] for k, v in PATTERNS.items()},
            "test_seconds": TEST_SECONDS,
            "live": _live(),
            "forced_dry": settings.forced_dry(),
            "home": settings.home(),
            "server_timezone": _server_tz(),
            "deep_scan_seconds": DEEP_SECONDS,
            "running": bool(s and s.configured)}


@router.post("/discover")
def discover(body: dict):
    """body: {types: ["govee", "wled", ...], targets: "192.168.2.0/24, 192.168.2.7", deep: false,
    expect: {"govee": 3}, known: {"govee": ["192.168.2.20"]}}. Read-only: controllers are only
    asked who they are. A deep scan keeps asking for up to DEEP_SECONDS and stops once it knows
    `expect` controllers of a kind (counting the `known` ones). Each type reports its own problems."""
    types = body.get("types") or [body.get("type", "govee")]
    deep = bool(body.get("deep"))
    expect, known = body.get("expect") or {}, body.get("known") or {}
    devices, problems = [], {}
    for t in types:
        drv = drivers.get(t)
        if not drv:
            problems[t] = "unknown controller type"
            continue
        ok, reason = drv.available()
        if not ok:
            problems[t] = reason
            continue
        try:
            devices += drv.discover(body.get("targets", ""), deep=deep, expect=int(expect.get(t) or 0),
                                    known=[str(ip) for ip in known.get(t) or []])
        except ValueError as e:
            problems[t] = str(e)
        except OSError as e:
            problems[t] = f"could not scan the network: {e}"
    log.info("setup %sscan (%s, %s): %d device(s)%s", "deep " if deep else "", ",".join(types),
             body.get("targets") or "this network",
             len(devices), f", problems: {problems}" if problems else "")
    if problems and not devices and len(types) == 1:
        raise HTTPException(400, next(iter(problems.values())))
    return {"devices": devices, "problems": problems}


@router.post("/probe")
def probe(body: dict):
    """Add by address: check the controller answers (and for Tuya, that the key works)."""
    drv = drivers.get(body.get("type", ""))
    if not drv:
        raise HTTPException(400, "pick the kind of controller")
    ok, reason = drv.available()
    if not ok:
        raise HTTPException(400, reason)
    info = dict(body)
    if not info.get("local_key") and info.get("id"):
        info["local_key"] = (settings.read_secrets().get(info["id"]) or {}).get("local_key", "")
    try:
        rows = drv.probe(info)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(503, f"no answer: {e}")
    return {"devices": rows}


def _test_controller(c):
    """A Controller for a test, from what the wizard posted (and a saved secret if the key
    wasn't typed again)."""
    drv = drivers.get(c.get("type", "govee"))
    if not drv or c.get("model") not in drv.MODELS:
        raise HTTPException(400, "pick a supported controller first")
    saved = settings.read_secrets().get(c.get("id") or "", {})
    try:
        opts, sec = drv.options(c, saved)
        probe_cfg = settings.validate({"controllers": [dict(c, id="test", enabled=True, **opts, **sec)],
                                       "runs": [{"name": "test", "controller": "test", "lights": 1}]}, secrets={})
    except ValueError as e:
        raise HTTPException(400, str(e).replace("controller 1 ", "").replace("controller 1: ", ""))
    pc = probe_cfg["controllers"][0]
    return drv, Controller("setup", pc["type"], pc["model"], pc["ip"], "", True, opts, sec)


@router.post("/test")
def test(body: dict):
    """body: {controller: {id?, type, model, ip, zone?, device_id?, version?, local_key?},
    lights, reverse, test, markers?}. Shows a test pattern on that one controller for
    TEST_SECONDS (or until /test/stop). Counting and "check" tests ignore reverse: they show
    where light 1 really is."""
    drv, ctrl = _test_controller(body.get("controller") or {})
    caps = drv.Kit.CAPS
    name = body.get("test")
    if name not in PATTERNS:
        raise HTTPException(400, "unknown test")
    if name not in allowed_tests(caps):
        raise HTTPException(400, f"this controller can't show the \"{PATTERNS[name][0]}\" test")
    counting = name in COUNTING
    model = drv.MODELS[ctrl.model]
    try:
        lights = model["max_lights"] if counting else int(body.get("lights"))
        markers = max(1, int(body.get("markers") or 1))
    except (TypeError, ValueError):
        raise HTTPException(400, "lights and markers must be numbers")
    if not 1 <= lights <= model["max_lights"]:
        raise HTTPException(400, f"lights must be between 1 and {model['max_lights']}")
    label, _, animated = PATTERNS[name]
    lps = model.get("lights_per_segment") or 5
    reverse = bool(body.get("reverse")) and name not in PHYSICAL
    kit = drivers.make_kit(ctrl, _live())
    slow = not caps.get("stream")
    count, lights = lights, _frame(name, lights, model["max_lights"])

    def render(t):
        cols = _pattern(name, lights, t, lps, markers, kit.slow_fps if slow else None, count)
        return cols[::-1] if reverse else cols

    where = (ctrl.ip, ctrl.options.get("zone", ""))
    if HOOKS["before_test"]:
        HOOKS["before_test"](ctrl.ip)             # stop what the dashboard streams there
    old = TESTS.pop(where, None)
    if old:
        old.stop()
    st = Streamer(kit, lights, 15)
    try:
        st.start_fn(f"test:{name}", render, animated, 100, seconds=TEST_SECONDS, slow_ok=True)
    except (ValueError, drivers.NotAllowed) as e:
        raise HTTPException(400, str(e))
    TESTS[where] = st
    log.info("setup test %s on %s (%d lights%s)", name, kit.tag, lights, ", reversed" if reverse else "")
    return {"ok": True, "live": kit.live, "label": label, "seconds": TEST_SECONDS, "lights_per_segment": lps,
            "frame_lights": lights, "restore": caps.get("restore"), "slow": slow}


@router.post("/test/stop")
def test_stop(body: dict):
    keys = [k for k in TESTS if not body.get("ip") or (k[0] == body["ip"] and
                                                       (not body.get("zone") or k[1] == body["zone"]))]
    for k in keys:
        st = TESTS.pop(k, None)
        if st:
            st.stop()
    return {"ok": True}


@router.post("/save")
def save(body: dict):
    """Validate and write config.json (and secrets.json), then restart with them."""
    try:
        clean = settings.save(body.get("config") or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    for st in list(TESTS.values()):
        st.stop()
    TESTS.clear()
    restarting = runtime.request_restart()
    return {"ok": True, "config": settings.public_config(clean), "restarting": restarting}


def preview_frames(name, lights, lps=5, seconds=3.0, fps=8, markers=1, frame=None):
    """Frames of a test pattern for the wizard's on-screen strip."""
    animated = PATTERNS[name][2]
    count = int(seconds * fps) if animated else 1
    n = frame or lights
    return [[f"#{r:02x}{g:02x}{b:02x}" for r, g, b in _pattern(name, n, k / fps, lps, markers, lights=lights)]
            for k in range(count)]


@router.post("/preview")
def preview(body: dict):
    name = body.get("test")
    if name not in PATTERNS:
        raise HTTPException(400, "unknown test")
    try:
        lights = max(1, min(3000, int(body.get("lights") or 50)))
        markers = max(1, int(body.get("markers") or 1))
    except (TypeError, ValueError):
        raise HTTPException(400, "lights must be a number")
    c = body.get("controller") or {}
    drv = drivers.get(c.get("type", "govee"))
    model = drv.MODELS.get(c.get("model"), {}) if drv else {}
    lps = model.get("lights_per_segment") or 5
    frame = _frame(name, lights, model.get("max_lights") or 3000) if name == "check" else None
    slow = drv and not drv.Kit.CAPS.get("stream")
    if slow and name == "identify":
        fps = drv.Kit.slow_fps
        frames = [[f"#{r:02x}{g:02x}{b:02x}" for r, g, b in _identify_slow(lights, k / 2, fps)] for k in range(8)]
        return {"frames": frames, "fps": 2, "animated": True}
    frames = preview_frames(name, lights, lps, seconds=math.ceil((lights + 8) / 8) if name == "chase" else 2.0,
                            markers=markers, frame=frame)
    if body.get("reverse") and name not in PHYSICAL:
        frames = [f[::-1] for f in frames]
    return {"frames": frames, "fps": 8, "animated": PATTERNS[name][2]}


# --- time and place ------------------------------------------------------------------------------
NO_SERVICE = "couldn't reach the ZIP lookup service; enter latitude and longitude instead"


def zip_lookup(code, country="us", fetch=None):
    """{lat, lon, place, zip} for a postal code, from zippopotam.us. fetch(url) -> bytes
    (tests pass their own). Raises HTTPException 400 (bad or unknown code) or 502 (no answer)."""
    code, country = str(code or "").strip(), str(country or "us").strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{0,9}", code):
        raise HTTPException(400, "type a ZIP code like 12345")
    if not re.fullmatch(r"[a-z]{2}", country):
        raise HTTPException(400, "pick a country")
    url = ZIP_URL.format(country=country, code=urllib.parse.quote(code))
    try:
        data = json.loads((fetch or _fetch)(url).decode("utf-8"))
        p = data["places"][0]
        lat, lon = round(float(p["latitude"]), 4), round(float(p["longitude"]), 4)
    except urllib.error.HTTPError as e:
        raise HTTPException(*((400, "ZIP code not found") if e.code == 404 else (502, NO_SERVICE))) from None
    except OSError:
        raise HTTPException(502, NO_SERVICE) from None
    except (KeyError, IndexError, TypeError, ValueError):     # not JSON, or no place in it
        raise HTTPException(400, "ZIP code not found") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "ZIP code not found")
    state = str(p.get("state abbreviation") or p.get("state") or "").strip()
    place = ", ".join(x for x in (str(p.get("place name") or "").strip(), state) if x)[:64]
    return {"lat": lat, "lon": lon, "place": place, "zip": code.upper()}


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "houselights-setup", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=ZIP_TIMEOUT) as r:
        return r.read()


@router.get("/zip")
def zip_code(code: str = "", country: str = "us"):
    """GET /api/setup/zip?code=12345&country=us -> {lat, lon, place, zip}."""
    return zip_lookup(code, country)


def sun_today(lat, lon, tz, day=None):
    """Sunrise, solar noon and sunset ("HH:MM", None in polar day or night) in time zone tz,
    and tz_ok: noon between 10:30 and 14:30 (otherwise the time zone is likely wrong)."""
    from astral import Observer
    from astral.sun import noon, sunrise, sunset
    try:
        zone = ZoneInfo(str(tz))
    except Exception:
        raise HTTPException(400, f"unknown time zone {tz!r}") from None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise HTTPException(400, "latitude and longitude must be numbers") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "latitude or longitude out of range")
    day = day or dt.datetime.now(zone).date()
    obs = Observer(latitude=lat, longitude=lon)

    def at(fn):
        try:
            return fn(obs, date=day, tzinfo=zone)
        except ValueError:                           # the sun doesn't rise or set that day
            return None
    n, rise, down = at(noon), at(sunrise), at(sunset)
    hm = (lambda t: t.strftime("%H:%M") if t else None)
    return {"sunrise": hm(rise), "sunset": hm(down), "noon": hm(n),
            "tz_ok": n is not None and dt.time(10, 30) <= n.time() <= dt.time(14, 30)}


@router.get("/sun")
def sun(lat: float, lon: float, tz: str):
    """GET /api/setup/sun?lat=..&lon=..&tz=America/Chicago -> today's sunrise and sunset there."""
    return sun_today(lat, lon, tz)
