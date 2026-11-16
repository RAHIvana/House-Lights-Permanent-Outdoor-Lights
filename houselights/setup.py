"""Setup wizard API (/api/setup/...): find controllers, play test patterns, save settings.

Used on the first start (no config.json yet) and later from the Settings tab. Test patterns
stop by themselves after TEST_SECONDS. Controllers that stream (Govee, WLED) go back to what
they showed when a test stops; Tuya lights are saved and put back; JellyFish can't be
(the wizard says so).
"""
import datetime as dt
import ipaddress
import json
import logging
import math
import os
import re
import select
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from . import drivers, runtime, settings
from .drivers import net
from .settings import Controller
from .stream import Streamer

log = logging.getLogger("houselights")
router = APIRouter(prefix="/api/setup")

TEST_SECONDS = 60
BLINK_S = 2.0                      # Blink test: one on-off cycle every 2 seconds
DEEP_SECONDS = 30                  # longest deep scan (Govee: keeps asking silent addresses)
TESTS = {}                    # (ip, zone) -> Streamer playing a test
TEST_LOCK = threading.Lock()  # one test start at a time (the stop of the old one, then the new)
SWITCHED = {}               # (ip, zone) -> kit switched on for the tests because it was off (else None)
HOOKS = {"before_test": None, "settings": None}     # set by app.py

RED, GREEN, BLUE, WHITE, OFF = (255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)
DIM_WHITE = (120, 120, 120)
ORANGE = (255, 110, 0)
EXTRA = 20                         # "check" test: orange lights past the last one, to spot a short count
ZIP_URL = "https://api.zippopotam.us/{country}/{code}"
ZIP_TIMEOUT = 5


# --- test patterns: fn(n, t) -> [rgb] * n, in the run's own light order ---------------------
def _identify(n, t):
    """The whole run blinks white: 1 s on, 1 s off, so it is easy to spot. Which run is this?"""
    return [WHITE if (t % BLINK_S) < BLINK_S / 2 else OFF] * n


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
    if not caps.get("pick"):                     # no segments to show (e.g. Govee "try" models)
        names = [n for n in names if n != "segments"]
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
    used = {(str(c.get("type") or "govee"), str(c.get("model") or "")) for c in config.get("controllers") or []
            if isinstance(c, dict)}
    for d in cat:
        d["tests"] = allowed_tests(d["caps"])
        infos = d["model_info"]                  # per model: label, tier, caps, limits, note, tests
        for t, m in used:                        # models in the config that aren't known by name
            if t == d["type"] and m not in infos and drivers.model_info(t, m):
                infos[m] = drivers.model_info(t, m)
        for i in [*infos.values(), *d["tiers"].values()]:
            i["tests"] = allowed_tests(i["caps"])
        d["max_lights"] = {m: i["max_lights"] for m, i in infos.items()}
        d["lights_per_segment"] = {m: i["lights_per_segment"] for m, i in infos.items()}
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
        if t == "tuya":                           # found even without tinytuya (then not usable yet)
            try:
                rows, problem = tuya_scan(body.get("targets", ""), deep=deep, expect=int(expect.get(t) or 0),
                                          known=[str(ip) for ip in known.get(t) or []])
            except ValueError as e:
                rows, problem = [], str(e)
            devices += rows
            if problem:
                problems[t] = problem
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


# --- Tuya / Smart Life: is anything there, with or without tinytuya? ----------------------------
TUYA_UDP_PORTS = (6666, 6667)      # Tuya devices announce themselves here every few seconds
TUYA_TCP_PORT = 6668               # and take local commands here
TUYA_LISTEN = (6.0, 20.0)          # seconds to listen: quick scan, deep scan
TUYA_FRAMES = (b"\x00\x00\x55\xaa", b"\x00\x00\x66\x99")    # how Tuya messages start (3.1-3.4, 3.5)
TUYA_NOT_INSTALLED = "Smart Life / Tuya device. If it's your lights, install tinytuya to use it"


def _tuya_announce(data):
    """What a Tuya broadcast says about the device ({gwId, version, ...}), when it can be read
    (port 6666 sends plain JSON; 6667 is encrypted, so then {})."""
    start, end = data.find(b"{"), data.rfind(b"}")
    if start < 0 or end < start:
        return {}
    try:
        d = json.loads(data[start:end + 1].decode("utf-8", "replace"))
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def tuya_listen(seconds, ports=TUYA_UDP_PORTS, bind="", expect=0):
    """Listen for Tuya broadcasts for up to `seconds` (sends nothing): {ip: announce}. Stops
    early at `expect` devices. Only devices on this computer's own network section are heard.
    Raises OSError when none of the ports can be opened."""
    socks, errors = [], []
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if os.name != "nt":                   # Windows: sharing the port would hide the broadcasts
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((bind, p))
        except OSError as e:
            s.close()
            errors.append(f"{p} ({e.strerror or e})")
            continue
        socks.append(s)
    if not socks:
        raise OSError(f"can't listen for Tuya devices on UDP port {' or '.join(errors)}; is another program using it?")
    found, end = {}, time.time() + seconds
    try:
        while time.time() < end and not (expect and len(found) >= expect):
            ready, _, _ = select.select(socks, [], [], max(0.0, min(0.2, end - time.time())))
            for s in ready:
                try:
                    data, (ip, _) = s.recvfrom(4096)
                except OSError:
                    continue
                if data[:4] in TUYA_FRAMES:
                    found.setdefault(ip, {}).update(_tuya_announce(data))
    finally:
        for s in socks:
            s.close()
    return found


