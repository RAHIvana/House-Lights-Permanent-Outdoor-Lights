"""Settings, wizard test patterns and Govee packets: no lights, no network.

    python tests/test_settings.py
"""
import json
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

# where light 1 is: light1 decides reverse; old files without it keep their reverse
check("old file: reverse kept, light1 from it", (c["runs"][0]["light1"], c["runs"][0]["reverse"]) == ("", False)
      and (c["runs"][1]["light1"], c["runs"][1]["reverse"]) == ("right", True))
lr = settings.validate(good(runs=[{"name": "A", "controller": "porch", "lights": 5, "light1": "right"},
                                  {"name": "B", "controller": "garage", "lights": 5, "light1": "left", "reverse": True}]))
check("light1 right -> reverse; left wins over a stale reverse",
      [(r["light1"], r["reverse"]) for r in lr["runs"]] == [("right", True), ("left", False)])
check("light1 '' (not checked yet) is allowed, not reversed",
      [(r["light1"], r["reverse"]) for r in settings.validate(good(runs=[
          {"name": "A", "controller": "porch", "lights": 5, "light1": "", "reverse": True}]))["runs"]] == [("", False)])
rejects("bad light1", good(runs=[{"name": "A", "controller": "porch", "lights": 5, "light1": "middle"}]), "left or right")
check("run order kept (left to right along the house)",
      [r["name"] for r in settings.validate(good(runs=list(reversed(good()["runs"]))))["runs"]] == ["Garage", "Porch eaves"])

# location: optional ZIP and place, lat/lon rounded to 4 decimals
lc = settings.validate(good(location={"lat": 40.712812, "lon": "-74.00601", "zip": " 12345 ", "place": "Springfield, IL"}))
check("location with zip and place", lc["location"] == {"lat": 40.7128, "lon": -74.006, "zip": "12345", "place": "Springfield, IL"})
check("location without zip/place has no empty keys",
      settings.validate(good(location={"lat": 1, "lon": 2, "zip": "", "place": None}))["location"] == {"lat": 1.0, "lon": 2.0})
rejects("zip too long", good(location={"lat": 1, "lon": 2, "zip": "12345678901"}), "ZIP code")
rejects("place too long", good(location={"lat": 1, "lon": 2, "place": "x" * 65}), "place name")

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

# --- Govee models in tiers: full (H806A), try (permanent outdoor families), basic (any other SKU) ---
from houselights import drivers  # noqa: E402

mi = {m: drivers.model_info("govee", m) for m in ("H806A", "H706B", "H7060", "h705a")}
check("model_info tiers", [mi[m]["tier"] for m in ("H806A", "H706B", "H7060")] == ["full", "try", "basic"])
check("model_info labels", mi["H806A"]["label"] == "Govee H806A" and mi["H7060"]["label"] == "Govee H7060")
check("model_info limits", (mi["H806A"]["max_lights"], mi["H806A"]["lights_per_segment"]) == (255, 5)
      and (mi["H706B"]["max_lights"], mi["H706B"]["lights_per_segment"]) == (255, 0)
      and (mi["H7060"]["max_lights"], mi["H7060"]["lights_per_segment"]) == (3000, 0))
check("model_info caps", mi["H806A"]["caps"]["stream"] and mi["H806A"]["caps"]["pick"]
      and not mi["H806A"]["caps"].get("stream_untested")
      and mi["H706B"]["caps"]["stream"] and mi["H706B"]["caps"]["stream_untested"] and not mi["H706B"]["caps"]["pick"]
      and not mi["H7060"]["caps"]["stream"] and not mi["H7060"]["caps"]["pick"]
      and mi["H7060"]["caps"]["restore"] == "snapshot")
check("model_info: lower case SKU read as upper case", mi["h705a"]["model"] == "H705A" and mi["h705a"]["tier"] == "try")
check("model_info: garbage is not a model", all(drivers.model_info("govee", m) is None
                                                for m in ("", "H99", "H999", "X806A", "H806A!", "H806AB7", None)))
check("model_info: other drivers from MODELS", drivers.model_info("wled", "WLED")["max_lights"] == 1500
      and drivers.model_info("wled", "WLED")["tier"] is None and drivers.model_info("wled", "H806A") is None)
check("model_caps per model", drivers.model_caps("govee", "H7060")["stream"] is False
      and drivers.model_caps("govee", "H806A")["stream"] is True)
