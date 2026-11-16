"""FastAPI app: JSON API under /api, the page at /.

With no settings yet (first start) there are no runs: the page opens the setup wizard
(setup.py), which writes config.json and restarts the server.
"""
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import drivers, settings, setup
from . import patterns as P
from .drivers import NotAllowed
from .schedule import Scheduler
from .stream import Streamer

log = logging.getLogger("houselights")

S = settings.load()
os.makedirs(settings.home(), exist_ok=True)
# Practice (dry) runs keep their own "last applied" record so they never pretend to be the real lights.
STATE_FILE = settings.path(f"state{'' if S.live else '-dry'}.json")
KITS = {cid: drivers.make_kit(c, S.live) for cid, c in S.controllers.items()}
STREAMS = {sid: Streamer(KITS[s.controller.id], s.lights, S.stream_fps) for sid, s in S.sections.items()}
POOL = ThreadPoolExecutor(max_workers=4)
JOBS = {}
STATE_LOCK = threading.Lock()

if S.configured:
    log.info("start: mode=%s, %d run(s): %s", S.mode.upper(), len(S.sections),
             ", ".join(f"{s.name} ({s.controller.model} {s.controller.ip}, {s.lights} lights)" for s in S.sections.values()))
else:
    log.info("start: no settings yet in %s; open the page to run the setup wizard", settings.home())


# --- assumed state (segments are write-only on the kits) ----------------------------
def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


STATE = _load_state()


def _remember(section_id, **kw):
    with STATE_LOCK:
        st = STATE.setdefault(section_id, {})
        st.update(kw, updated=time.strftime("%Y-%m-%d %H:%M:%S"), mode=S.mode)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(STATE, f, indent=1)
        os.replace(tmp, STATE_FILE)


# --- helpers ---------------------------------------------------------------------------
def _section(sid):
    """A section about to receive a command. Commands from the page count as changes by hand."""
    sec = S.sections.get(sid)
    if not sec:
        raise HTTPException(404, f"no section {sid}")
    if not sec.enabled:
        raise HTTPException(409, f"{sec.name} is disabled (controller {sec.controller.id} not enabled)")
    _manual(sid)
    return sec, KITS[sec.controller.id]


# Set while the scheduler itself calls the endpoint functions below.
_BY_SCHEDULE = threading.local()


def _manual(sid):
    if not getattr(_BY_SCHEDULE, "on", False):
        SCHED.manual(sid)


def _run(fn):
    try:
        return fn()
    except NotAllowed as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _stop_stream(sid):
    """Any direct command takes the kit out of per-light streaming first."""
    if STREAMS[sid].playing:
        STREAMS[sid].stop()
        _remember(sid, streaming=None)


def _start_job(sec, kit, label, calls):
    """calls: [(rgb, [segments])]. One packet each, serialised per controller."""
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "section": sec.id, "label": label, "status": "queued",
           "total": len(calls), "done": 0, "error": None, "cancel": False,
           "started": time.time(), "mode": S.mode, "transport": "lan"}
    JOBS[jid] = job

    def work():
        with kit.lock:
            job["status"] = "running"
            try:
                for call in calls:
                    if job["cancel"]:
                        job["status"] = "cancelled"
                        return
                    if callable(call):                      # e.g. a whole frame at once
                        call()
                    else:
                        rgb, segs = call
                        kit.segments(segs, rgb, sec.segments)
                    job["done"] += 1
                job["status"] = "done"
            except Exception as e:
                job["status"], job["error"] = "error", str(e)
                log.error("job %s failed: %s", jid, e)
            finally:
                job["finished"] = time.time()

    POOL.submit(work)
    return {k: v for k, v in job.items() if k != "cancel"}


# --- API ---------------------------------------------------------------------------------
app = FastAPI(title="House Lights", docs_url=None, redoc_url=None)
app.include_router(setup.router)


@app.middleware("http")
async def no_cache(request, call_next):
    """Small LAN app that changes often: always revalidate, so a restart shows new code."""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.on_event("startup")
def _startup():
    SCHED.start()