def tuya_connect(ips, port=TUYA_TCP_PORT, timeout=0.8):
    """The addresses that accept a connection on Tuya's command port (connects, sends nothing)."""
    def one(ip):
        socket.create_connection((ip, port), timeout=timeout).close()
        return True
    return set(net.probe_many(one, list(ips), workers=32))


def _same_section(targets):
    """Typed nothing (this network), or typed an address on this computer's own network
    section: only then can Tuya broadcasts be heard."""
    from .drivers.govee import expand_targets
    if not str(targets or "").strip():
        return True
    nets = [ipaddress.ip_network(n) for n in net.local_networks()]
    return any(ipaddress.ip_address(ip) in n for ip in expand_targets(targets) for n in nets)


def _tuya_row(ip, info, usable, probable=False):
    dev = str(info.get("gwId") or info.get("devId") or info.get("id") or "")
    row = {"ip": ip, "type": "tuya", "model": "Tuya light", "device_id": dev,
           "version": str(info.get("version") or "3.3"), "device_tail": dev[-5:], "lights": None,
           "label": "Smart Life / Tuya device" + (" (probably)" if probable else ""), "probable": probable}
    if usable:
        row.update(supported=True, needs_key=True)
    else:
        row.update(supported=False, reason=TUYA_NOT_INSTALLED, install=drivers.get("tuya").INSTALL)
    return row


def tuya_scan(targets="", deep=False, expect=0, known=(), listen=None, connect=None, usable=None, same_section=None):
    """Tuya / Smart Life devices: (rows, problem). With tinytuya, its own discovery; without it,
    listening for their broadcasts tells us they're there (rows not usable until tinytuya is
    installed). Typed addresses are also tried on the command port ("probably Tuya").
    listen, connect, usable, same_section: stand-ins for the tests."""
    from .drivers.govee import expand_targets
    tuya = drivers.get("tuya")
    usable = tuya.available()[0] if usable is None else usable
    listen, connect = listen or tuya_listen, connect or tuya_connect
    ips = expand_targets(targets) if str(targets or "").strip() else []
    rows, problem = {}, ""
    if (same_section or _same_section)(targets):
        try:
            if usable:
                for r in tuya.discover(targets, deep=deep, expect=expect, known=known):
                    rows[r["ip"]] = r
            else:
                for ip, info in listen(TUYA_LISTEN[1 if deep else 0], expect=expect).items():
                    rows[ip] = _tuya_row(ip, info, False)
        except OSError as e:
            problem = str(e)
    rest = [ip for ip in ips if ip not in rows and ip not in set(known)]
    for ip in sorted(connect(rest), key=socket.inet_aton):
        rows[ip] = _tuya_row(ip, {}, usable, probable=True)
    return sorted(rows.values(), key=lambda r: socket.inet_aton(r["ip"])), problem


# --- add by address: which kind of controller is there? ---------------------------------------
def _ask(kind):
    def fn(ip):
        try:
            return drivers.get(kind).probe({"ip": ip})
        except (ValueError, OSError):
            return []
    return fn


def _ask_tuya(ip):
    return [_tuya_row(ip, {}, drivers.get("tuya").available()[0], probable=True)] if tuya_connect([ip]) else []


IDENTIFY_GRACE = 1.0
IDENTIFY = {"govee": _ask("govee"), "wled": _ask("wled"), "jellyfish": _ask("jellyfish"), "tuya": _ask_tuya}


def _what(kind, rows):
    if kind == "govee":
        r = rows[0]
        return f"a Govee controller ({r.get('label') or r.get('model')})"
    if kind == "wled":
        return "a WLED controller"
    if kind == "jellyfish":
        return f"a JellyFish controller with {len(rows)} zone{'' if len(rows) == 1 else 's'}" if rows else "a JellyFish controller"
    return "probably a Tuya / Smart Life device"


