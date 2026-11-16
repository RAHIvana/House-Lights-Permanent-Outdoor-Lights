"""WLED, JellyFish and Tuya drivers against simulators: no real lights, local addresses only.

    python tests/test_drivers.py

WLED and JellyFish run their simulators (tools/) inside this test on 127.0.0.x and spare
ports; Tuya uses a stand-in for the tinytuya library. Linux (needs 127.0.0.2+ addresses).
"""
import importlib.util
import os
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOUSELIGHTS_HOME"] = tempfile.mkdtemp()
os.environ["HOUSELIGHTS_WLED_PORTS"] = "18181,21326"
os.environ["HOUSELIGHTS_JELLYFISH_PORT"] = "19101"

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def tool(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- a stand-in for tinytuya, before the drivers import it ---------------------------------------
CALLS = []
DPS = {"20": True, "21": "white", "22": 1000, "23": 500, "24": "000003e803e8"}


class FakeBulb:
    def __init__(self, dev_id, ip, key, **kw):
        self.dev_id, self.ip, self.key = dev_id, ip, key

    def set_version(self, v):
        pass

    def set_socketTimeout(self, t):
        pass

    def status(self):
        if self.key != "0123456789abcdef":
            return {"Error": "Check device key or version", "Err": "914"}
        return {"dps": dict(DPS)}

    def __getattr__(self, name):
        def call(*args):
            CALLS.append((name, args))
            if name == "set_multiple_values":
                DPS.update(args[0])
            return {"dps": {}}
        return call


sys.modules["tinytuya"] = types.SimpleNamespace(
    BulbDevice=FakeBulb,
    deviceScan=lambda verbose, seconds: {"127.0.0.41": {"ip": "127.0.0.41", "gwId": "abcdef0123456789abcd", "version": "3.3"}})

from houselights import drivers, settings, setup  # noqa: E402
from houselights.drivers import jellyfish, net, tuya, wled  # noqa: E402
from houselights.settings import Controller  # noqa: E402
from houselights.stream import Streamer  # noqa: E402

fw = tool("fake_wled").serve("127.0.0.21", 2, [60, 600], 18181, 21326)
fj = tool("fake_jellyfish").serve("127.0.0.31", 1, [("Front", 120), ("Back", 45)], 19101)
time.sleep(0.3)

# --- WLED ----------------------------------------------------------------------------------------
pk = wled.dnrgb_packets([(1, 2, 3)] * 600)
check("WLED DNRGB: 2 packets, header and start index", len(pk) == 2 and pk[0][:4] == bytes([4, 2, 0, 0])
      and pk[1][:4] == bytes([4, 2, 489 >> 8, 489 & 255]) and len(pk[0]) == 4 + 3 * 489)
calls = wled.i_calls([(255, 0, 0)] * 300)
check("WLED per-light calls: 256 + 44 colours", len(calls) == 2 and calls[1]["seg"]["i"][0] == 256
      and len(calls[0]["seg"]["i"]) == 257 and calls[0]["seg"]["i"][1] == "FF0000")
rows = wled.discover("127.0.0.21, 127.0.0.22, 127.0.0.23")
check("WLED discover finds 2 with their light counts", [(r["ip"], r["lights"]) for r in rows]
      == [("127.0.0.21", 60), ("127.0.0.22", 600)])
try:
    wled.probe({"ip": "127.0.0.29"})
    check("WLED probe: nothing there -> error", False)
except ValueError as e:
    check("WLED probe: nothing there -> error", "no WLED device" in str(e))
c = Controller("w1", "wled", "WLED", "127.0.0.21", "", True)
k = drivers.make_kit(c, live=True)
k.power(True)
k.brightness(50)
k.color((0, 0, 255))
check("WLED colour and brightness", fw[0].bri == 128 and fw[0].shown()[5] == [0, 0, 255])
st = wled.read_status([k])["w1"]
check("WLED status", st == {"onOff": 1, "brightness": 50, "color": {"r": 0, "g": 0, "b": 255}, "colorTemInKelvin": 0})
frame = [(i, 0, 255 - i) for i in range(60)]
with k.lock:
    k.show_lights(frame)
check("WLED per-light static frame", fw[0].shown()[10] == [10, 0, 245] and fw[0].shown()[59] == [59, 0, 196])
with k.lock:
    k.segments([0, 1, 2], (9, 9, 9), 60)
check("WLED pick lights", fw[0].shown()[:4] == [[9, 9, 9]] * 3 + [[3, 0, 252]])
s = Streamer(k, 60, 15)
s.start("diya_glow", {}, 100)
time.sleep(0.6)
check("WLED streaming: realtime mode", fw[0].live and fw[0].packets > 3)
s.stop()
time.sleep(2.4)
check("WLED back to normal 2 s after the last frame", not fw[0].live and fw[0].shown()[10] == [10, 0, 245])
k2 = drivers.make_kit(Controller("w2", "wled", "WLED", "127.0.0.22", "", True), live=True)
k2.stream_frame([(7, 7, 7)] * 600)
time.sleep(0.2)
check("WLED 600 lights over 2 packets", fw[1].live and fw[1].shown()[599] == [7, 7, 7])
kd = drivers.make_kit(Controller("w1", "wled", "WLED", "127.0.0.21", "", True), live=False)
before = fw[0].posts
kd.color((1, 2, 3))
check("WLED dry mode sends nothing", fw[0].posts == before)

# --- JellyFish ------------------------------------------------------------------------------------
pal, b = jellyfish.blocks([(255, 0, 0)] * 5 + [(255, 255, 255)] * 5 + [(0, 0, 255)] * 5)
check("JellyFish blocks: bands are exact", pal == [(255, 0, 0), (255, 255, 255), (0, 0, 255)] and b == 5)
pal, b = jellyfish.blocks([(1, 1, 1), (2, 2, 2)] * 40)
check("JellyFish blocks: repeating pattern", pal == [(1, 1, 1), (2, 2, 2)] and b == 1)
frame = [(i, i, i) for i in range(100)]
pal, b = jellyfish.blocks(frame)
check("JellyFish blocks: rounded to <= 30 colours", len(pal) <= 30 and b == 4)
rows = jellyfish.discover("127.0.0.31, 127.0.0.32")
check("JellyFish discover: one row per zone", [(r["zone"], r["lights"]) for r in rows] == [("Front", 120), ("Back", 45)])
cj = Controller("j1", "jellyfish", "JellyFish", "127.0.0.31", "", True, {"zone": "Front"})
kj = drivers.make_kit(cj, live=True)
kj.color((255, 0, 0))
z = fj[0]
check("JellyFish solid colour on its zone only", z.running["Front"]["state"] == 1 and z.shown("Front")[0] == "#ff0000"
      and z.running["Back"]["state"] == 0)
kj.brightness(40)
check("JellyFish brightness inside the pattern", z.running["Front"]["data"]["runData"]["brightness"] == 40)
bands = [(255, 0, 0)] * 5 + [(255, 255, 255)] * 5 + [(0, 0, 255)] * 5
with kj.lock:
    kj.show_lights((bands * 8)[:120])
shown = z.shown("Front")
check("JellyFish band theme as Multi-Paint", z.running["Front"]["data"]["type"] == "Multi-Paint"
      and shown[0] == "#ff0000" and shown[5] == "#ffffff" and shown[14] == "#0000ff" and shown[15] == "#ff0000")
kj.power(False)
check("JellyFish off", z.running["Front"]["state"] == 0)
check("JellyFish status: not reported", jellyfish.read_status([kj]) == {"j1": None})
try:
    Streamer(kj, 120).start("diya_glow", {})
    check("JellyFish refuses animated themes", False)
except ValueError:
    check("JellyFish refuses animated themes", True)
st = Streamer(kj, 120)
st.start_fn("test", lambda t: setup._identify_slow(120, t, 1.0), True, seconds=3, slow_ok=True)
time.sleep(0.5)
a = z.shown("Front")[0]
time.sleep(1.2)
bb = z.shown("Front")[0]
st.stop()
check("JellyFish slow blink test: white then blue", a == "#ffffff" and bb == "#0000ff")

# --- Tuya --------------------------------------------------------------------------------------
w = net.kelvin_to_rgb(4600)
check("Tuya type B status (white)", tuya.parse_dps(DPS) == {"onOff": 1, "brightness": 100, "colorTemInKelvin": 4600,
                                                             "color": {"r": w[0], "g": w[1], "b": w[2]}})
check("Tuya type A status", tuya.parse_dps({"1": True, "2": "colour", "3": 255, "5": "ff8000"})["color"]
      == {"r": 255, "g": 128, "b": 0})
check("Tuya red from HSV", tuya.parse_dps({"20": True, "21": "colour", "22": 500, "24": "000003e803e8"})["color"]
      == {"r": 255, "g": 0, "b": 0})
try:
    tuya.options({"device_id": "abcdef0123456789abcd", "local_key": "short"}, {})
    check("Tuya rejects a short key", False)
except ValueError as e:
    check("Tuya rejects a short key", "16 characters" in str(e))
check("Tuya discover", tuya.discover("")[0]["device_id"] == "abcdef0123456789abcd")
try:
    tuya.probe({"ip": "127.0.0.41", "device_id": "abcdef0123456789abcd", "local_key": "wrongwrongwrong!"})
    check("Tuya probe: wrong key -> error", False)
except OSError as e:
    check("Tuya probe: wrong key -> error", "914" in str(e))
check("Tuya probe: right key", tuya.probe({"ip": "127.0.0.41", "device_id": "abcdef0123456789abcd",
                                          "local_key": "0123456789abcdef"})[0]["label"] == "Tuya light (key works)")
ct = Controller("t1", "tuya", "Tuya light", "127.0.0.41", "", True, {"device_id": "abcdef0123456789abcd", "version": "3.3"},
                {"local_key": "0123456789abcdef"})
kt = drivers.make_kit(ct, live=True)
CALLS.clear()
kt.color((10, 20, 30))
kt.kelvin(2700)
kt.power(False)
check("Tuya commands", CALLS == [("set_colour", (10, 20, 30)), ("set_white_percentage", (100, 0)), ("turn_off", ())])
CALLS.clear()
before = dict(DPS)
st = Streamer(kt, 60)
st.start_fn("test", lambda t: [(255, 0, 0)] * 60, False, seconds=2, slow_ok=True)
time.sleep(0.3)
st.stop()
check("Tuya test shows a colour, then puts the light back",
      CALLS[0] == ("set_colour", (255, 0, 0)) and CALLS[-1][0] == "set_multiple_values" and DPS == before)

# --- settings with secrets ------------------------------------------------------------------------
cfg = {"controllers": [{"id": "t1", "type": "tuya", "model": "Tuya light", "ip": "127.0.0.41",
                        "device_id": "abcdef0123456789abcd", "local_key": "0123456789abcdef"},
                       {"id": "j1", "type": "jellyfish", "model": "JellyFish", "ip": "127.0.0.31", "zone": "Front"},
                       {"id": "j2", "type": "jellyfish", "model": "JellyFish", "ip": "127.0.0.31", "zone": "Back"},
                       {"id": "w1", "type": "wled", "model": "WLED", "ip": "127.0.0.21"}],
       "runs": [{"name": "Porch", "controller": "t1", "lights": 60}, {"name": "Front", "controller": "j1", "lights": 120},
                {"name": "Back", "controller": "j2", "lights": 45}, {"name": "Garage", "controller": "w1", "lights": 60}]}
settings.save(cfg)
raw = open(settings.path("config.json")).read()
mode = os.stat(settings.path("secrets.json")).st_mode & 0o777
check("local key kept out of config.json, secrets.json is private", "0123456789abcdef" not in raw and mode == 0o600)
s = settings.load()
check("loaded with options and secret", s.controllers["t1"].secret == {"local_key": "0123456789abcdef"}
      and s.controllers["j2"].options == {"zone": "Back"} and s.sections["garage"].lights_per_segment == 1)
cfg2 = dict(cfg)
cfg2["controllers"] = [dict(c) for c in cfg["controllers"]]
cfg2["controllers"][0].pop("local_key")
settings.save(cfg2)
check("saving again without retyping the key keeps it", settings.load().controllers["t1"].secret.get("local_key")
      == "0123456789abcdef")
pub = settings.public_config(settings.validate(settings.read_raw()))
check("the page never gets the key", "0123456789abcdef" not in str(pub) and pub["controllers"][0]["has_secret"])
try:
    settings.validate(dict(cfg, controllers=cfg["controllers"] + [dict(cfg["controllers"][1], id="j3")]))
    check("same JellyFish zone twice rejected", False)
except ValueError as e:
    check("same JellyFish zone twice rejected", "used twice" in str(e))
check("tests offered per controller", setup.allowed_tests(drivers.caps("tuya")) == ["identify"]
      and setup.allowed_tests(drivers.caps("jellyfish")) == ["identify", "rgb"]
      and "markers" not in setup.allowed_tests(drivers.caps("wled"))
      and "markers" in setup.allowed_tests(drivers.caps("govee")))
check("kelvin to RGB looks warm", net.kelvin_to_rgb(2200)[0] == 255 and net.kelvin_to_rgb(2200)[2] < 120)

print(f"\n{'ALL OK' if not FAILS else f'{len(FAILS)} FAILED'}")
sys.exit(1 if FAILS else 0)