@app.on_event("shutdown")
def _shutdown():
    SCHED.stop()
    for st in [*STREAMS.values(), *setup.TESTS.values()]:     # take controllers out of streaming mode
        st.stop()


@app.get("/api/config")
def config():
    return {"configured": S.configured,
            "mode": S.mode,
            "stream_fps": S.stream_fps,
            "timezone": S.timezone,
            "location": bool(S.location),
            "home": settings.home(),
            "controllers": [{"id": c.id, "type": c.type, "model": c.model, "ip": c.ip, "name": c.name,
                             "enabled": c.enabled} for c in S.controllers.values()],
            "sections": [s.public() for s in S.sections.values()],
            "patterns": P.catalogue(),
            "categories": P.CATEGORIES}


LAST_LAN = {}                     # last status per controller id, for the fast read below


@app.get("/api/status")
def status(lan: bool = True):
    """lan=false skips asking the kits (up to ~2.4 s when one is streaming and doesn't
    answer) and reuses the last answers: the page uses it right after a command."""
    if lan:
        LAST_LAN.update(drivers.read_status([KITS[s.controller.id] for s in S.sections.values() if s.enabled]))
    return {"sections": {sid: {"lan": LAST_LAN.get(s.controller.id) if s.enabled else None,
                               "assumed": STATE.get(sid),
                               "stream": STREAMS[sid].state if STREAMS[sid].playing else None}
                         for sid, s in S.sections.items()}}


class Power(BaseModel):
    on: bool


class Brightness(BaseModel):
    value: int


class Colour(BaseModel):
    color: str | None = None
    kelvin: int | None = None


class PatternReq(BaseModel):
    pattern: str
    params: dict = {}


class PlayReq(BaseModel):
    pattern: str
    params: dict = {}
    level: int = 100


class PlayAllReq(PlayReq):
    sections: list[str] | None = None
    per_section: dict = {}           # optional {section id: params} overrides


class Segments(BaseModel):
    segments: list[int]
    color: str


@app.post("/api/sections/{sid}/power")
def power(sid: str, body: Power):
    sec, kit = _section(sid)
    if not body.on:
        _stop_stream(sid)
    _run(lambda: kit.power(body.on))
    _remember(sid, power=body.on)
    return {"ok": True, "mode": S.mode}


@app.post("/api/sections/{sid}/brightness")
def brightness(sid: str, body: Brightness):
    sec, kit = _section(sid)
    _run(lambda: kit.brightness(body.value))
    _remember(sid, brightness=body.value)
    return {"ok": True, "mode": S.mode}


@app.post("/api/sections/{sid}/color")
def colour(sid: str, body: Colour):
    sec, kit = _section(sid)
    _stop_stream(sid)
    if body.kelvin:
        _run(lambda: kit.kelvin(body.kelvin))
        _remember(sid, kelvin=body.kelvin, segments=None, pattern=None, color=None)
    elif body.color:
        rgb = _run(lambda: P.hex_to_rgb(body.color))
        _run(lambda: kit.color(rgb))
        _remember(sid, color=P.rgb_to_hex(rgb), kelvin=None,
                  segments=[P.rgb_to_hex(rgb)] * sec.used_segments, pattern=None)
    else:
        raise HTTPException(400, "give color or kelvin")
    return {"ok": True, "mode": S.mode}


def _segments_for(sec, lights):
    """What Apply sends: (colours as shown, which are rounded, calls). Controllers that take a
    whole frame get one call; the others one packet per colour group of segments."""
    kit = KITS[sec.controller.id]
    if sec.caps.get("static") in ("lights", "palette"):
        shown = [tuple(c) for c in kit.preview_static(lights)]
        mixed = [tuple(a) != tuple(b) for a, b in zip(shown, lights)]
        return shown, mixed, [lambda: kit.show_lights(shown)]
    segs, mixed = P.quantise(lights, sec.used_segments, sec.lights_per_segment)
    return segs, mixed, P.plan_calls(segs)


def _can_stream(sec):
    return bool(sec.caps.get("stream"))