def identify(ip, checks=None):
    """Ask one address as every kind of controller at once (read-only: who are you?).
    {devices, kinds, message}. checks: {kind: fn(ip) -> rows}, stand-ins for the tests."""
    from concurrent.futures import ThreadPoolExecutor
    from .drivers.govee import expand_targets
    try:
        one = expand_targets(ip)
    except ValueError:
        one = []
    if len(one) != 1 or "/" in str(ip):
        raise HTTPException(400, "type one address, like 192.168.2.50")
    ip, checks = one[0], checks or IDENTIFY
    pool = ThreadPoolExecutor(max_workers=len(checks))
    jobs = {kind: pool.submit(fn, ip) for kind, fn in checks.items()}
    pool.shutdown(wait=False)
    # Once one kind has answered, the others get IDENTIFY_GRACE seconds more, not their whole
    # timeout (a Govee check otherwise keeps asking for 6 s).
    end = time.time() + 30
    while time.time() < end and not all(j.done() for j in jobs.values()):
        if any(j.done() and not j.exception() and j.result() for j in jobs.values()):
            end = min(end, time.time() + IDENTIFY_GRACE)
        time.sleep(0.05)
    rows, kinds = [], []
    for kind, job in jobs.items():
        try:
            got = (job.result() if job.done() else []) or []
        except Exception:                      # nothing of that kind there
            got = []
        if got:
            rows += got
            kinds.append(kind)
    if not kinds:
        message = (f"Nothing answered at {ip}. Is the controller on, and is that its address (its app or "
                   "your router lists it)? Govee: is LAN Control on in the Govee Home app?")
    else:
        message = f"{ip} is " + " and ".join(_what(k, [r for r in rows if r["type"] == k]) for k in kinds) + "."
    return {"devices": rows, "kinds": kinds, "message": message}


@router.post("/identify")
def identify_endpoint(body: dict):
    """Add by address: body {ip}. Tries Govee, WLED, JellyFish and Tuya on that one address."""
    out = identify(str(body.get("ip") or "").strip())
    log.info("setup identify %s: %s", body.get("ip"), ",".join(out["kinds"]) or "nothing")
    return out


def _test_controller(c):
    """A Controller for a test, from what the wizard posted (and a saved secret if the key
    wasn't typed again)."""
    drv = drivers.get(c.get("type", "govee"))
    if not drv or not drivers.model_info(c.get("type", "govee"), c.get("model")):
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
    model = drivers.model_info(ctrl.type, ctrl.model)          # per model: caps, limits, segments
    caps = model["caps"]
    name = body.get("test")
    if name not in PATTERNS:
        raise HTTPException(400, "unknown test")
    if name not in allowed_tests(caps):
        raise HTTPException(400, f"this controller can't show the \"{PATTERNS[name][0]}\" test")
    counting = name in COUNTING
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
    with TEST_LOCK:                               # two quick presses: the second replaces the first
        if HOOKS["before_test"]:
            HOOKS["before_test"](ctrl.ip)         # stop what the dashboard streams there
        old = TESTS.pop(where, None)
        if old:
            old.stop()
        st = Streamer(kit, lights, 15)
        try:
            if not slow:
                switch_on(drv, kit, where)
            st.start_fn(f"test:{name}", render, animated, 100, seconds=TEST_SECONDS, slow_ok=True)
        except (ValueError, drivers.NotAllowed) as e:
            raise HTTPException(400, str(e))
        except OSError as e:
            raise HTTPException(502, f"couldn't reach the controller: {e}")
        TESTS[where] = st
    log.info("setup test %s on %s (%d lights%s)", name, kit.tag, lights, ", reversed" if reverse else "")
    return {"ok": True, "live": kit.live, "label": label, "seconds": TEST_SECONDS, "lights_per_segment": lps,
            "frame_lights": lights, "restore": caps.get("restore"), "slow": slow, "tier": model.get("tier"),
            "stream_untested": bool(caps.get("stream_untested")) and not slow}


def switch_on(drv, kit, where):
    """A stream shows nothing on a controller that is switched off, so switch it on first.
    The first time, ask whether it was off (when the controller can say), so switch_off_tested
    can put it back off when the tests stop. No answer: it stays on afterwards."""
    if where not in SWITCHED:
        st = None
        if kit.live and kit.caps.get("status"):
            try:
                st = drv.read_status([kit]).get(kit.c.id)
            except Exception:                     # no answer is fine: just switch it on
                st = None
        SWITCHED[where] = kit if (st or {}).get("onOff") == 0 else None
    kit.power(True)


def switch_off_tested(keys=None):
    """Switch off again the controllers that were off before their tests."""
    for k in [k for k in SWITCHED if keys is None or k in keys]:
        kit = SWITCHED.pop(k)
        if kit is not None:
            try:
                kit.power(False)
                log.info("setup tests done on %s: switched it off again", kit.tag)
            except Exception as e:
                log.warning("couldn't switch %s off again: %s", kit.tag, e)


@router.post("/test/stop")
def test_stop(body: dict):
    match = (lambda k: not body.get("ip") or (k[0] == body["ip"] and (not body.get("zone") or k[1] == body["zone"])))
    for k in [k for k in TESTS if match(k)]:
        st = TESTS.pop(k, None)
        if st:
            st.stop()
    switch_off_tested({k for k in SWITCHED if match(k)})
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
    switch_off_tested()
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
    model = (drivers.model_info(c.get("type", "govee"), c.get("model")) if drv else None) or {}
    lps = model.get("lights_per_segment") or 5
    frame = _frame(name, lights, model.get("max_lights") or 3000) if name == "check" else None
    slow = drv and not (model.get("caps") or drv.Kit.CAPS).get("stream")
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
