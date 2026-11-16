"""Setup wizard API (/api/setup/...): find controllers, play test patterns, save settings.

Used on the first start (no config.json yet) and later from the Settings tab. Test patterns
stream to the controller being set up and stop by themselves after TEST_SECONDS; when
streaming stops, the controller goes back to what it showed before.
"""
import datetime as dt
import logging
import math

from fastapi import APIRouter, HTTPException

from . import drivers, runtime, settings
from .settings import Controller
from .stream import Streamer

log = logging.getLogger("houselights")
router = APIRouter(prefix="/api/setup")

TEST_SECONDS = 60
TESTS = {}                    # ip -> Streamer playing a test
HOOKS = {"before_test": None, "settings": None}     # set by app.py

RED, GREEN, BLUE, WHITE, OFF = (255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)


# --- test patterns: fn(n, t) -> [rgb] * n, in the run's own light order ---------------------
def _identify(n, t):
    """The whole run blinks white once a second: which run is this?"""
    return [WHITE if (t % 1.0) < 0.5 else OFF] * n


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


DIM_WHITE = (120, 120, 120)


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

PATTERNS = {"identify": ("Blink the whole run", _identify, True),
            "markers": ("Count: segment markers", _markers, False),
            "tail": ("Count: last segment", _tail, False),
            "ruler": ("Check the count", _ruler, False),
            "chase": ("Direction: dot from light 1", _chase, True),
            "rgb": ("Colours: red, green, blue", _rgb, False),
            "segments": ("Segment groups", _segments, False)}


def _cfg():
    return HOOKS["settings"]() if HOOKS["settings"] else None


def _live():
    s = _cfg()
    return s.live if s is not None else not settings.forced_dry()


# --- endpoints -----------------------------------------------------------------------------
@router.get("")
def state():
    s = _cfg()
    error = ""
    try:
        raw = settings.read_raw()
        config = settings.validate(raw) if raw is not None else settings.default_config()
    except ValueError as e:                        # broken config.json: start the wizard from it
        error = str(e)
        try:
            raw = settings.read_raw()
        except ValueError:
            raw = None
        config = {**settings.default_config(), **(raw or {})}
    return {"configured": bool(s and s.configured),
            "error": error,
            "config": config,
            "drivers": drivers.catalog(),
            "tests": {k: v[0] for k, v in PATTERNS.items()},
            "test_seconds": TEST_SECONDS,
            "live": _live(),
            "forced_dry": settings.forced_dry(),
            "home": settings.home(),
            "server_timezone": _server_tz(),
            "running": bool(s and s.configured)}


def _server_tz():
    try:
        return str(dt.datetime.now().astimezone().tzinfo)
    except Exception:
        return "UTC"


