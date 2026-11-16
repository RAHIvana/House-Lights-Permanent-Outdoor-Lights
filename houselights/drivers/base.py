"""What every controller driver provides. The safety checks live here, not in the page:
- a disabled controller gets no commands;
- in dry (practice) mode nothing that changes a light is sent; it is only logged.
"""
import logging
import threading

log = logging.getLogger("houselights")


class NotAllowed(Exception):
    pass


class Kit:
    """One controller. Drivers subclass this and fill in the _send_* methods."""

    max_stream_lights = 255

    def __init__(self, controller, live):
        self.c = controller
        self.live = live
        self.lock = threading.Lock()        # one command at a time per controller

    @property
    def tag(self):
        return f"{self.c.id}({self.c.ip})"

    @property
    def prefix(self):
        return "LIVE" if self.live else "DRY"

    def guard(self):
        if not self.c.enabled:
            raise NotAllowed(f"controller {self.c.id} is disabled in the settings")

    # --- whole-controller commands (thread-safe) ---
    def power(self, on):
        raise NotImplementedError

    def brightness(self, value):
        raise NotImplementedError

    def color(self, rgb):
        raise NotImplementedError

    def kelvin(self, k):
        raise NotImplementedError

    def segments(self, segs, rgb, nseg):
        """These segments to one colour. Caller holds self.lock."""
        raise NotImplementedError

    # --- per-light streaming (called by stream.Streamer) ---
    def stream_begin(self):
        raise NotImplementedError

    def stream_frame(self, colors):
        raise NotImplementedError

    def stream_end(self):
        raise NotImplementedError
