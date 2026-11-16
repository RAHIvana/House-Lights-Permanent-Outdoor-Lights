"""Schedules: switch kits on and off at clock times or around sunrise/sunset.

A schedule names some sections, weekdays, an optional date range, an "on" rule, an "off"
rule and a theme. Each day it's due gives one window [on, off), which may run past
midnight. Every 30 s the scheduler works out which window (if any) each section is in, and
acts only when that changes:
- a window starts, or wins over another: power on and show its theme;
- the window it applied ends: power off.
Between those events it leaves the kits alone, so a change made by hand during a window
sticks until the window ends.

If several windows cover a section, a schedule with a date range wins over one without,
then the one higher in the list.

What was applied is saved, so a restart neither repeats an "on" nor misses an "off" (a
missed "off" up to 6 h old is still sent). An animated theme lives only in this process,
so after a restart it is resumed, unless it was changed by hand.
"""
import datetime as dt
import json
import logging
import os
import threading
import time
import uuid
from zoneinfo import ZoneInfo

log = logging.getLogger("houselights")

TICK = 30                                   # seconds between checks
CATCH_UP_OFF = dt.timedelta(hours=6)        # a missed "off" older than this is dropped
RETRY = 120                                 # seconds before retrying a failed action
SUN = ("sunrise", "sunset")
SPECIAL_THEMES = {"keep": "Last used", "warm_white": "Warm white 2200 K"}


# --- window arithmetic (pure; tested with a fake clock) ---------------------------------
def sun_time(location, tz, day, event):
    from astral import Observer
    from astral.sun import sunrise, sunset
    obs = Observer(latitude=location[0], longitude=location[1])
    return (sunrise if event == "sunrise" else sunset)(obs, date=day, tzinfo=tz)


def _at(rule, day, tz, location):
    if rule["type"] == "time":
        h, m = map(int, rule["time"].split(":"))
        return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
    if location is None:
        raise ValueError("sunrise/sunset needs the location (Settings tab: change setup)")
    return (sun_time(location, tz, day, rule["type"]).replace(second=0, microsecond=0)
            + dt.timedelta(minutes=rule.get("offset", 0)))


def window(s, day, tz, location):
    """(start, end) of schedule s on the day it starts, or None if it isn't due that day."""
    if day.weekday() not in s["days"]:
        return None
    if s.get("date_from") and day < dt.date.fromisoformat(s["date_from"]):
        return None
    if s.get("date_to") and day > dt.date.fromisoformat(s["date_to"]):
        return None
    start = _at(s["on"], day, tz, location)
    off = s["off"]
    if off["type"] == "after":
        end = start + dt.timedelta(minutes=off["minutes"])
    else:
        end = _at(off, day, tz, location)
        if end <= start:                            # e.g. on 8 PM, off 1 AM or at sunrise
            end = _at(off, day + dt.timedelta(days=1), tz, location)
    if not start < end <= start + dt.timedelta(hours=24):
        return None
    return start, end


def active_window(s, now, tz, location):
    for back in (1, 0):                             # yesterday's window may run past midnight
        try:
            w = window(s, now.date() - dt.timedelta(days=back), tz, location)
        except ValueError:
            return None
        if w and w[0] <= now < w[1]:
            return w
    return None


def next_windows(s, now, tz, location, n=3, horizon=400):
    """The current window (if any) and the next ones, up to n."""
    out = []
    day = now.date() - dt.timedelta(days=1)
    for _ in range(horizon):
        w = window(s, day, tz, location)
        if w and w[1] > now:
            out.append(w)
            if len(out) == n:
                break
        day += dt.timedelta(days=1)
    return out


def desired(schedules, now, tz, location):
    """{section: (schedule, window)} for every section some enabled schedule covers now."""
    best = {}
    for rank, s in enumerate(schedules):
        if not s["enabled"]:
            continue
        w = active_window(s, now, tz, location)
        if not w:
            continue
        pri = (0 if (s.get("date_from") or s.get("date_to")) else 1, rank)
        for sid in s["sections"]:
            if sid not in best or pri < best[sid][0]:
                best[sid] = (pri, s, w)
    return {sid: (s, w) for sid, (_, s, w) in best.items()}


# --- validation ---------------------------------------------------------------------------
def _rule(r, allowed, what):
    if not isinstance(r, dict) or r.get("type") not in allowed:
        raise ValueError(f"{what}: choose one of {', '.join(allowed)}")
    t = r["type"]
    if t == "time":
        try:
            h, m = map(int, str(r.get("time", "")).split(":"))
            assert 0 <= h < 24 and 0 <= m < 60
        except (ValueError, AssertionError):
            raise ValueError(f"{what}: time must be HH:MM")
        return {"type": t, "time": f"{h:02d}:{m:02d}"}
    if t == "after":
        mins = int(r.get("minutes", 0))
        if not 1 <= mins <= 24 * 60:
            raise ValueError(f"{what}: duration must be 1 minute to 24 hours")
        return {"type": t, "minutes": mins}
    offset = int(r.get("offset", 0))
    if abs(offset) > 12 * 60:
        raise ValueError(f"{what}: offset must be within 12 hours")
    return {"type": t, "offset": offset}


