"""Schedule logic with a fake clock and fake kits: no lights, no network.

    python tests/test_schedule.py
"""
import datetime as dt
import os
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from houselights import schedule as S  # noqa: E402

TZ = ZoneInfo("America/New_York")
LOC = (40.71, -74.01)                     # any city works for the test


def at(y, mo, d, h=0, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=TZ)


class FakeKits:
    def __init__(self):
        self.calls, self.playing, self.fail = [], set(), set()

    def apply(self, sid, theme):
        if sid in self.fail:
            raise OSError("kit offline")
        self.calls.append(("on", sid, theme["pattern"]))
        if theme["pattern"] == "diya_glow":
            self.playing.add(sid)

    def off(self, sid):
        self.calls.append(("off", sid))
        self.playing.discard(sid)

    def streaming(self, sid):
        return sid in self.playing

    @staticmethod
    def animated(p):
        return p == "diya_glow"


def make(tmp, kits=None):
    kits = kits or FakeKits()
    sch = S.Scheduler(f"{tmp}/s.json", f"{tmp}/st.json", ["run_a", "run_b", "run_c"],
                      kits, "America/New_York", LOC, lambda p, q: None)
    return sch, kits


def sched(**kw):
    d = {"name": "t", "sections": ["run_a"], "days": list(range(7)),
         "on": {"type": "time", "time": "20:00"}, "off": {"type": "time", "time": "22:00"},
         "theme": {"pattern": "warm_white", "level": 80}}
    d.update(kw)
    return d


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        check.failed = True


check.failed = False

# --- windows -------------------------------------------------------------------------
day = dt.date(2026, 10, 28)                                              # a Wednesday
s = S.clean(sched(), ["run_a"], LOC, lambda p, q: None)
check("8-10 PM window", S.window(s, day, TZ, LOC) == (at(2026, 10, 28, 20), at(2026, 10, 28, 22)))
s2 = S.clean(sched(off={"type": "time", "time": "01:00"}), ["run_a"], LOC, lambda p, q: None)
check("off after midnight is next day", S.window(s2, day, TZ, LOC)[1] == at(2026, 10, 29, 1))
check("active at 00:30 from yesterday's window", S.active_window(s2, at(2026, 10, 29, 0, 30), TZ, LOC) is not None)
s3 = S.clean(sched(on={"type": "sunset", "offset": 60}, off={"type": "after", "minutes": 180}),
             ["run_a"], LOC, lambda p, q: None)
w = S.window(s3, day, TZ, LOC)
sunset = S.sun_time(LOC, TZ, day, "sunset")
check(f"sunset+1h then 3h (sunset {sunset:%H:%M}, on {w[0]:%H:%M}, off {w[1]:%H:%M})",
      abs((w[0] - sunset).total_seconds() - 3600) < 60 and w[1] - w[0] == dt.timedelta(hours=3))
check("New York sunset late Oct is ~18:00", 17 <= sunset.hour <= 18)
s4 = S.clean(sched(days=[5, 6]), ["run_a"], LOC, lambda p, q: None)                  # Sat, Sun
check("weekday filter", S.window(s4, day, TZ, LOC) is None and S.window(s4, dt.date(2026, 10, 31), TZ, LOC))
s5 = S.clean(sched(date_from="2026-10-30", date_to="2026-11-03"), ["run_a"], LOC, lambda p, q: None)
check("date range", S.window(s5, day, TZ, LOC) is None and S.window(s5, dt.date(2026, 11, 1), TZ, LOC))
dst = S.window(s, dt.date(2026, 11, 1), TZ, LOC)                                          # DST ends
check("DST day keeps wall-clock times", dst[0].hour == 20 and dst[1].hour == 22)
for bad, why in [(sched(name=""), "name"), (sched(sections=[]), "sections"), (sched(days=[]), "days"),
                 (sched(on={"type": "time", "time": "25:00"}), "time"),
                 (sched(date_from="2026-11-05", date_to="2026-11-01"), "range"),
                 (sched(off={"type": "after", "minutes": 0}), "duration")]:
    try:
        S.clean(bad, ["run_a"], LOC, lambda p, q: None)
        check(f"rejects bad {why}", False)
    except ValueError:
        check(f"rejects bad {why}", True)
try:
    S.clean(sched(on={"type": "sunset", "offset": 0}), ["run_a"], None, lambda p, q: None)
    check("sunset without location rejected", False)