@router.post("/discover")
def discover(body: dict):
    """body: {type: "govee", targets: "192.168.1.0/24, 10.0.0.7"}. Read-only: devices are only
    asked to identify themselves."""
    drv = drivers.get(body.get("type", "govee"))
    if not drv:
        raise HTTPException(400, "unknown controller type")
    try:
        found = drv.discover(body.get("targets", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(503, f"could not scan the network: {e}")
    log.info("setup scan (%s): %d device(s)", body.get("targets") or "this network", len(found))
    return {"devices": found}


@router.post("/test")
def test(body: dict):
    """body: {controller: {type, model, ip}, lights, reverse, test}. Streams a test pattern
    to that one controller for TEST_SECONDS (or until /test/stop)."""
    c = body.get("controller") or {}
    drv = drivers.get(c.get("type", "govee"))
    if not drv or c.get("model") not in drv.MODELS:
        raise HTTPException(400, "pick a supported controller first")
    name = body.get("test")
    if name not in PATTERNS:
        raise HTTPException(400, "unknown test")
    counting = name in COUNTING
    try:
        model_max = drv.MODELS[c["model"]]["max_lights"]
        probe = settings.validate({"controllers": [dict(c, id="test", enabled=True)],
                                   "runs": [{"name": "test", "controller": "test",
                                             "lights": model_max if counting else body.get("lights")}]})
    except ValueError as e:
        raise HTTPException(400, str(e).replace("run 1 (test) ", "").replace("controller 1: ", ""))
    try:
        markers = max(1, int(body.get("markers") or 1))
    except (TypeError, ValueError):
        raise HTTPException(400, "markers must be a number")
    pc = probe["controllers"][0]
    lights = probe["runs"][0]["lights"]
    label, fn, animated = PATTERNS[name]
    lps = drv.MODELS[pc["model"]].get("lights_per_segment") or 5
    reverse = bool(body.get("reverse")) and not counting

    def render(t):
        cols = _pattern(name, lights, t, lps, markers)
        return cols[::-1] if reverse else cols

    if HOOKS["before_test"]:
        HOOKS["before_test"](pc["ip"])            # stop what the dashboard streams there
    old = TESTS.pop(pc["ip"], None)
    if old:
        old.stop()
    kit = drivers.make_kit(Controller("setup", pc["type"], pc["model"], pc["ip"], "", True), _live())
    st = Streamer(kit, lights, 15)
    try:
        st.start_fn(f"test:{name}", render, animated, 100, seconds=TEST_SECONDS)
    except (ValueError, drivers.NotAllowed) as e:
        raise HTTPException(400, str(e))
    TESTS[pc["ip"]] = st
    log.info("setup test %s on %s (%d lights%s)", name, pc["ip"], lights, ", reversed" if reverse else "")
    return {"ok": True, "live": kit.live, "label": label, "seconds": TEST_SECONDS, "lights_per_segment": lps,
            "frame_lights": lights}


@router.post("/test/stop")
def test_stop(body: dict):
    ips = [body["ip"]] if body.get("ip") else list(TESTS)
    for ip in ips:
        st = TESTS.pop(ip, None)
        if st:
            st.stop()
    return {"ok": True}


@router.post("/save")
def save(body: dict):
    """Validate and write config.json, then restart with it."""
    try:
        clean = settings.save(body.get("config") or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    for st in list(TESTS.values()):
        st.stop()
    TESTS.clear()
    restarting = runtime.request_restart()
    return {"ok": True, "config": clean, "restarting": restarting}


def _pattern(name, n, t, lps=5, markers=1):
    if name == "segments":
        return _segments(n, t, lps)
    if name == "markers":
        return _markers(n, t, lps)
    if name == "tail":
        return _tail(n, t, lps, markers)
    return PATTERNS[name][1](n, t)


def preview_frames(name, lights, lps=5, seconds=3.0, fps=8, markers=1):
    """Frames of a test pattern for the wizard's on-screen strip."""
    animated = PATTERNS[name][2]
    count = int(seconds * fps) if animated else 1
    return [[f"#{r:02x}{g:02x}{b:02x}" for r, g, b in _pattern(name, lights, k / fps, lps, markers)]
            for k in range(count)]


@router.post("/preview")
def preview(body: dict):
    name = body.get("test")
    if name not in PATTERNS:
        raise HTTPException(400, "unknown test")
    try:
        lights = max(1, min(255, int(body.get("lights") or 50)))
    except (TypeError, ValueError):
        raise HTTPException(400, "lights must be a number")
    c = body.get("controller") or {}
    drv = drivers.get(c.get("type", "govee"))
    lps = (drv.MODELS.get(c.get("model"), {}).get("lights_per_segment") if drv else None) or 5
    animated = PATTERNS[name][2]
    try:
        markers = max(1, int(body.get("markers") or 1))
    except (TypeError, ValueError):
        markers = 1
    frames = preview_frames(name, lights, lps, seconds=math.ceil((lights + 8) / 8) if name == "chase" else 2.0,
                            markers=markers)
    if body.get("reverse") and name not in COUNTING:
        frames = [f[::-1] for f in frames]
    return {"frames": frames, "fps": 8, "animated": animated}
