"""What every controller driver provides. The safety checks live here, not in the page:
- a disabled controller gets no commands;
- in dry (practice) mode nothing that changes a light is sent; it is only logged.

Capabilities (CAPS) tell the dashboard and the setup wizard what a controller can do:
  stream   per-light colours many times a second: animated themes and "Play live"
  static   how a static theme is shown:
             "segments"  one packet per colour group of fixed-size segments (lights_per_segment)
             "lights"    every light its own colour, in one call (show_lights)
             "palette"   an approximation with a limited number of colour blocks (show_lights)
  pick     segments can be picked and coloured one by one on the page
  status   the controller reports power, brightness and colour
  count    where the light count comes from: "manual" (the wizard counts with test patterns),
           "reported" (the controller says), "display" (only used to draw the run)
  restore  after a test: "auto" (controller goes back by itself), "snapshot" (we save and
           put back its state), "none" (can't: the wizard says so)
  stream_untested  (optional) streaming is allowed but not yet seen working on this model:
           the page and the wizard say "try it"

CAPS can differ per model of one driver (e.g. Govee): ask drivers.model_caps(kind, model) or
a kit's .caps, not Kit.CAPS, for one controller.
"""
import logging
import threading

log = logging.getLogger("houselights")


class NotAllowed(Exception):
    pass


# A controller that shows one colour at a time (one "segment": the whole run), reports its
# state, and is saved and put back after a wizard test. Static themes show their main colour.
ONE_COLOUR_CAPS = {"stream": False, "static": "segments", "pick": False, "status": True, "count": "display",
                   "restore": "snapshot"}


class Kit:
    """One controller. Drivers subclass this."""

    CAPS = {"stream": False, "static": "segments", "pick": True, "status": True, "count": "manual",
            "restore": "none"}
    max_stream_lights = 255
    slow_fps = 1.0                # how often a test may update a controller that can't stream

    def __init__(self, controller, live):
        self.c = controller
        self.live = live
        self.lock = threading.Lock()        # one command at a time per controller

    @property
    def caps(self):
        return self.CAPS

    @property
    def tag(self):
        zone = (self.c.options or {}).get("zone") if hasattr(self.c, "options") else None
        return f"{self.c.id}({self.c.ip}{'/' + zone if zone else ''})"

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
        raise ValueError("this controller can't colour segments one by one")

    def show_lights(self, colors):
        """A whole static frame, one colour per light (static "lights" / "palette").
        Caller holds self.lock."""
        raise ValueError("this controller can't show a different colour on each light")

    def preview_static(self, colors):
        """What show_lights() will really display (the same, unless it approximates)."""
        return colors

    # --- per-light streaming (called by stream.Streamer) ---
    def stream_begin(self):
        raise NotImplementedError

    def stream_frame(self, colors):
        raise NotImplementedError

    def stream_end(self):
        raise NotImplementedError

    # --- tests on controllers that can't stream ---
    def snapshot(self):
        """State to put back after a test (restore "snapshot"), or None."""
        return None

    def restore(self, snap):
        pass