except ValueError:
    check("sunset without location rejected", True)

# --- scheduler behavior -------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    sch, k = make(tmp)
    sch.save(sched(name="evening", sections=["run_a", "run_c"]))
    sch.tick(at(2026, 10, 28, 19, 59))
    check("nothing before the window", k.calls == [])
    sch.tick(at(2026, 10, 28, 20, 0))
    check("on at 20:00 for both kits", sorted(k.calls) == [("on", "run_a", "warm_white"), ("on", "run_c", "warm_white")])
    k.calls.clear()
    sch.tick(at(2026, 10, 28, 20, 30))
    check("no repeat during the window", k.calls == [])
    sch.manual("run_a")                                              # turned off by hand
    sch.tick(at(2026, 10, 28, 21, 0))
    check("manual change is left alone", k.calls == [])
    sch.tick(at(2026, 10, 28, 22, 0))
    check("off at 22:00 for both", sorted(k.calls) == [("off", "run_a"), ("off", "run_c")])
    k.calls.clear()
    sch.tick(at(2026, 10, 28, 22, 30))
    check("nothing after", k.calls == [])

    # overlap: a date-ranged Diwali schedule beats the everyday one, then hands back
    sch.save(sched(name="diwali", sections=["run_a"], date_from="2026-10-29", date_to="2026-10-29",
                   on={"type": "time", "time": "21:00"}, off={"type": "time", "time": "21:30"},
                   theme={"pattern": "diya_glow", "level": 90}))
    sch.tick(at(2026, 10, 29, 20, 0)); k.calls.clear()
    sch.tick(at(2026, 10, 29, 21, 0))
    check("date-ranged schedule takes over", k.calls == [("on", "run_a", "diya_glow")])
    k.calls.clear()
    sch.tick(at(2026, 10, 29, 21, 30))
    check("everyday schedule comes back after it", k.calls == [("on", "run_a", "warm_white")])

    # restart mid-window with an animated theme: resumed
    sch.tick(at(2026, 10, 29, 22, 0)); k.calls.clear()
    sch.delete([x for x in sch.schedules if x["name"] == "evening"][0]["id"])
    sch.save(sched(name="anim", sections=["run_b"], theme={"pattern": "diya_glow", "level": 90}))
    sch.tick(at(2026, 10, 30, 20, 0))
    k2 = FakeKits()                                                       # new process: nothing streams
    sch2, _ = make(tmp, k2)
    sch2.tick(at(2026, 10, 30, 20, 10))
    check("animated theme resumed after restart", k2.calls == [("on", "run_b", "diya_glow")])
    sch2.tick(at(2026, 10, 30, 20, 11))
    check("resumed only once", len(k2.calls) == 1)

    # restart after the window ended while down: missed off is sent
    k3 = FakeKits()
    sch3, _ = make(tmp, k3)
    sch3.tick(at(2026, 10, 30, 23, 0))
    check("missed off sent after restart", k3.calls == [("off", "run_b")])

    # a failing kit is retried, not marked done
    k4 = FakeKits(); k4.fail.add("run_b")
    sch4, _ = make(tmp, k4)
    sch4.tick(at(2026, 10, 31, 20, 0))
    check("failure recorded", sch4.last["run_b"]["error"] == "kit offline" and "run_b" not in sch4.applied)
    k4.fail.clear(); sch4.retry_at.clear()
    sch4.tick(at(2026, 10, 31, 20, 3))
    check("retried and applied", ("on", "run_b", "diya_glow") in k4.calls and "run_b" in sch4.applied)

    # pause until noon tomorrow: tonight's off is skipped
    sch4.paused_until = at(2026, 11, 1, 12).isoformat()
    k4.calls.clear()
    sch4.tick(at(2026, 10, 31, 22, 0))
    check("paused: no off", k4.calls == [])
    sch4.tick(at(2026, 11, 1, 12, 0))
    check("pause ends at noon (stale off dropped)", sch4.paused_until is None and "run_b" not in sch4.applied)

    # deleting a schedule mid-window leaves the lights as they are
    sch4.tick(at(2026, 11, 1, 20, 0)); k4.calls.clear()
    sch4.delete(sch4.schedules[-1]["id"])
    sch4.tick(at(2026, 11, 1, 20, 30))
    check("deleted mid-window: lights left alone", k4.calls == [] and "run_b" not in sch4.applied)

sys.exit(1 if check.failed else 0)
