"""Per-light streaming: one colour per light, sent to the controller every 1/fps seconds.

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
    def __init__(self, kit, lights, fps=15):
        self.kit, self.lights, self.fps = kit, lights, fps
        self._thread = None
        self._stop = threading.Event()
        self.state = None                 # {"pattern", "params", "level", "since"} while playing

    @property
    def playing(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, pattern, params, level=100, reverse=False):
        P.frame(pattern, self.lights, params, 0.0, reverse)          # validate before stopping
        self.start_fn(pattern, lambda t: P.frame(pattern, self.lights, params, t, reverse),
                      P.is_animated(pattern), level, params=params)

    def start_fn(self, name, render, animated=True, level=100, params=None, seconds=None, slow_ok=False):
        """Stream render(t) -> [rgb] * lights. seconds: stop by itself after that long.
        slow_ok: on a controller that can't stream, show the frames slowly instead (setup tests)."""
        slow = not self.kit.caps.get("stream")
        if slow and not slow_ok:
            raise ValueError("this controller can't play animated themes (it has no per-light streaming)")
        if not slow and self.lights > self.kit.max_stream_lights:
            raise ValueError(f"a stream frame carries at most {self.kit.max_stream_lights} lights")
        self.kit.guard()
        self.stop()
        self._stop.clear()
        self.state = {"pattern": name, "params": params or {}, "level": level,
                      "since": time.strftime("%H:%M:%S")}
        self._thread = threading.Thread(target=self._run_slow if slow else self._run,
                                        args=(name, render, animated, level, seconds),
                                        name=f"stream-{self.kit.c.id}", daemon=True)
        self._thread.start()

    def stop(self):
        if self.playing:
            self._stop.set()
            self._thread.join(timeout=3)
        self._thread = None
        self.state = None

    def _run(self, name, render, animated, level, seconds):
        log.info("%s STREAM %s start %s level %s%% (%d lights, %d fps)",
                 self.kit.prefix, self.kit.tag, name, level, self.lights, self.fps)
        scale = max(0, min(100, int(level))) / 100
        static = None
        try:
            self.kit.stream_begin()
            time.sleep(0.3)
            t0, period = time.monotonic(), 1 / self.fps
            next_at = t0
            while not self._stop.is_set():
                t = time.monotonic() - t0
                if seconds and t >= seconds:
                    break
                if animated or static is None:
                    colors = [tuple(round(v * scale) for v in c) for c in render(t)]
                    if not animated:
                        static = colors
                self.kit.stream_frame(static or colors)
                next_at += period if animated else 0.4             # static: just keep the mode alive
                self._stop.wait(max(0.0, next_at - time.monotonic()))
        except Exception as e:                                     # never leave a controller stuck
            log.error("STREAM %s failed: %s", self.kit.tag, e)
        finally:
            try:
                self.kit.stream_end()
            except OSError:
                pass
            log.info("%s STREAM %s stop", self.kit.prefix, self.kit.tag)

    def _run_slow(self, name, render, animated, level, seconds):
        """No streaming: show frames with show_lights() (or the main colour) at most
        kit.slow_fps times a second, then put the controller back if it allows."""
        log.info("%s SLOW %s start %s (%d lights)", self.kit.prefix, self.kit.tag, name, self.lights)
        snap = self.kit.snapshot() if self.kit.caps.get("restore") == "snapshot" else None
        per_light = self.kit.caps.get("static") in ("lights", "palette")
        scale = max(0, min(100, int(level))) / 100
        last = None
        try:
            t0 = time.monotonic()
            while not self._stop.is_set():
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
                    self._stop.wait(seconds - t if seconds else None)
                    break
                self._stop.wait(1 / self.kit.slow_fps)
        except Exception as e:
            log.error("SLOW %s failed: %s", self.kit.tag, e)
        finally:
            if snap is not None:
                try:
                    self.kit.restore(snap)
                except Exception as e:
                    log.error("SLOW %s could not put the controller back: %s", self.kit.tag, e)
            log.info("%s SLOW %s stop", self.kit.prefix, self.kit.tag)