@app.post("/api/sections/{sid}/preview")
def preview(sid: str, body: PatternReq, seconds: float = 8.0, fps: int = 12):
    """Static: one frame plus its segment version. Animated: also `frames` for the 3D view."""
    sec = S.sections.get(sid)
    if not sec:
        raise HTTPException(404, f"no section {sid}")
    pat = _run(lambda: P.get(body.pattern))
    lights = _run(lambda: P.frame(body.pattern, sec.lights, body.params, 0.0, sec.reverse,
                                  sec.lights_per_segment or 5))
    segs, mixed, calls = _segments_for(sec, lights)
    one = len(calls) == 1
    out = {"animated": bool(pat.get("animated")) and _can_stream(sec),
           "lights": [P.rgb_to_hex(c) for c in lights],
           "segments": [P.rgb_to_hex(c) for c in segs],
           "mixed": mixed,
           "reachable": sec.reachable,
           "path": "lan",
           "calls": len(calls),
           "estimate_s": 1 if one else round(len(calls) * 0.3),
           "still": out_still(sec)}
    if out["animated"]:
        seconds, fps = max(1.0, min(seconds, 20.0)), max(4, min(fps, 20))
        out["fps"] = fps
        out["frames"] = [[P.rgb_to_hex(c) for c in P.frame(body.pattern, sec.lights, body.params,
                                                            k / fps, sec.reverse)]
                         for k in range(int(seconds * fps))]
    return out


def out_still(sec):
    """True when animated themes can only be shown as a still picture on this run."""
    return not _can_stream(sec)


@app.post("/api/sections/{sid}/pattern")
def apply_pattern(sid: str, body: PatternReq, still: bool = False):
    """Static patterns as segment colours (persist on the controller). Animated ones need
    /play, except as a still picture (still=true) on controllers that can't stream."""
    sec, kit = _section(sid)
    if _run(lambda: P.is_animated(body.pattern)) and not (still and not _can_stream(sec)):
        raise HTTPException(400, "animated themes play per light: use Play live")
    _stop_stream(sid)
    lights = _run(lambda: P.frame(body.pattern, sec.lights, body.params, 0.0, sec.reverse,
                                  sec.lights_per_segment or 5))
    segs, mixed, calls = _segments_for(sec, lights)
    seg_hex = [P.rgb_to_hex(c) for c in segs]
    if len(calls) == 1 and not callable(calls[0]):     # one colour: whole controller
        _run(lambda: kit.color(calls[0][0]))
        _remember(sid, segments=seg_hex, pattern=body.pattern, params=body.params,
                  color=seg_hex[0], kelvin=None)
        return {"ok": True, "path": "lan", "mode": S.mode}
    job = _start_job(sec, kit, P.get(body.pattern)["label"], calls)
    _remember(sid, segments=seg_hex, pattern=body.pattern, params=body.params, color=None, kelvin=None)
    return {"ok": True, "path": "lan", "job": job, "mode": S.mode}


@app.post("/api/sections/{sid}/segments")
def set_segments(sid: str, body: Segments):
    sec, kit = _section(sid)
    if not sec.caps.get("pick"):
        raise HTTPException(409, f"{sec.name}: this controller can't colour segments one by one")
    rgb = _run(lambda: P.hex_to_rgb(body.color))
    segs = sorted(set(body.segments))
    if not segs or segs[0] < 0 or segs[-1] >= sec.used_segments:
        raise HTTPException(400, f"segments must be within 0..{sec.used_segments - 1}")
    _stop_stream(sid)
    job = _start_job(sec, kit, f"{len(segs)} segment(s) {body.color}", [(list(rgb), segs)])
    prev = (STATE.get(sid) or {}).get("segments") or [None] * sec.used_segments
    prev = (prev + [None] * sec.used_segments)[:sec.used_segments]
    for s in segs:
        prev[s] = P.rgb_to_hex(rgb)
    _remember(sid, segments=prev, pattern="custom", color=None, kelvin=None)
    return {"ok": True, "job": job, "mode": S.mode}