def clean(d, section_ids, location, check_theme):
    """A normalised schedule from the dialog's JSON, or ValueError with a readable reason."""
    name = str(d.get("name", "")).strip()[:60]
    if not name:
        raise ValueError("give the schedule a name")
    sections = [s for s in section_ids if s in set(d.get("sections") or [])]
    if not sections:
        raise ValueError("pick at least one set of lights")
    days = sorted({int(x) for x in d.get("days") or [] if 0 <= int(x) <= 6})
    if not days:
        raise ValueError("pick at least one day")
    dates = {}
    for k in ("date_from", "date_to"):
        v = d.get(k) or None
        if v:
            try:
                dt.date.fromisoformat(v)
            except ValueError:
                raise ValueError(f"{k.replace('_', ' ')} must be a date (YYYY-MM-DD)")
        dates[k] = v
    if dates["date_from"] and dates["date_to"] and dates["date_from"] > dates["date_to"]:
        raise ValueError("the date range ends before it starts")
    on = _rule(d.get("on"), ("time",) + SUN, "Turn on")
    off = _rule(d.get("off"), ("time", "after") + SUN, "Turn off")
    if location is None and (on["type"] in SUN or off["type"] in SUN):
        raise ValueError("sunrise/sunset needs the location (Settings tab: change setup)")
    th = d.get("theme") or {}
    level = int(th.get("level", 100))
    if not 1 <= level <= 100:
        raise ValueError("level must be 1–100 %")
    theme = {"pattern": th.get("pattern") or "keep", "params": th.get("params") or {}, "level": level}
    if theme["pattern"] not in SPECIAL_THEMES:
        check_theme(theme["pattern"], theme["params"])
    return {"id": d.get("id") or uuid.uuid4().hex[:8], "name": name,
            "enabled": bool(d.get("enabled", True)), "sections": sections, "days": days,
            **dates, "on": on, "off": off, "theme": theme}


