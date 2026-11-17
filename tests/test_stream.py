"""The stream worker (houselights/stream.py): one worker per controller, a cancel signal of its own
for every run, and a worker that is slow to stop is never revived or overlapped. No lights: a fake
controller whose frames can be made to hang.

    python tests/test_stream.py
"""
import logging
import os
import sys
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from houselights.stream import Streamer  # noqa: E402

logging.disable(logging.CRITICAL)             # the worker logs its errors; the test checks the effects
FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def wait_for(cond, seconds=5.0):
    """True as soon as cond() is; the deadline keeps a failing test from hanging."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


class FakeKit:
    caps = {"stream": True}
    max_stream_lights = 255
    slow_fps = 1.0
    prefix, tag = "DRY", "fake(127.0.0.1)"

    def __init__(self):
        self.c = types.SimpleNamespace(id="fake")
        self.frames, self.begun, self.ended = [], 0, 0
        self.release = threading.Event()      # clear it to make the next frame hang
        self.release.set()
        self.in_frame = threading.Event()
        self.fail = False

    def guard(self):
        pass

    def stream_begin(self):
        self.begun += 1

    def stream_frame(self, colors):
        self.in_frame.set()
        self.release.wait(10)
        if self.fail:
            raise OSError("network down")
        self.frames.append(colors[0])

    def stream_end(self):
        self.ended += 1


def colour(n):
    return lambda t: [(n, 0, 0)] * 3


def workers():
    return [t for t in threading.enumerate() if t.name == "stream-fake" and t.is_alive()]


# --- a normal run -----------------------------------------------------------------------------------
kit = FakeKit()
s = Streamer(kit, 3, 50)
s.start_fn("a", colour(1))
check("start: one worker, frames, state set",
      wait_for(lambda: len(kit.frames) >= 2) and s.playing and s.state["pattern"] == "a" and len(workers()) == 1)
check("stop: True, nothing runs, cleaned up once",
      s.stop() is True and not s.playing and s.state is None and kit.begun == 1 and kit.ended == 1 and not workers())
n = len(kit.frames)
time.sleep(0.2)
check("no frames after stop", len(kit.frames) == n)
check("stop again: still True, no second cleanup", s.stop() is True and kit.ended == 1)

# --- a restart ---------------------------------------------------------------------------------------
kit = FakeKit()
s = Streamer(kit, 3, 50)
s.start_fn("a", colour(1))
wait_for(lambda: len(kit.frames) >= 2)
first_cancel = s._stop
s.start_fn("b", colour(2))
wait_for(lambda: (2, 0, 0) in kit.frames)
check("restart: the old worker is gone, the new one runs",
      len(workers()) == 1 and kit.begun == 2 and kit.ended == 1 and s.state["pattern"] == "b")
check("restart: the old run's cancel signal stays set, the new run has its own",
      first_cancel.is_set() and s._stop is not first_cancel and not s._stop.is_set())
mark = len(kit.frames)
time.sleep(0.2)
check("restart: only the new colour after the switch", len(kit.frames) > mark and all(f == (2, 0, 0) for f in kit.frames[mark:]))
s.stop()

# --- a worker that does not stop in time ---------------------------------------------------------------
kit = FakeKit()
s = Streamer(kit, 3, 50)
s.STOP_WAIT = 0.3
s.start_fn("a", colour(1))
wait_for(lambda: len(kit.frames) >= 1)
kit.release.clear()
kit.in_frame.clear()
check("a frame is now hanging inside the controller", wait_for(kit.in_frame.is_set))
old_cancel = s._stop
t0 = time.monotonic()
ok = s.stop()
check("stuck worker: stop gives up after STOP_WAIT and says so",
      ok is False and time.monotonic() - t0 < 2 and s.playing and s.state.get("stopping") is True)
check("stuck worker: its cancel signal stays set (nothing clears it)", old_cancel.is_set() and s._stop is old_cancel)
try:
    s.start_fn("b", colour(2))
    refused = False
except ValueError as e:
    refused = "still stopping" in str(e)
check("stuck worker: a new start is refused, nothing overlaps", refused and kit.begun == 1 and len(workers()) == 1)
kit.release.set()
check("stuck worker: once it can, the old worker ends by itself, cleaning up once",
      wait_for(lambda: not s.playing) and kit.ended == 1)
n = len(kit.frames)
time.sleep(0.2)
check("... and sends nothing more", len(kit.frames) == n)
check("... then stop is clean and a new run works",
      s.stop() is True and s.start_fn("b", colour(2)) is None and wait_for(lambda: (2, 0, 0) in kit.frames)
      and kit.begun == 2 and not s._stop.is_set())
s.stop()

# --- stop before the first frame ------------------------------------------------------------------------
kit = FakeKit()
s = Streamer(kit, 3, 50)
s.start_fn("a", colour(1))
check("stop before the first frame is clean", s.stop() is True and kit.frames == [] and kit.begun == 1
      and kit.ended == 1 and not workers())

# --- a failing frame ends the worker ---------------------------------------------------------------------
kit = FakeKit()
kit.fail = True
s = Streamer(kit, 3, 50)
s.start_fn("a", colour(1))
check("a failing frame ends the worker and cleans up once", wait_for(lambda: not s.playing) and kit.ended == 1)
check("... and stop is clean", s.stop() is True and s.state is None)

# --- quick starts from several threads (two clicks, two requests) --------------------------------------------
kit = FakeKit()
s = Streamer(kit, 3, 50)
errors = []


def go(i):
    try:
        s.start_fn(f"p{i}", colour(i))
    except Exception as e:                    # noqa: BLE001
        errors.append(e)


threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
for t in threads:
    t.start()
for t in threads:
    t.join(20)
time.sleep(0.5)
check("six quick starts: exactly one worker is left, none lost", not errors and len(workers()) == 1
      and kit.begun - kit.ended == 1)
s.stop()
check("... and it stops", not workers() and kit.begun == kit.ended)

print(f"\n{len(FAILS)} failed" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
