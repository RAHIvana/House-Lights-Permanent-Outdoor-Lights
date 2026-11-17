"""WLED, JellyFish and Tuya drivers against simulators: no real lights, local addresses only.

    python tests/test_drivers.py

WLED and JellyFish run their simulators (tools/) inside this test on 127.0.0.x and spare
ports; Tuya uses a stand-in for the tinytuya library. Linux and Windows (needs 127.0.0.2+
addresses, so not macOS).
"""
import importlib.util
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOUSELIGHTS_HOME"] = tempfile.mkdtemp()
os.environ["HOUSELIGHTS_WLED_PORTS"] = "18181,21326"
os.environ["HOUSELIGHTS_JELLYFISH_PORT"] = "19101"
os.environ["HOUSELIGHTS_GOVEE_PORTS"] = "14101,14102,14103"

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
from houselights.drivers import govee, jellyfish, net, tuya, wled  # noqa: E402
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
r = setup.discover({"types": ["wled"], "targets": "127.0.0.21, 127.0.0.22", "deep": True, "known": {"wled": ["127.0.0.21"]}})
check("wizard deep scan skips controllers it already has", [d["ip"] for d in r["devices"]] == ["127.0.0.22"])
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
time.sleep(0.2)
check("WLED: stopping the stream releases realtime mode at once, back to the normal look",
      not fw[0].live and fw[0].released >= 1 and fw[0].shown()[10] == [10, 0, 245])
k2 = drivers.make_kit(Controller("w2", "wled", "WLED", "127.0.0.22", "", True), live=True)
k2.stream_frame([(7, 7, 7)] * 600)
time.sleep(0.2)
check("WLED 600 lights over 2 packets", fw[1].live and fw[1].shown()[599] == [7, 7, 7])
kd = drivers.make_kit(Controller("w1", "wled", "WLED", "127.0.0.21", "", True), live=False)
before = fw[0].posts
kd.color((1, 2, 3))
check("WLED dry mode sends nothing", fw[0].posts == before)


# WLED packets, checked by a receiver written from WLED's own rules (wled00/udp.cpp), not from our encoder
def wled_receiver(packets, n):
    """What WLED shows after these packets: DRGB (2) applies pixels if the packet is longer than 4 bytes,
    DNRGB (4) if longer than 7; timeout 0 applies nothing; at most 1472 bytes per packet."""
    shown = [None] * n
    for p in packets:
        if len(p) > 1472:
            return None
        if len(p) < 2 or p[0] not in (2, 4) or p[1] == 0:
            continue
        if p[0] == 2 and len(p) > 4:
            start, first = 0, 2
        elif p[0] == 4 and len(p) > 7:
            start, first = (p[2] << 8) + p[3], 4
        else:
            continue
        for j, i in enumerate(range(first, len(p) - 2, 3)):
            if start + j < n:
                shown[start + j] = tuple(p[i:i + 3])
    return shown