# --- the scheduler ---------------------------------------------------------------------------
def _load(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


class Scheduler:
    """actions: apply(section, theme), off(section), streaming(section) -> bool,
    animated(pattern) -> bool. Section ids are listed in `sections` (page order)."""

    def __init__(self, schedules_file, state_file, sections, actions, tz, location, check_theme):
        self.schedules_file, self.state_file = schedules_file, state_file
        self.sections, self.actions = list(sections), actions
        self.tz, self.location, self.check_theme = ZoneInfo(tz), location, check_theme
        self.lock = threading.RLock()
        self.schedules = _load(schedules_file, {"schedules": []})["schedules"]
        st = _load(state_file, {})
        self.applied = st.get("applied", {})        # section -> {key, id, name, start, end, theme}
        self.override = st.get("override", {})      # section -> key changed by hand
        self.paused_until = st.get("paused_until")
        self.last = st.get("last", {})              # section -> last action, for the page
        self.retry_at = {}
        # Animated themes stop with the process: resume them unless changed by hand.
        self.resume = {sid for sid, a in self.applied.items()
                       if self.override.get(sid) != a["key"] and self._animated(a["theme"])}
        self._stop = threading.Event()
        self._thread = None

    def _animated(self, theme):
        try:
            return theme["pattern"] not in SPECIAL_THEMES and self.actions.animated(theme["pattern"])
        except ValueError:
            return False

    def now(self):
        return dt.datetime.now(self.tz)

    # persistence
    def _save_schedules(self):
        _save(self.schedules_file, {"schedules": self.schedules})

    def _save_state(self):
        _save(self.state_file, {"applied": self.applied, "override": self.override,
                                "paused_until": self.paused_until, "last": self.last})

    # thread
    def start(self):
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            self._stop.wait(TICK)

    # the decision step
    def _note(self, sid, what, error=None):
        self.last[sid] = {"at": self.now().isoformat(timespec="seconds"), "what": what, "error": error}
        (log.error if error else log.info)("schedule %s: %s%s", sid, what, f" FAILED: {error}" if error else "")

    def _do(self, sid, what, fn):
        if self.retry_at.get(sid, 0) > time.time():
            return False
        try:
            fn()
        except Exception as e:                         # kit offline, disabled, bad theme...
            self.retry_at[sid] = time.time() + RETRY
            self._note(sid, what, getattr(e, "detail", None) or str(e) or type(e).__name__)
            return False
        self.retry_at.pop(sid, None)
        self._note(sid, what)
        return True

    def tick(self, now=None):
        now = now or self.now()
        with self.lock:
            if self.paused_until:
                if now < dt.datetime.fromisoformat(self.paused_until):
                    return
                self.paused_until = None
            want = desired(self.schedules, now, self.tz, self.location)
            for sid in self.sections:
                cur = self.applied.get(sid)
                if sid in want:
                    s, (start, end) = want[sid]
                    key = f"{s['id']}@{start.isoformat()}"
                    if cur and cur["key"] == key:
                        if sid in self.resume and not self.actions.streaming(sid):
                            if self._do(sid, f"resumed {s['name']}", lambda: self.actions.apply(sid, s["theme"])):
                                self.resume.discard(sid)
                        continue
                    if self._do(sid, f"on: {s['name']}", lambda: self.actions.apply(sid, s["theme"])):
                        self.applied[sid] = {"key": key, "id": s["id"], "name": s["name"],
                                             "start": start.isoformat(), "end": end.isoformat(),
                                             "theme": s["theme"]}
                        self.override.pop(sid, None)
                        self.resume.discard(sid)
                elif cur:
                    end = dt.datetime.fromisoformat(cur["end"])
                    if now < end:
                        # Its schedule was deleted, disabled or moved: forget it, leave the lights.
                        self.applied.pop(sid)
                    elif now - end > CATCH_UP_OFF or self._do(sid, f"off: {cur['name']}",
                                                              lambda: self.actions.off(sid)):
                        self.applied.pop(sid)
                        self.override.pop(sid, None)
                        self.resume.discard(sid)
            self._save_state()

    def manual(self, sid):
        """A change by hand: keep it until the window ends (don't resume an animation)."""
        with self.lock:
            a = self.applied.get(sid)
            if a and self.override.get(sid) != a["key"]:
                self.override[sid] = a["key"]
                self.resume.discard(sid)
                self._save_state()

    # editing
    def clean(self, d):
        return clean(d, self.sections, self.location, self.check_theme)

    def save(self, d):
        s = self.clean(d)
        with self.lock:
            for i, old in enumerate(self.schedules):
                if old["id"] == s["id"]:
                    self.schedules[i] = s
                    break
            else:
                self.schedules.append(s)
            self._save_schedules()
        return s

    def delete(self, sched_id):
        with self.lock:
            n = len(self.schedules)
            self.schedules = [s for s in self.schedules if s["id"] != sched_id]
            if len(self.schedules) == n:
                raise KeyError(sched_id)
            self._save_schedules()

    def set_enabled(self, sched_id, enabled):
        with self.lock:
            for s in self.schedules:
                if s["id"] == sched_id:
                    s["enabled"] = bool(enabled)
                    self._save_schedules()
                    return
            raise KeyError(sched_id)

    def reorder(self, ids):
        with self.lock:
            by_id = {s["id"]: s for s in self.schedules}
            if sorted(ids) != sorted(by_id):
                raise ValueError("the new order must list every schedule once")
            self.schedules = [by_id[i] for i in ids]
            self._save_schedules()

    def pause(self, until):
        with self.lock:
            self.paused_until = until.isoformat(timespec="minutes") if until else None
            self._save_state()

    def pause_until_tomorrow(self):
        """Pause tonight's events: until noon tomorrow."""
        now = self.now()
        noon = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(12), tzinfo=self.tz)
        self.pause(noon)

    # for the page
    def preview(self, d, n=3):
        s = self.clean(d)
        return [{"start": a.isoformat(), "end": b.isoformat()}
                for a, b in next_windows(s, self.now(), self.tz, self.location, n)]

    def overview(self):
        now = self.now()
        with self.lock:
            out = []
            for s in self.schedules:
                try:
                    nxt = next_windows(s, now, self.tz, self.location, 1)
                except ValueError:
                    nxt = []
                out.append(dict(s, next={"start": nxt[0][0].isoformat(), "end": nxt[0][1].isoformat()}
                                if nxt else None,
                                active=bool(nxt) and nxt[0][0] <= now and s["enabled"]))
            sun = None
            if self.location:
                sun = {e: sun_time(self.location, self.tz, now.date(), e).isoformat(timespec="minutes")
                       for e in SUN}
            return {"now": now.isoformat(timespec="seconds"), "timezone": str(self.tz),
                    "location_set": self.location is not None, "sun": sun,
                    "paused_until": self.paused_until, "schedules": out,
                    "applied": {k: {x: v[x] for x in ("id", "name", "end")} for k, v in self.applied.items()},
                    "override": sorted(self.override), "last": self.last,
                    "themes": SPECIAL_THEMES}