@app.post("/api/sections/{sid}/play")
def play(sid: str, body: PlayReq):
    """Stream one colour per light (static or animated) until stopped."""
    sec, kit = _section(sid)
    _run(lambda: P.frame(body.pattern, sec.lights, body.params))          # validate first
    if not _can_stream(sec):                                              # show it as a still picture
        r = apply_pattern(sid, PatternReq(pattern=body.pattern, params=body.params), still=True)
        return {**r, "still": True}
    _run(lambda: kit.power(True))                                         # streaming into a dark kit shows nothing
    _run(lambda: STREAMS[sid].start(body.pattern, body.params, body.level, sec.reverse))
    _remember(sid, power=True, streaming={"pattern": body.pattern, "params": body.params, "level": body.level})
    return {"ok": True, "mode": S.mode, "stream": STREAMS[sid].state}


@app.post("/api/sections/{sid}/stop")
def stop(sid: str):
    _section(sid)
    _stop_stream(sid)
    return {"ok": True, "mode": S.mode}


@app.post("/api/play-all")
def play_all(body: PlayAllReq):
    started, skipped, still = [], {}, []
    for sid, sec in S.sections.items():
        if body.sections and sid not in body.sections:
            continue
        if not sec.enabled:
            skipped[sid] = "disabled"
            continue
        params = body.per_section.get(sid, body.params)
        _manual(sid)
        if not _can_stream(sec):
            try:
                apply_pattern(sid, PatternReq(pattern=body.pattern, params=params), still=True)
                still.append(sid)
            except HTTPException as e:
                skipped[sid] = e.detail
            continue
        try:
            P.frame(body.pattern, sec.lights, params)
            KITS[sec.controller.id].power(True)
            STREAMS[sid].start(body.pattern, params, body.level, sec.reverse)
            _remember(sid, power=True, streaming={"pattern": body.pattern, "params": params, "level": body.level})
            started.append(sid)
        except (ValueError, NotAllowed) as e:
            skipped[sid] = str(e)
    return {"ok": bool(started or still), "started": started, "still": still, "skipped": skipped, "mode": S.mode}


@app.post("/api/stop-all")
def stop_all():
    for sid in S.sections:
        _manual(sid)
        _stop_stream(sid)
    return {"ok": True, "mode": S.mode}


class PowerAll(BaseModel):
    on: bool
    sections: list[str] | None = None


@app.post("/api/power-all")
def power_all(body: PowerAll):
    done, skipped = [], {}
    for sid, sec in S.sections.items():
        if body.sections and sid not in body.sections:
            continue
        if not sec.enabled:
            skipped[sid] = "disabled"
            continue
        _manual(sid)
        if not body.on:
            _stop_stream(sid)
        try:
            KITS[sec.controller.id].power(body.on)
            _remember(sid, power=body.on)
            done.append(sid)
        except (ValueError, NotAllowed, OSError) as e:
            skipped[sid] = str(e)
    return {"ok": bool(done), "done": done, "skipped": skipped, "mode": S.mode}


class ApplyAll(BaseModel):
    pattern: str
    params: dict = {}
    sections: list[str] | None = None


@app.post("/api/apply-all")
def apply_all(body: ApplyAll):
    """A static theme as segment colours on several kits (each kit's own job)."""
    if _run(lambda: P.is_animated(body.pattern)):
        raise HTTPException(400, "animated themes play per light: use Play live")
    jobs, skipped = {}, {}
    for sid, sec in S.sections.items():
        if body.sections and sid not in body.sections:
            continue
        if not sec.enabled:
            skipped[sid] = "disabled"
            continue
        r = apply_pattern(sid, PatternReq(pattern=body.pattern, params=body.params))
        jobs[sid] = r.get("job", {}).get("id") if r.get("job") else r.get("path")
    return {"ok": bool(jobs), "jobs": jobs, "skipped": skipped, "mode": S.mode}


@app.post("/api/sections/{sid}/restore")
def restore(sid: str):
    sec, kit = _section(sid)
    _stop_stream(sid)
    b = sec.baseline

    def go():
        kit.power(True)
        kit.kelvin(b.get("kelvin", 2200))
        kit.brightness(b.get("brightness", 45))
    _run(go)
    _remember(sid, power=True, kelvin=b.get("kelvin", 2200), brightness=b.get("brightness", 45),
              segments=None, pattern="baseline", color=None)
    return {"ok": True, "mode": S.mode}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    return {k: v for k, v in j.items() if k != "cancel"}


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    j["cancel"] = True
    return {"ok": True}


