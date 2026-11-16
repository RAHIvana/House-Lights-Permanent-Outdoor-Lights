"""Settings, wizard test patterns and Govee packets: no lights, no network.

    python tests/test_settings.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp()
os.environ["HOUSELIGHTS_HOME"] = TMP

from houselights import settings, setup  # noqa: E402
from houselights.drivers import govee  # noqa: E402

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def rejects(name, cfg, words):
    try:
        settings.validate(cfg)
    except ValueError as e:
        check(f"rejects {name}: {e}", words.lower() in str(e).lower())
        return
    check(f"rejects {name}", False)


def good(**over):
    cfg = {"controllers": [{"id": "porch", "type": "govee", "model": "H806A", "ip": "192.0.2.10"},
                           {"id": "garage", "type": "govee", "model": "H806A", "ip": "192.0.2.11", "enabled": False}],
           "runs": [{"name": "Porch eaves", "controller": "porch", "lights": 60, "start": "left end"},
                    {"name": "Garage", "controller": "garage", "lights": 120, "reverse": True}],
           "timezone": "America/New_York", "location": {"lat": 40.7128, "lon": -74.006}}
    cfg.update(over)
    return cfg


# --- validation ---
c = settings.validate(good())
check("good config passes", c["runs"][0]["id"] == "porch_eaves" and c["runs"][0]["short"] == "Porch eaves")
check("defaults filled", c["mode"] == "live" and c["listen"]["port"] == 8090 and c["runs"][1]["baseline"]["kelvin"] == 2200)
check("location kept", c["location"] == {"lat": 40.7128, "lon": -74.006})
check("empty location -> none", settings.validate(good(location={"lat": "", "lon": ""}))["location"] is None)
rejects("no runs", good(runs=[]), "at least one run")
rejects("unknown model", good(controllers=[{"id": "x", "model": "H999", "ip": "192.0.2.1"}],
                              runs=[{"name": "a", "controller": "x", "lights": 5}]), "not supported")
rejects("bad ip", good(controllers=[{"id": "x", "model": "H806A", "ip": "192.0.2.300"}],
                       runs=[{"name": "a", "controller": "x", "lights": 5}]), "not an IP")
rejects("same ip twice", good(controllers=[{"id": "x", "model": "H806A", "ip": "192.0.2.1"},
                                           {"id": "y", "model": "H806A", "ip": "192.0.2.1"}]), "used twice")
rejects("too many lights", good(runs=[{"name": "a", "controller": "porch", "lights": 300}]), "between 1 and 255")
rejects("two runs on one controller", good(runs=[{"name": "a", "controller": "porch", "lights": 5},
                                                 {"name": "b", "controller": "porch", "lights": 5}]), "already has a run")
rejects("run without controller", good(runs=[{"name": "a", "controller": "nope", "lights": 5}]), "pick its controller")
rejects("same run names", good(runs=[{"name": "Front", "controller": "porch", "lights": 5},
                                     {"name": "front", "controller": "garage", "lights": 5}]), "same id")
rejects("bad time zone", good(timezone="Mars/Olympus"), "unknown time zone")
rejects("bad latitude", good(location={"lat": 95, "lon": 0}), "latitude")
rejects("bad mode", good(mode="maybe"), "mode")

# --- save and load ---
check("no file: not configured", settings.load().configured is False)
settings.save(good())
s = settings.load()
check("saved and loaded", s.configured and list(s.sections) == ["porch_eaves", "garage"])
sec = s.sections["garage"]
check("segments from the model (120 / 5)", sec.segments == 24 and sec.lights_per_segment == 5)
check("disabled controller", not sec.enabled and s.sections["porch_eaves"].enabled)
check("location tuple", s.location == (40.7128, -74.006) and s.timezone == "America/New_York")
os.environ["HOUSELIGHTS_DRY"] = "1"
check("--dry forces practice mode", settings.load().mode == "dry")
del os.environ["HOUSELIGHTS_DRY"]

# --- a broken config.json opens the wizard instead of stopping the server ---
with open(settings.path("config.json"), "w") as f:
    f.write("{not json")
b = settings.load()
check("bad JSON: wizard with an error", not b.configured and "not valid JSON" in b.error)
st = setup.state()
check("wizard state shows the error", "not valid JSON" in st["error"] and st["config"]["runs"] == [])
with open(settings.path("config.json"), "w") as f:
    f.write('{"controllers": [{"id": "x", "model": "H806A", "ip": "192.0.2.9"}], "runs": [{"name": "R", "controller": "x", "lights": 999}]}')
b = settings.load()
st = setup.state()
check("invalid values: wizard keeps what was there", not b.configured and "between 1 and 255" in b.error
      and st["config"]["controllers"][0]["ip"] == "192.0.2.9")
settings.save(good())

# --- wizard test patterns ---
for name, (label, fn, animated) in setup.PATTERNS.items():
    for n in (1, 2, 50, 255):
        for t in (0.0, 0.7, 9.3):
            f = fn(n, t)
            assert len(f) == n and all(len(px) == 3 and all(0 <= v <= 255 for v in px) for px in f), (name, n, t)
check("test patterns give one colour per light", True)
r = setup._ruler(50, 0)
check("ruler: light 1 red, last blue, 10th white", r[0] == setup.RED and r[-1] == setup.BLUE and r[9] == setup.WHITE)
check("chase: dot moves", setup._chase(50, 0.0) != setup._chase(50, 1.0))
check("segments: groups of 5", setup._segments(12, 0, 5)[4] != setup._segments(12, 0, 5)[5])
pv = setup.preview_frames("chase", 20, 5, seconds=2, fps=8)
check("preview frames", len(pv) == 16 and len(pv[0]) == 20 and pv[0][-1] == "#0000ff" and pv[8][0] == "#ff0000")

# counting: markers, then the red lights of the last segment, give every length back
ok = True
for n in range(1, 256):
    for lps in (5, 3, 10):
        shown = setup._markers(255, 0, lps)[:n]                    # the controller shows its first n lights
        m = sum(1 for c in shown if c != setup.DIM_WHITE)
        red = sum(1 for c in setup._tail(255, 0, lps, m)[:n] if c == setup.RED)
        ok &= 1 <= red <= lps and lps * (m - 1) + red == n
check("counting finds every length 1-255 (5, 3 and 10 per segment)", ok)

# --- Govee packets and addresses ---
f = govee.razer_frame([(1, 2, 3), (4, 5, 6)])
x = 0
for b in f[:-1]:
    x ^= b
check("razer frame length and checksum", len(f) == 4 + 2 + 6 + 1 and f[-1] == x and f[5] == 2)
p = govee.segment_color_packet([0, 9], (255, 0, 0), 24)
check("segment packet: 20 bytes, 3-byte mask", len(p) == 20 and p[12:15] == bytes([0x01, 0x02, 0x00]))
check("targets: network", len(govee.expand_targets("192.0.2.0/30")) == 2)
check("targets: list", govee.expand_targets("192.0.2.5, 192.0.2.6") == ["192.0.2.5", "192.0.2.6"])
try:
    govee.expand_targets("10.0.0.0/8")
    check("targets: too big rejected", False)
except ValueError:
    check("targets: too big rejected", True)

print(f"\n{'ALL OK' if not FAILS else f'{len(FAILS)} FAILED'}")
sys.exit(1 if FAILS else 0)