cat = {d["type"]: d for d in drivers.catalog()}
check("catalog: Govee summary, tiers and a models note", cat["govee"]["models"] == {"H806A": "Govee H806A"}
      and set(cat["govee"]["tiers"]) == {"full", "try", "basic"} and "H706A" in cat["govee"]["models_note"]
      and cat["govee"]["model_info"]["H706B"]["tier"] == "try")

tiers = good(controllers=[{"id": "a", "model": "H806A", "ip": "192.0.2.21"},
                          {"id": "b", "model": "H706B", "ip": "192.0.2.22"},
                          {"id": "c", "model": "H7060", "ip": "192.0.2.23"}],
             runs=[{"name": "A", "controller": "a", "lights": 50}, {"name": "B", "controller": "b", "lights": 200},
                   {"name": "C", "controller": "c", "lights": 2500}])
check("H706B and H7060 runs accepted", [r["lights"] for r in settings.validate(tiers)["runs"]] == [50, 200, 2500])
rejects("too many lights on a try model", dict(tiers, runs=[{"name": "B", "controller": "b", "lights": 300}]),
        "between 1 and 255")
rejects("too many lights on a basic model", dict(tiers, runs=[{"name": "C", "controller": "c", "lights": 3001}]),
        "between 1 and 3000")
rejects("garbage Govee model", good(controllers=[{"id": "x", "model": "lamp", "ip": "192.0.2.1"}],
                                    runs=[{"name": "a", "controller": "x", "lights": 5}]), "not supported")
settings.save(tiers)
ts = settings.load()
pa, pb, pc = (ts.sections[k].public() for k in ("a", "b", "c"))
check("Section.public: tier and caps per run",
      (pa["tier"], pb["tier"], pc["tier"]) == ("full", "try", "basic")
      and pa["caps"]["stream"] and pa["caps"]["pick"] and pb["caps"]["stream"] and pb["caps"]["stream_untested"]
      and not pb["caps"]["pick"] and not pc["caps"]["stream"] and pc["model_label"] == "Govee H7060")
check("segments: 5 per segment on H806A, one (the whole run) on the others",
      (pa["segments"], pa["lights_per_segment"]) == (10, 5) and (pb["segments"], pb["lights_per_segment"]) == (1, 0)
      and pc["segments"] == 1)
sw = setup.state()
gv = next(d for d in sw["drivers"] if d["type"] == "govee")
check("wizard state: per-model limits, tiers and tests (also for a basic model in the config)",
      gv["max_lights"]["H706B"] == 255 and gv["max_lights"]["H7060"] == 3000
      and gv["model_info"]["H7060"]["tier"] == "basic" and gv["model_info"]["H7060"]["tests"] == ["identify"]
      and "ends" in gv["model_info"]["H706B"]["tests"] and "segments" not in gv["model_info"]["H706B"]["tests"]
      and gv["tiers"]["basic"]["tests"] == ["identify"] and "segments" in gv["tests"])
os.remove(settings.path("config.json"))

# --- save and load ---
check("no file: not configured", settings.load().configured is False)
settings.save(good())
s = settings.load()
check("saved and loaded", s.configured and list(s.sections) == ["porch_eaves", "garage"])
sec = s.sections["garage"]
check("segments from the model (120 / 5)", sec.segments == 24 and sec.lights_per_segment == 5)
check("disabled controller", not sec.enabled and s.sections["porch_eaves"].enabled)
check("location tuple", s.location == (40.7128, -74.006) and s.timezone == "America/New_York")
pub = sec.public()
check("section.public() has light1 and reverse", pub["light1"] == "right" and pub["reverse"] is True
      and s.sections["porch_eaves"].public()["light1"] == "")
os.environ["HOUSELIGHTS_DRY"] = "1"
check("--dry forces practice mode", settings.load().mode == "dry")
del os.environ["HOUSELIGHTS_DRY"]

# --- config.json edited by hand (Notepad: UTF-8, maybe with a BOM), names beyond ASCII ---
NAME = "Façade ✨ दीप"
with open(settings.path("config.json"), "w", encoding="utf-8-sig") as f:
    json.dump(good(runs=[{"name": NAME, "controller": "porch", "lights": 60}]), f, ensure_ascii=False)
u = settings.load()
check("hand-edited UTF-8 config.json with a BOM loads", u.configured and [x.name for x in u.sections.values()] == [NAME])

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
check("test patterns give one color per light", True)
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