# --- schedules ---------------------------------------------------------------------------
class _ScheduleActions:
    """What a schedule does, through the same code paths as the page's buttons."""

    @staticmethod
    def apply(sid, theme):
        _BY_SCHEDULE.on = True
        try:
            pat, level = theme["pattern"], theme["level"]
            if pat not in ("keep", "warm_white") and P.is_animated(pat):
                power(sid, Power(on=True))
                play(sid, PlayReq(pattern=pat, params=theme["params"], level=level))
                return
            power(sid, Power(on=True))
            brightness(sid, Brightness(value=level))
            if pat == "warm_white":
                colour(sid, Colour(kelvin=2200))
            elif pat != "keep":
                apply_pattern(sid, PatternReq(pattern=pat, params=theme["params"]))
        finally:
            _BY_SCHEDULE.on = False

    @staticmethod
    def off(sid):
        _BY_SCHEDULE.on = True
        try:
            power(sid, Power(on=False))
        finally:
            _BY_SCHEDULE.on = False

    @staticmethod
    def streaming(sid):
        return STREAMS[sid].playing

    @staticmethod
    def animated(pattern):
        return P.is_animated(pattern)


def _check_theme(pattern, params):
    P.frame(pattern, 10, params)                    # unknown theme or bad parameter: ValueError


_SUFFIX = "" if S.live else "-dry"
SCHED = Scheduler(settings.path(f"schedules{_SUFFIX}.json"), settings.path(f"schedule-state{_SUFFIX}.json"),
                  list(S.sections), _ScheduleActions, S.timezone, S.location, _check_theme)


@app.get("/api/schedules")
def schedules():
    return SCHED.overview()


@app.post("/api/schedules/save")
def schedule_save(body: dict):
    s = _run(lambda: SCHED.save(body))
    log.info("schedule saved: %s (%s)", s["name"], s["id"])
    return {"ok": True, "schedule": s, **SCHED.overview()}


@app.post("/api/schedules/preview")
def schedule_preview(body: dict):
    return {"next": _run(lambda: SCHED.preview(body))}


class SchedId(BaseModel):
    id: str


class SchedEnabled(SchedId):
    enabled: bool


@app.post("/api/schedules/delete")
def schedule_delete(body: SchedId):
    try:
        SCHED.delete(body.id)
    except KeyError:
        raise HTTPException(404, "no such schedule")
    log.info("schedule deleted: %s", body.id)
    return {"ok": True, **SCHED.overview()}


@app.post("/api/schedules/enabled")
def schedule_enabled(body: SchedEnabled):
    try:
        SCHED.set_enabled(body.id, body.enabled)
    except KeyError:
        raise HTTPException(404, "no such schedule")
    return {"ok": True, **SCHED.overview()}


class SchedOrder(BaseModel):
    ids: list[str]


@app.post("/api/schedules/order")
def schedule_order(body: SchedOrder):
    _run(lambda: SCHED.reorder(body.ids))
    return {"ok": True, **SCHED.overview()}


class SchedPause(BaseModel):
    pause: bool


@app.post("/api/schedules/pause")
def schedule_pause(body: SchedPause):
    """pause=true: no schedule events until noon tomorrow. pause=false: resume now."""
    SCHED.pause_until_tomorrow() if body.pause else SCHED.pause(None)
    log.info("schedules %s", f"paused until {SCHED.paused_until}" if body.pause else "resumed")
    return {"ok": True, **SCHED.overview()}


# --- setup wizard hooks -------------------------------------------------------------------
def _before_test(ip):
    """A wizard test is about to stream to this controller: stop the dashboard's own stream."""
    for sid, sec in S.sections.items():
        if sec.controller.ip == ip:
            _stop_stream(sid)


setup.HOOKS.update(settings=lambda: S, before_test=_before_test)

app.mount("/", StaticFiles(directory=os.path.join(settings.PKG, "static"), html=True), name="static")
