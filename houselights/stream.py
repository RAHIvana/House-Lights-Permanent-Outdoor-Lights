"""Per-light streaming: one color per light, sent to the controller every 1/fps seconds.

One Streamer per run. Animated themes are rendered here at time t. The setup wizard's test
patterns use start_fn() with their own render function and a time limit.
In dry mode the driver only logs start and stop.
"""
import logging
import threading
import time

from . import patterns as P

log = logging.getLogger("houselights")


class Streamer:
    """One worker thread at a time per Kit. Every run gets a cancel signal of its own, so a worker that
    is slow to stop can never be revived by the next start; stop() keeps hold of it until it really
    ends, and a new start is refused until then."""

    STOP_WAIT = 3.0                   # seconds stop() waits for the worker (tests make it short)

    def __init__(self, kit, lights, fps=15):
        self.kit, self.lights, self.fps = kit, lights, fps
        self._thread = None
        self._stop = threading.Event()    # the current worker's cancel signal (a new one for every run)
        self._mutex = threading.RLock()   # start and stop never interleave (two quick requests)
        self.state = None                 # {"pattern", "params", "level", "since"} while playing

    @property
    def playing(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, pattern, params, level=100, reverse=False, render=None):
        """render(t) -> [rgb] * lights replaces the plain frame, e.g. this run's slice of a
        whole-house theme (which keeps its own clock so every run shows the same moment)."""
        render = render or (lambda t: P.frame(pattern, self.lights, params, t, reverse))
        render(0.0)                                                   # validate before stopping
        self.start_fn(pattern, render, P.is_animated(pattern, params), level, params=params)

    def start_fn(self, name, render, animated=True, level=100, params=None, seconds=None, slow_ok=False):
        """Stream render(t) -> [rgb] * lights. seconds: stop by itself after that long.
        slow_ok: on a controller that can't stream, show the frames slowly instead (setup tests)."""
        slow = not self.kit.caps.get("stream")
        if slow and not slow_ok:
            raise ValueError("this controller can't play animated themes (it has no per-light streaming)")
        if not slow and self.lights > self.kit.max_stream_lights:
            raise ValueError(f"a stream frame carries at most {self.kit.max_stream_lights} lights")
        self.kit.guard()
        with self._mutex:
            if not self.stop():
                raise ValueError("the previous animation is still stopping: try again in a moment")
            stop = self._stop = threading.Event()
            self.state = {"pattern": name, "params": params or {}, "level": level,
                          "since": time.strftime("%H:%M:%S")}
            self._thread = threading.Thread(target=self._run_slow if slow else self._run,
                                            args=(name, render, animated, level, seconds, stop),
                                            name=f"stream-{self.kit.c.id}", daemon=True)
            self._thread.start()

    def stop(self):
        """Ask the worker to stop and wait for it. True when nothing runs any more. A worker that
        has not ended after STOP_WAIT seconds is kept (playing stays True, state says "stopping") with
        its cancel signal set, and False is returned."""
        with self._mutex:
            t = self._thread
            if t is not None:
                self._stop.set()
                if t.is_alive():
                    t.join(timeout=self.STOP_WAIT)
                if t.is_alive():
                    log.warning("%s: the animation has not stopped after %s s", self.kit.tag, self.STOP_WAIT)
                    if self.state:
                        self.state["stopping"] = True
                    return False
            self._thread = None
            self.state = None
            return True

    def _run(self, name, render, animated, level, seconds, stop):
        log.info("%s STREAM %s start %s level %s%% (%d lights, %d fps)",
                 self.kit.prefix, self.kit.tag, name, level, self.lights, self.fps)
        scale = max(0, min(100, int(level))) / 100
        static = None
        try:
            self.kit.stream_begin()
            time.sleep(0.3)
            t0, period = time.monotonic(), 1 / self.fps
            next_at = t0
            while not stop.is_set():
                t = time.monotonic() - t0
                if seconds and t >= seconds:
                    break
                if animated or static is None:
                    colors = [tuple(round(v * scale) for v in c) for c in render(t)]
                    if not animated:
                        static = colors
                self.kit.stream_frame(static or colors)
                next_at += period if animated else 0.4             # static: just keep the mode alive
                stop.wait(max(0.0, next_at - time.monotonic()))
        except Exception as e:                                     # never leave a controller stuck
            log.error("STREAM %s failed: %s", self.kit.tag, e)
        finally:
            try:
                self.kit.stream_end()
            except OSError:
                pass
            log.info("%s STREAM %s stop", self.kit.prefix, self.kit.tag)

    def _run_slow(self, name, render, animated, level, seconds, stop):
        """No streaming: show frames with show_lights() (or the main color) at most
        kit.slow_fps times a second, then put the controller back if it allows."""
        log.info("%s SLOW %s start %s (%d lights)", self.kit.prefix, self.kit.tag, name, self.lights)
        snap = self.kit.snapshot() if self.kit.caps.get("restore") == "snapshot" else None
        per_light = self.kit.caps.get("static") in ("lights", "palette")
        scale = max(0, min(100, int(level))) / 100
        last = None
        try:
            t0 = time.monotonic()
            while not stop.is_set():
                t = time.monotonic() - t0
                if seconds and t >= seconds:
                    break
                colors = [tuple(round(v * scale) for v in c) for c in render(t)]
                if colors != last:
                    if per_light:
                        with self.kit.lock:
                            self.kit.show_lights(colors)
                    else:
                        self.kit.color(max(set(colors), key=colors.count))
                    last = colors
                if not animated:
                    stop.wait(seconds - t if seconds else None)
                    break
                stop.wait(1 / self.kit.slow_fps)
        except Exception as e:
            log.error("SLOW %s failed: %s", self.kit.tag, e)
        finally:
            if snap is not None:
                try:
                    self.kit.restore(snap)
                except Exception as e:
                    log.error("SLOW %s could not put the controller back: %s", self.kit.tag, e)
            log.info("%s SLOW %s stop", self.kit.prefix, self.kit.tag)