def wled_frame(n):
    return [(i % 256, (i // 256) % 256, 7) for i in range(n)]


lost = [n for n in (1, 2, 3, 488, 489, 490, 491, 978, 979, 980, 1468, 1500)
        if wled_receiver(wled.dnrgb_packets(wled_frame(n)), n) != wled_frame(n)]
check(f"WLED packets: every light arrives, for 1 to 1500 lights (lost: {lost})", not lost)
check("WLED packets: a lone light goes as DRGB, and 490 lights are 488 + 2",
      wled.dnrgb_packets([(9, 8, 7)]) == [bytes([2, 2, 9, 8, 7])]
      and [(len(p) - 4) // 3 for p in wled.dnrgb_packets(wled_frame(490))] == [488, 2])
check("WLED receiver model: a one-light DNRGB packet (7 bytes) is ignored, as in the firmware",
      wled_receiver([bytes([4, 2, 0, 0, 1, 2, 3])], 1) == [None])
k2.stream_frame(wled_frame(490))
k.stream_frame([(5, 6, 7)])
time.sleep(0.3)
check("WLED simulator: 490 lights including the last two, and a one-light frame, arrive",
      [tuple(c) for c in fw[1].live_frame[:490]] == wled_frame(490) and fw[0].live_frame[0] == [5, 6, 7])
time.sleep(2.4)
check("WLED: a sender that vanishes without releasing: back to normal after the 2 s timeout",
      not fw[1].live and not fw[0].live)


class FakeUdp:
    def __init__(self):
        self.sent = []

    def sendto(self, pkt, addr):
        self.sent.append((bytes(pkt), addr))


def wled_kit(info, ip="127.0.0.51", live=True, enabled=True):
    """A kit whose /json/info is `info` (a dict, or a function of the URL) and whose UDP socket records."""
    net.http_json = lambda url, body=None, timeout=3.0: info(url) if callable(info) else info
    kk = drivers.make_kit(Controller("wp", "wled", "WLED", ip, "", enabled), live=live)
    kk.udp = FakeUdp()
    return kk


def refuse(url):
    raise OSError("no route")


real_http = net.http_json
logging.disable(logging.CRITICAL)             # the driver logs the odd ports below; the checks look at what it did
try:
    kk = wled_kit({"udpport": 12345})
    kk.stream_begin()
    kk.stream_frame([(1, 2, 3)] * 3)
    kk.stream_end()
    sent = kk.udp.sent
    check("WLED: frames and the release go to the controller's own port, the release last",
          len(sent) == 2 and {a for _, a in sent} == {("127.0.0.51", 12345)} and sent[0][0][0] == 4
          and sent[1][0] == wled.RELEASE)
    kk.stream_end()
    check("WLED: releasing twice sends nothing more", len(kk.udp.sent) == 2)
    check("WLED: no release for a session this kit didn't start", wled_kit({"udpport": 12345}).udp.sent == [])

    two = lambda url: {"udpport": 12345 if "127.0.0.51" in url else 23456}      # noqa: E731
    ka, kb = wled_kit(two, "127.0.0.51"), wled_kit(two, "127.0.0.52")
    ka.stream_frame([(1, 1, 1)] * 2)
    kb.stream_frame([(1, 1, 1)] * 2)
    check("WLED: two controllers, two ports", ka.udp.sent[0][1] == ("127.0.0.51", 12345)
          and kb.udp.sent[0][1] == ("127.0.0.52", 23456))

    ports = []
    for odd in ({"udpport": 0}, {"udpport": 70000}, {"udpport": -1}, {"udpport": "21324"}, {"udpport": None},
                {"udpport": True}, {"udpport": 21324.5}, {}, refuse):
        ko = wled_kit(odd)
        ko.stream_frame([(1, 1, 1)] * 2)
        ports.append(ko.udp.sent[0][1][1])
    check("WLED: a missing, invalid or unreadable port falls back to the default", set(ports) == {wled.UDP_PORT})

    box = {"udpport": 12345}
    kr = wled_kit(lambda url: dict(box))
    kr.stream_begin()
    kr.stream_frame([(1, 1, 1)] * 2)
    kr.stream_end()
    box["udpport"] = 23456
    kr.stream_begin()
    kr.stream_frame([(1, 1, 1)] * 2)
    kr.stream_end()
    check("WLED: the port is read again for every stream", [a[1] for _, a in kr.udp.sent] == [12345, 12345, 23456, 23456])

    asked = []
    net.http_json = lambda url, body=None, timeout=3.0: asked.append(url) or {}
    kp = drivers.make_kit(Controller("wp", "wled", "WLED", "127.0.0.51", "", True), live=False)
    kp.udp = FakeUdp()
    kp.stream_begin()
    kp.stream_frame([(1, 1, 1)] * 2)
    kp.stream_end()
    check("WLED dry mode: no UDP and no HTTP while streaming", kp.udp.sent == [] and asked == [])

    kx = wled_kit({"udpport": 12345}, enabled=False)
    try:
        kx.stream_frame([(1, 1, 1)] * 2)
        blocked = False
    except drivers.NotAllowed:
        blocked = True
    kx.stream_end()
    check("WLED: a disabled controller gets no frames and no release", blocked and kx.udp.sent == [])
finally:
    net.http_json = real_http
    logging.disable(logging.NOTSET)

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


# JellyFish: brightness needs a pattern we sent, and a zone that was switched off stays off
zb = fj[0]
kb = drivers.make_kit(Controller("j2", "jellyfish", "JellyFish", "127.0.0.31", "", True, {"zone": "Back"}), live=True)
try:
    kb.brightness(30)
    said = False
except ValueError as e:
    said = "pick a colour or theme" in str(e)
check("JellyFish: brightness before any colour or theme says so, and sends nothing",
      said and zb.running["Back"]["data"] is None and zb.running["Back"]["state"] == 0)
kb.power(True)
kb.brightness(30)
check("JellyFish: power on shows a pattern, and brightness then applies to it",
      zb.running["Back"]["state"] == 1 and zb.running["Back"]["data"]["runData"]["brightness"] == 30)
kb.color((0, 255, 0))
kb.power(False)
kb.brightness(60)
check("JellyFish: brightness on a zone that is off keeps it off, with the new level",
      zb.running["Back"]["state"] == 0 and zb.running["Back"]["data"]["runData"]["brightness"] == 60)
kb.power(True)
check("JellyFish: switching on afterwards uses that level",
      zb.running["Back"]["state"] == 1 and zb.running["Back"]["data"]["runData"]["brightness"] == 60)
kb.brightness(80)
check("JellyFish: brightness on a zone that is on keeps it on",
      zb.running["Back"]["state"] == 1 and zb.running["Back"]["data"]["runData"]["brightness"] == 80)
kb.power(False)
with kb.lock:
    kb.show_lights([(255, 0, 0)] * 45)
check("JellyFish: a new theme switches the zone on", zb.running["Back"]["state"] == 1)

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


# Tuya: one thing at a time on the device object (the dashboard asks for status every 15 s while commands run)
class SlowBulb(FakeBulb):
    made = active = most = 0
    fail = False
    gate = threading.Lock()

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        SlowBulb.made += 1

    def _busy(self, result):
        with SlowBulb.gate:
            SlowBulb.active += 1
            SlowBulb.most = max(SlowBulb.most, SlowBulb.active)
        time.sleep(0.05)
        with SlowBulb.gate:
            SlowBulb.active -= 1
        return result

    def status(self):
        if SlowBulb.fail:
            raise OSError("boom")
        return self._busy({"dps": dict(DPS)})

    def set_colour(self, *args):
        CALLS.append(("set_colour", args))
        return self._busy({"dps": {}})


tt = sys.modules["tinytuya"]
real_bulb = tt.BulbDevice
tt.BulbDevice = SlowBulb
try:
    ks = drivers.make_kit(ct, live=True)
    jobs = [lambda: ks.color((1, 2, 3)), ks.status, ks.snapshot, lambda: ks.color((4, 5, 6)), ks.status]
    start = threading.Barrier(len(jobs))
    errors = []

    def go(fn):
        try:
            start.wait(5)
            fn()
        except Exception as e:                    # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go, args=(fn,)) for fn in jobs]
    for th in threads:
        th.start()
    for th in threads:
        th.join(15)
    check("Tuya: commands, status and snapshot never use the device at the same time, and one device is made",
          not errors and SlowBulb.most == 1 and SlowBulb.made == 1)
    SlowBulb.fail = True
    try:
        ks.status()
    except OSError:
        pass
    SlowBulb.fail = False
    freed = ks.lock.acquire(timeout=1)
    if freed:
        ks.lock.release()
    check("Tuya: a failing status call doesn't leave the lock held", freed and ks.status()["onOff"] == 1)
finally:
    tt.BulbDevice = real_bulb
kdis = drivers.make_kit(Controller("t2", "tuya", "Tuya light", "127.0.0.41", "", False,
                                   {"device_id": "abcdef0123456789abcd", "version": "3.3"},
                                   {"local_key": "0123456789abcdef"}), live=True)
CALLS.clear()
try:
    kdis.restore({"20": True})
    refused = False
except drivers.NotAllowed:
    refused = True
check("Tuya: a disabled controller gets no restore", refused and CALLS == [])


# --- Tuya brightness: what is read is what is set; never switched off; colours and whites keep it -------------
check("Tuya brightness: white mode reads the white level (type B, 100 of 1000 = 10%)",
      tuya.parse_dps({"20": True, "21": "white", "22": 100, "23": 0})["brightness"] == 10)
check("Tuya brightness: colour mode reads the colour's value, not the white level",
      tuya.parse_dps({"20": True, "21": "colour", "22": 1000, "24": "000003e803e8"})["brightness"] == 100
      and tuya.parse_dps({"20": True, "21": "colour", "22": 1000, "24": "000003e800c8"})["brightness"] == 20)
check("Tuya brightness: type A white 51 of 255 = 20%, and type A colour value 51 = 20%",
      tuya.parse_dps({"1": True, "2": "white", "3": 51})["brightness"] == 20
      and tuya.parse_dps({"1": True, "2": "colour", "3": 255, "5": "ff00000000ff33"})["brightness"] == 20)
check("Tuya brightness: unknown stays unknown (no made-up 100%), and bad data doesn't crash",
      tuya.parse_dps({"20": True, "21": "white"})["brightness"] is None
      and tuya.parse_dps({"20": True, "21": "colour", "24": "zzzz"})["brightness"] is None
      and tuya.parse_dps({"20": True, "21": "colour", "22": "x", "24": "zzzzzzzzzzzz"})["brightness"] is None)

# the real TinyTuya, if it is installed: what its set_brightness_percentage sends reads back as the same percent
stand_in = sys.modules.pop("tinytuya")
try:
    import importlib
    real_tt = importlib.import_module("tinytuya")
except Exception:                                     # noqa: BLE001
    real_tt = None
finally:
    sys.modules.pop("tinytuya", None)
    sys.modules["tinytuya"] = stand_in
if real_tt is None:
    check("Tuya brightness round trip with TinyTuya's own scales: skipped (tinytuya not installed)", True)
else:
    scales, worst = real_tt.BulbDevice.DEFAULT_DPSET, 0
    for kind, make in (("A", lambda raw: {"1": True, "2": "white", "3": raw}),
                       ("B", lambda raw: {"20": True, "21": "white", "22": raw})):
        vmin, vmax = scales[kind]["value_min"], scales[kind]["value_max"]
        for pct in range(-(-vmin * 100 // vmax), 101):
            raw = int(vmax * pct // 100)                 # what set_brightness_percentage(pct) sends
            worst = max(worst, abs(tuya.parse_dps(make(raw))["brightness"] - pct))
    check(f"Tuya brightness round trip with TinyTuya's own scales: set then read differs by at most 1% (worst {worst})",
          worst <= 1)


class TypedBulb(FakeBulb):
    dps = {}
    broken = False

    def status(self):
        if self.broken:
            raise OSError("no answer")
        return {"dps": dict(self.dps)}


class TypeA(TypedBulb):
    dps = {"1": True, "2": "white", "3": 255, "4": 0, "5": "ff00000000ffff"}


class TypeB(TypedBulb):
    dps = {"20": True, "21": "white", "22": 1000, "23": 0, "24": "000003e803e8"}


class TypeB40(TypedBulb):                             # a type B light that is at 40% in white mode
    dps = {"20": True, "21": "white", "22": 400, "23": 0, "24": "000003e803e8"}


class TypeBColour20(TypedBulb):                       # in colour mode at 20%
    dps = {"20": True, "21": "colour", "22": 1000, "23": 0, "24": "000003e800c8"}


class TypeBSilent(TypeB):
    broken = True


class PlugBulb(TypedBulb):
    dps = {"1": True, "9": 0}


tt = sys.modules["tinytuya"]
orig_bulb = tt.BulbDevice


def tuya_kit(bulb):
    tt.BulbDevice = bulb
    return drivers.make_kit(ct, live=True)


try:
    for bulb, low in ((TypeA, 10), (TypeB, 1)):
        kk = tuya_kit(bulb)
        CALLS.clear()
        for v in (0, 5, 100):
            kk.brightness(v)
        got = [c[1][0] for c in CALLS if c[0] == "set_brightness_percentage"]
        check(f"Tuya type {bulb.__name__[-1]}: the slider never goes below {low}%, so it never switches the light off",
              got == [low, max(low, 5), 100])

    kk = tuya_kit(TypeB40)
    CALLS.clear()
    kk.color((200, 100, 0))
    kk.kelvin(2700)
    kk.brightness(50)
    kk.color((200, 100, 0))
    check("Tuya: colours and whites start from the light's own 40%, and keep the slider's brightness once it is set",
          CALLS == [("set_colour", (80, 40, 0)), ("set_white_percentage", (40, 0)),
                    ("set_brightness_percentage", (50,)), ("set_colour", (100, 50, 0))])
    check("Tuya status: colour mode reports the colour's brightness, an unreadable value stays None",
          tuya_kit(TypeBColour20).status()["brightness"] == 20
          and tuya.parse_dps({"20": True, "21": "white"})["brightness"] is None)

    kk = tuya_kit(TypeBSilent)
    CALLS.clear()
    kk.color((200, 100, 0))
    kk.kelvin(2700)
    check("Tuya: a light that can't be read: colours go out as they are and whites keep the light's own level",
          CALLS == [("set_colour", (200, 100, 0)), ("set_colourtemp_percentage", (0,))])

    kk = tuya_kit(TypeB40)
    CALLS.clear()
    stt = Streamer(kk, 60)
    stt.start_fn("test", lambda t: [(255, 0, 0)] * 60, False, seconds=2, slow_ok=True)
    time.sleep(0.3)
    stt.stop()
    check("Tuya: a wizard test shows its colour at full brightness so it can be seen, whatever the light is set to",
          CALLS[0] == ("set_colour", (255, 0, 0)))

    # plugs, switches and dimmers are not lights
    cases = {"plug": {"1": True, "9": 0}, "dimmer switch": {"1": True, "2": 10, "3": 10, "4": "incandescent"},
             "two-socket switch": {"1": True, "2": True, "3": False},
             "white-only bulb": {"20": True, "21": "white", "22": 60}, "no data points": {}, "power only, type B": {"20": True}}
    wrongly = [name for name, dps in cases.items() if tuya.looks_like_light(dps)]
    check(f"Tuya: plugs, switches, dimmers and white-only bulbs are not colour lights {wrongly}", not wrongly)
    check("Tuya: colour lights of type A and B are", tuya.looks_like_light(TypeA.dps) and tuya.looks_like_light(TypeB.dps)
          and tuya.looks_like_light({str(k): v for k, v in TypeB.dps.items()}))
    tt.BulbDevice = PlugBulb
    try:
        tuya.probe({"ip": "127.0.0.41", "device_id": "abcdef0123456789abcd", "local_key": "0123456789abcdef"})
        message = ""
    except ValueError as e:
        message = str(e)
    check("Tuya probe: a plug whose key works is refused, with a reason", "colour light" in message and "plug" in message)
    tt.BulbDevice = TypeB
    check("Tuya probe: a colour light is accepted",
          tuya.probe({"ip": "127.0.0.41", "device_id": "abcdef0123456789abcd", "local_key": "0123456789abcdef"})[0]["supported"])
finally:
    tt.BulbDevice = orig_bulb

# --- Govee scan: retries the addresses that didn't answer ----------------------------------------
ASKED = {}


def lossy_govee(ip, drop_first, every=1):
    """A Govee device that answers "scan": optionally not the first request, and then only
    every `every`th one (real controllers ignore many requests)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((ip, govee.SCAN_PORT))

    def loop():
        while True:
            data, (src, _) = s.recvfrom(4096)
            ASKED[ip] = ASKED.get(ip, 0) + 1
            if (drop_first and ASKED[ip] == 1) or ASKED[ip] % every:
                continue
            reply = {"msg": {"cmd": "scan", "data": {"ip": ip, "device": "FA:KE:00:00:00:00:00:01", "sku": "H806A"}}}
            s.sendto(json.dumps(reply).encode(), (src, govee.REPLY_PORT))
    threading.Thread(target=loop, daemon=True).start()


lossy_govee("127.0.0.12", drop_first=True)
lossy_govee("127.0.0.13", drop_first=False)
t0 = time.time()
found = govee.LAN.scan(["127.0.0.12", "127.0.0.13", "127.0.0.14"], wait=1.5, multicast=False)
check("Govee scan: a device that missed the first request is found in a later round",
      sorted(found) == ["127.0.0.12", "127.0.0.13"] and ASKED == {"127.0.0.12": 2, "127.0.0.13": 1})
t0 = time.time()
rows = govee.probe({"ip": "127.0.0.13"})
check("Govee add by address: stops as soon as it answers", len(rows) == 1 and time.time() - t0 < 0.5)
lossy_govee("127.0.0.15", drop_first=False, every=15)     # answers one request in 15
lossy_govee("127.0.0.16", drop_first=False)
quick = govee.discover("127.0.0.15, 127.0.0.16")
check("Govee quick scan: 10 tries miss a controller that answers 1 in 15",
      [r["ip"] for r in quick] == ["127.0.0.16"] and ASKED["127.0.0.15"] == 10)
t0, before = time.time(), ASKED["127.0.0.16"]
deep = govee.discover("127.0.0.15, 127.0.0.16", deep=True, expect=2, known=["127.0.0.16"])
check("Govee deep scan finds it, skips the known one, stops once all are found",
      [r["ip"] for r in deep] == ["127.0.0.15"] and ASKED["127.0.0.16"] == before and time.time() - t0 < 10)

# --- Govee models in tiers, against the simulator --------------------------------------------------
fg_try = tool("fake_govee").serve("127.0.0.17", 1, "H706B", [50])
fg_basic = tool("fake_govee").serve("127.0.0.18", 1, "H7060", [40], razer=False)
time.sleep(0.2)
rows = {r["ip"]: r for r in govee.discover("127.0.0.17, 127.0.0.18")}
check("Govee scan: an H706B is supported, tier try", rows.get("127.0.0.17", {}).get("supported")
      and rows["127.0.0.17"]["tier"] == "try" and rows["127.0.0.17"]["label"] == "Govee H706B")
check("Govee scan: an H7060 is supported, tier basic", rows.get("127.0.0.18", {}).get("supported")
      and rows["127.0.0.18"]["tier"] == "basic" and rows["127.0.0.18"]["model"] == "H7060")
check("Govee scan row for garbage: not supported", not govee._row("127.0.0.19", {"sku": "?"})["supported"])
kfull = drivers.make_kit(Controller("gf", "govee", "H806A", "127.0.0.17", "", True), live=False)
ktry = drivers.make_kit(Controller("gt", "govee", "H706B", "127.0.0.17", "", True), live=True)
kbasic = drivers.make_kit(Controller("gb", "govee", "H7060", "127.0.0.18", "", True), live=True)
check("Govee kit caps per model", kfull.caps["pick"] and ktry.caps["stream_untested"] and not ktry.caps["pick"]
      and not kbasic.caps["stream"] and kbasic.caps["restore"] == "snapshot")


def refuses(kit, fn):
    try:
        with kit.lock:
            fn()
    except drivers.NotAllowed:
        return True
    return False


check("Govee try and basic kits refuse segment colours",
      refuses(ktry, lambda: ktry.segments([0], (1, 2, 3), 10)) and refuses(kbasic, lambda: kbasic.segments([0], (1, 2, 3), 10))
      and fg_try["127.0.0.17"]["segment_packets"] == 0)
check("Govee basic kit refuses streaming", refuses(kbasic, kbasic.stream_begin)
      and refuses(kbasic, lambda: kbasic.stream_frame([(1, 1, 1)])) and fg_basic["127.0.0.18"]["ignored"] == 0)
s = Streamer(ktry, 50, 15)
s.start("diya_glow", {}, 100)
time.sleep(0.8)
d = fg_try["127.0.0.17"]
check("Govee try kit streams per light", d["streaming"] and d["frames"] > 3 and len(d["last_frame"]) == 50)
s.stop()
time.sleep(0.2)
check("Govee try kit: stream stopped", not d["streaming"])
kbasic.power(True)
kbasic.brightness(70)
kbasic.color((10, 20, 30))
b = fg_basic["127.0.0.18"]
check("Govee basic kit: on, brightness, colour", (b["onOff"], b["brightness"], b["color"]) == (1, 70, {"r": 10, "g": 20, "b": 30}))
kbasic.kelvin(3000)
check("Govee basic kit: white", b["colorTemInKelvin"] == 3000)
st = govee.read_status([kbasic])["gb"]
check("Govee basic kit: status", st and st["brightness"] == 70 and st["colorTemInKelvin"] == 3000)
try:
    Streamer(kbasic, 40).start("diya_glow", {})
    check("Govee basic kit: animated themes refused", False)
except ValueError:
    check("Govee basic kit: animated themes refused", True)
st = Streamer(kbasic, 40)
st.start_fn("test", lambda t: [(255, 0, 0)] * 40, False, seconds=3, slow_ok=True)
time.sleep(2.0)
shown = dict(b["color"])
st.stop()
check("Govee basic test: shows the colour, then puts the light back",
      shown == {"r": 255, "g": 0, "b": 0} and b["colorTemInKelvin"] == 3000 and b["brightness"] == 70 and b["onOff"] == 1)
check("Govee tests per model", setup.allowed_tests(drivers.model_caps("govee", "H7060")) == ["identify"]
      and "ends" in setup.allowed_tests(drivers.model_caps("govee", "H706B"))
      and "segments" not in setup.allowed_tests(drivers.model_caps("govee", "H706B")))

# --- settings with secrets ------------------------------------------------------------------------
cfg = {"controllers": [{"id": "t1", "type": "tuya", "model": "Tuya light", "ip": "127.0.0.41",
                        "device_id": "abcdef0123456789abcd", "local_key": "0123456789abcdef"},
                       {"id": "j1", "type": "jellyfish", "model": "JellyFish", "ip": "127.0.0.31", "zone": "Front"},
                       {"id": "j2", "type": "jellyfish", "model": "JellyFish", "ip": "127.0.0.31", "zone": "Back"},
                       {"id": "w1", "type": "wled", "model": "WLED", "ip": "127.0.0.21"}],
       "runs": [{"name": "Porch", "controller": "t1", "lights": 60}, {"name": "Front", "controller": "j1", "lights": 120},
                {"name": "Back", "controller": "j2", "lights": 45}, {"name": "Garage", "controller": "w1", "lights": 60}]}
def private(p):
    """Only this user can open the file: mode 600, or on Windows one access entry (this user's),
    nothing inherited from the folder."""
    if os.name != "nt":
        return os.stat(p).st_mode & 0o777 == 0o600
    acl = subprocess.run(["icacls", p], capture_output=True, text=True).stdout
    return acl.count(":(") == 1 and "(I)" not in acl and os.environ.get("USERNAME", "?").lower() in acl.lower()


settings.save(cfg)
raw = open(settings.path("config.json")).read()
check("local key kept out of config.json, secrets.json is private",
      "0123456789abcdef" not in raw and private(settings.path("secrets.json")))
s = settings.load()
check("loaded with options and secret", s.controllers["t1"].secret == {"local_key": "0123456789abcdef"}
      and s.controllers["j2"].options == {"zone": "Back"} and s.sections["garage"].lights_per_segment == 1)
cfg2 = dict(cfg)
cfg2["controllers"] = [dict(c) for c in cfg["controllers"]]
cfg2["controllers"][0].pop("local_key")
settings.save(cfg2)
check("saving again without retyping the key keeps it", settings.load().controllers["t1"].secret.get("local_key")
      == "0123456789abcdef" and private(settings.path("secrets.json")))
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
      and "seg4" in setup.allowed_tests(drivers.caps("govee"))
      and "markers" not in setup.allowed_tests(drivers.caps("govee")))
check("kelvin to RGB looks warm", net.kelvin_to_rgb(2200)[0] == 255 and net.kelvin_to_rgb(2200)[2] < 120)

print(f"\n{'ALL OK' if not FAILS else f'{len(FAILS)} FAILED'}")
sys.exit(1 if FAILS else 0)
