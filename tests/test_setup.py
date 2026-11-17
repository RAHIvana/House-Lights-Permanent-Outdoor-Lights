"""Setup wizard API helpers: the "check" test, ZIP lookup (mocked: no internet) and sun times.

    python tests/test_setup.py
"""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOUSELIGHTS_HOME"] = tempfile.mkdtemp()

from fastapi import HTTPException  # noqa: E402

from houselights import setup  # noqa: E402

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def fails(name, fn, status, words):
    try:
        fn()
    except HTTPException as e:
        check(f"{name}: {e.status_code} {e.detail}", e.status_code == status and words.lower() in e.detail.lower())
        return
    check(name, False)


# --- "check" test: red light 1, blue last light, orange past the end ---
f = setup._check(70, 0, 50)
check("check: red first, blue at the count, dim between", f[0] == setup.RED and f[49] == setup.BLUE
      and f[1] == f[48] == setup.DIM_WHITE)
check("check: 20 orange after the count", f[50:] == [setup.ORANGE] * 20)
check("check frame: count + 20, capped at the model's max",
      setup._frame("check", 50, 255) == 70 and setup._frame("check", 250, 255) == 255
      and setup._frame("markers", 50, 255) == 255 and setup._frame("ruler", 50, 255) == 50)
check("check with 1 light", setup._check(21, 0, 1)[0] == setup.RED and setup._check(21, 0, 1)[1] == setup.ORANGE)
pv = setup.preview(({"test": "check", "lights": 73, "controller": {"type": "govee", "model": "H806A"}, "reverse": True}))
check("check preview: 93 dots, not reversed", len(pv["frames"][0]) == 93 and pv["frames"][0][0] == "#ff0000"
      and pv["frames"][0][72] == "#0000ff")
check("check is offered to Govee and WLED only", "check" in setup.allowed_tests({"stream": True})
      and "check" not in setup.allowed_tests({"static": "palette"}))


# --- ZIP lookup ---
ANSWER = {"post code": "12345", "country": "United States", "country abbreviation": "US",
          "places": [{"place name": "Springfield", "longitude": "-89.65012", "state": "Illinois",
                      "state abbreviation": "IL", "latitude": "39.78172"}]}
seen = []


def fake(body=None, error=None):
    def fetch(url):
        seen.append(url)
        if error:
            raise error
        return json.dumps(body, ensure_ascii=False).encode("utf-8")
    return fetch


r = setup.zip_lookup("12345", "US", fetch=fake(ANSWER))
check("zip: lat, lon, place", r == {"lat": 39.7817, "lon": -89.6501, "place": "Springfield, IL", "zip": "12345"})
check("zip: url", seen[-1] == "https://api.zippopotam.us/us/12345")
uni = dict(ANSWER, places=[dict(ANSWER["places"][0], **{"place name": "Saint-Étienne", "state abbreviation": ""})])
check("zip: UTF-8 place names", setup.zip_lookup("42000", "fr", fetch=fake(uni))["place"] == "Saint-Étienne, Illinois")
not_found = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b"{}"))
fails("zip not found", lambda: setup.zip_lookup("00000", fetch=fake(error=not_found)), 400, "ZIP code not found")
fails("zip: empty answer", lambda: setup.zip_lookup("00000", fetch=fake({})), 400, "not found")
fails("zip: no network", lambda: setup.zip_lookup("12345", fetch=fake(error=urllib.error.URLError("down"))),
      502, "enter latitude and longitude")
fails("zip: timeout", lambda: setup.zip_lookup("12345", fetch=fake(error=TimeoutError())), 502, "couldn't reach")
fails("zip: server error", lambda: setup.zip_lookup("12345", fetch=fake(
    error=urllib.error.HTTPError("u", 500, "x", {}, io.BytesIO(b"")))), 502, "couldn't reach")
fails("zip: bad code", lambda: setup.zip_lookup("12/45", fetch=fake(ANSWER)), 400, "ZIP code")
fails("zip: bad country", lambda: setup.zip_lookup("12345", "usa", fetch=fake(ANSWER)), 400, "country")
setup._fetch, real = fake(ANSWER), setup._fetch          # the endpoint, still without the internet
try:
    check("GET /api/setup/zip", setup.zip_code(code="12345", country="us")["place"] == "Springfield, IL")
finally:
    setup._fetch = real

# --- sun times and the time zone check ---
day = dt.date(2026, 12, 1)
s = setup.sun_today(39.78, -89.65, "America/Chicago", day)
check(f"sun: Springfield in Chicago time {s}", s["tz_ok"] and "06:30" < s["sunrise"] < "07:30" and "16:00" < s["sunset"] < "17:00")
w = setup.sun_today(39.78, -89.65, "Asia/Tokyo", day)
check(f"sun: wrong time zone is flagged {w}", not w["tz_ok"])
p = setup.sun_today(78.2, 15.6, "Arctic/Longyearbyen", day)
check(f"sun: polar night has no sunrise {p}", p["sunrise"] is None and p["sunset"] is None)
fails("sun: bad time zone", lambda: setup.sun_today(1, 2, "Mars/Olympus"), 400, "time zone")

# --- tests switch a controller on first, and back off afterwards if it was off ---
class FakeC:
    id, tag = "c1", "fake"


class FakeKit:
    live, caps, c, tag = True, {"stream": True, "status": True}, FakeC(), "fake"

    def __init__(self):
        self.calls = []

    def power(self, on):
        self.calls.append(on)


class FakeDrv:
    def __init__(self, status):
        self.status, self.asked = status, 0

    def read_status(self, kits):
        self.asked += 1
        return {"c1": self.status}


setup.SWITCHED.clear()
kit, drv = FakeKit(), FakeDrv({"onOff": 0})
setup.switch_on(drv, kit, ("192.168.2.50", ""))
setup.switch_on(drv, kit, ("192.168.2.50", ""))                # the next test on the same controller
check("switch on: asked once, switched on each test", drv.asked == 1 and kit.calls == [True, True])
setup.switch_off_tested({("192.168.2.51", "")})
check("switch off: other controllers untouched", kit.calls == [True, True])
setup.switch_off_tested({("192.168.2.50", "")})
check("switch off: was off, so off again", kit.calls == [True, True, False] and not setup.SWITCHED)
kit, drv = FakeKit(), FakeDrv({"onOff": 1})
setup.switch_on(drv, kit, ("192.168.2.50", ""))
setup.switch_off_tested()
check("was on: stays on", kit.calls == [True])
kit, drv = FakeKit(), FakeDrv(None)
setup.switch_on(drv, kit, ("192.168.2.50", ""))
setup.switch_off_tested()
check("no answer: switched on, left on", kit.calls == [True])
kit = FakeKit()
kit.live = False
drv = FakeDrv({"onOff": 0})
setup.switch_on(drv, kit, ("192.168.2.50", ""))
setup.switch_off_tested()
check("practice mode: doesn't ask", drv.asked == 0 and kit.calls == [True])

# --- add by address: every kind is asked, whatever answers is added ---
def answers(kind, rows=None, error=None):
    def fn(ip):
        if error:
            raise error
        return [dict(r, ip=ip) for r in rows or []]
    return fn


NONE = {k: answers(k) for k in ("govee", "wled", "jellyfish", "tuya")}
r = setup.identify("192.168.2.50", dict(NONE, wled=answers("wled", [{"type": "wled", "model": "WLED", "label": "WLED 0.15"}])))
check(f"identify: WLED ({r['message']})", r["kinds"] == ["wled"] and r["devices"][0]["ip"] == "192.168.2.50"
      and r["message"] == "192.168.2.50 is a WLED controller.")
r = setup.identify(" 192.168.2.51 ", dict(NONE, govee=answers("govee", [{"type": "govee", "model": "H806A", "label": "Lights (H806A)"}]),
                                         wled=answers("wled", error=OSError("refused"))))
check(f"identify: Govee, a failing check is just 'not that kind' ({r['message']})",
      r["kinds"] == ["govee"] and "is a Govee controller (Lights (H806A))" in r["message"])
r = setup.identify("192.168.2.52", dict(NONE, jellyfish=answers("jellyfish", [{"type": "jellyfish", "zone": "Front"},
                                                                              {"type": "jellyfish", "zone": "Back"}])))
check(f"identify: JellyFish zones ({r['message']})", len(r["devices"]) == 2 and "with 2 zones" in r["message"])
r = setup.identify("192.168.2.53", NONE)
check(f"identify: nothing answered ({r['message'][:40]}...)", r["devices"] == [] and r["message"].startswith("Nothing answered at 192.168.2.53"))
asked = []
setup.identify("192.168.2.54", {k: (lambda ip, k=k: asked.append((k, ip)) or []) for k in NONE})
check("identify: all four kinds asked, at that address", sorted(asked) == sorted((k, "192.168.2.54") for k in NONE))
import time  # noqa: E402
t0 = time.time()
r = setup.identify("192.168.2.55", dict(NONE, wled=answers("wled", [{"type": "wled", "model": "WLED"}]),
                                        govee=lambda ip: time.sleep(4) or []))
check(f"identify: once one kind answers, a slow check isn't waited for ({time.time() - t0:.1f} s)",
      r["kinds"] == ["wled"] and time.time() - t0 < setup.IDENTIFY_GRACE + 1.5)
fails("identify: a range is not one address", lambda: setup.identify("192.168.2.0/30", NONE), 400, "one address")
fails("identify: not an address", lambda: setup.identify("lights", NONE), 400, "one address")
fails("identify: empty", lambda: setup.identify("", NONE), 400, "one address")

# --- Tuya / Smart Life presence without tinytuya ---
import socket  # noqa: E402
import threading  # noqa: E402


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


port = free_udp_port()
announce = b"\x00\x00\x55\xaa" + b"\x00" * 16 + json.dumps({"ip": "127.0.0.1", "gwId": "bf00fake00device00ab",
                                                            "version": "3.3"}).encode() + b"\x00" * 8


def send_later(payloads):
    import time
    time.sleep(0.3)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for p in payloads:
        tx.sendto(p, ("127.0.0.1", port))
    tx.close()


threading.Thread(target=send_later, args=([b"not tuya", announce],), daemon=True).start()
heard = setup.tuya_listen(3.0, ports=(port,), bind="127.0.0.1", expect=1)
check(f"tuya listen: a broadcast is heard, other packets ignored {heard}",
      list(heard) == ["127.0.0.1"] and heard["127.0.0.1"].get("gwId") == "bf00fake00device00ab")
check("tuya listen: an encrypted announcement has no readable details",setup._tuya_announce(b"\x00\x00\x55\xaa\x93\x11garbage") == {})
blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
blocker.bind(("127.0.0.1", 0))
try:
    if os.name == "nt":
        setup.tuya_listen(0.1, ports=(blocker.getsockname()[1],), bind="127.0.0.1")
        check("tuya listen: port in use is reported", False)
    else:
        check("tuya listen: port in use (skipped off Windows: ports are shared)", True)
except OSError as e:
    check(f"tuya listen: port in use is reported ({e})", "can't listen for Tuya" in str(e))
blocker.close()

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.bind(("127.0.0.1", 0))
srv.listen(4)
tcp = srv.getsockname()[1]
check("tuya connect: the command port answers", setup.tuya_connect(["127.0.0.1"], port=tcp) == {"127.0.0.1"})
srv.close()
check("tuya connect: nothing there", setup.tuya_connect(["127.0.0.1"], port=tcp, timeout=0.3) == set())

rows, prob = setup.tuya_scan("", usable=False, same_section=lambda t: True,
                             listen=lambda s, expect=0: {"192.168.2.60": {"gwId": "bf1234567890abcdef12"}},
                             connect=lambda ips: set())
check(f"tuya scan without tinytuya: found, not usable, says why {rows}", len(rows) == 1 and not rows[0]["supported"]
      and rows[0]["reason"] == setup.TUYA_NOT_INSTALLED and "install tinytuya" in rows[0]["install"]
      and rows[0]["device_id"] == "bf1234567890abcdef12" and not prob)
listened = []
rows, prob = setup.tuya_scan("192.168.5.7, 192.168.5.8", usable=False, same_section=lambda t: False,
                             listen=lambda s, expect=0: listened.append(s) or {},
                             connect=lambda ips: {ip for ip in ips if ip.endswith(".8")})
check(f"tuya scan, other network section: no listening, typed addresses tried {rows}",
      not listened and [r["ip"] for r in rows] == ["192.168.5.8"] and rows[0]["probable"] and rows[0]["label"].endswith("(probably)"))
rows, prob = setup.tuya_scan("192.168.2.60, 192.168.2.61", usable=False, same_section=lambda t: True, deep=True,
                             known=["192.168.2.61"],
                             listen=lambda s, expect=0: listened.append(s) or {"192.168.2.60": {}},
                             connect=lambda ips: listened.append(sorted(ips)) or set(ips))
check(f"tuya deep scan: listens longer, doesn't ask again what it heard or knows {listened}",
      listened == [setup.TUYA_LISTEN[1], []] and [r["ip"] for r in rows] == ["192.168.2.60"])
rows, prob = setup.tuya_scan("", usable=False, same_section=lambda t: True, connect=lambda ips: set(),
                             listen=lambda s, expect=0: (_ for _ in ()).throw(OSError("can't listen for Tuya devices on UDP port 6666")))
check(f"tuya scan: a port problem is reported, not raised ({prob})", rows == [] and "6666" in prob)
rows, prob = setup.tuya_scan("192.168.5.9", usable=True, same_section=lambda t: False, connect=lambda ips: set(ips))
check("tuya scan with tinytuya: a typed address is usable once the id and key are typed",
      rows[0]["supported"] and rows[0]["needs_key"] and rows[0]["device_id"] == "")

# --- Blink: 1 s on, 1 s off ---
check("blink: on for the first 2 s", setup._identify(3, 0.5) == setup._identify(3, 1.9) == [setup.WHITE] * 3)
check("blink: off for the next 2 s", setup._identify(3, 2.1) == setup._identify(3, 3.9) == [setup.OFF] * 3)
check("blink: on again after 4 s", setup._identify(3, 4.2) == [setup.WHITE] * 3)

# --- Govee streams: "start" a few times at the beginning only (a mid-stream "start" flashes
# the lights), "stop" a few times at the end; a test starts once ---
import threading as _th  # noqa: E402
from types import SimpleNamespace as _NS  # noqa: E402

from houselights import stream as _stream  # noqa: E402
from houselights.drivers import govee as _govee  # noqa: E402


class _Rec:
    def __init__(self):
        self.sent = []

    def send(self, ip, cmd, data):
        self.sent.append(cmd + ":" + data.get("pt", ""))


gk = _govee.Kit(_NS(id="g1", ip="192.168.2.20", model="H806A", enabled=True, options={}), True)
gk.lan = _Rec()
s = _stream.Streamer(gk, 5, 20)
s.start_fn("t", lambda t: [(1, 1, 1)] * 5, True, 100, seconds=0.8)
s._thread.join(5)
import base64 as _b64  # noqa: E402
on = "razer:" + _b64.b64encode(_govee.RAZER_ON).decode()
off = "razer:" + _b64.b64encode(_govee.RAZER_OFF).decode()
sent = gk.lan.sent
n_on = sent.count(on)
check(f"govee stream: start sent {n_on}x, all before the first frame",
      n_on == 3 and sent[:3] == [on] * 3)
check("govee stream: stop sent 5x at the end", sent[-5:] == [off] * 5 and sent.count(off) == 5)
check("govee stream: frames in between", len(sent) - 8 >= 5)
check("test start is guarded by a lock", isinstance(setup.TEST_LOCK, type(_th.Lock())))

# --- Govee counting: segment colours, the last segment red, then light 1 blue / last red ---
from houselights import drivers as _drv  # noqa: E402

full = setup.allowed_tests(_drv.model_caps("govee", "H806A"))
check("Govee H806A counts with segment colours, not markers or orange",
      {"seg4", "seglast", "ends"} <= set(full) and not {"markers", "tail", "check"} & set(full))
check("WLED keeps markers / check, no Govee counting",
      "ends" not in setup.allowed_tests({"stream": True, "count": "manual", "pick": True})
      and "check" in setup.allowed_tests({"stream": True, "count": "manual", "pick": True}))
g, w, r_, y = setup.SEG_COLOURS
s4 = setup._seg4(23, 0, 5)
check("seg4: green, white, red, yellow per 5 lights, then again",
      s4[:5] == [g] * 5 and s4[5:10] == [w] * 5 and s4[10:15] == [r_] * 5 and s4[15:20] == [y] * 5 and s4[20:] == [g] * 3)
sl = setup._seglast(25, 0, 5, 4)
check("seglast: segments before the last white, the last red, past it blue",
      sl[:15] == [setup.WHITE] * 15 and sl[15:20] == [setup.RED] * 5 and sl[20:] == [setup.BLUE] * 5)
en = setup._ends(73, 0)
check("ends: light 1 blue, the last red, the rest white", en[0] == setup.BLUE and en[-1] == setup.RED
      and en[1:-1] == [setup.WHITE] * 71 and len(en) == 73)
check("segment counting: the last colour and its blocks give the segments",
      all(4 * (blocks - 1) + place == segs for segs, place, blocks in
          [(24, 4, 6), (10, 2, 3), (15, 3, 4), (1, 1, 1)]))


class SegKit:
    lock = _th.Lock()

    def __init__(self):
        self.sent = []

    def guard(self):
        pass

    def segments(self, segs, rgb, nseg):
        self.sent.append((tuple(segs), rgb, nseg))


sk = SegKit()
setup.SegmentTest(sk, 5, 255, "seg4").show()
cover = sorted(s for segs, _, _ in sk.sent[::2] for s in segs)
check(f"seg4 sets every segment the model can have, once per colour, each sent twice ({len(sk.sent)} sends)",
      cover == list(range(51)) and len(sk.sent) == 8 and sk.sent[0] == sk.sent[1] and sk.sent[0][2] == 51)
sk = setup.SegmentTest(SegKit(), 5, 255, "seglast", 24)
grp = dict((rgb, segs) for segs, rgb in sk.groups())
check("seglast: 23 white, segment 24 red, 25-51 blue", grp[setup.WHITE] == list(range(23))
      and grp[setup.RED] == [23] and grp[setup.BLUE] == list(range(24, 51)))

print(f"\n{'ALL OK' if not FAILS else f'{len(FAILS)} FAILED'}")
sys.exit(1 if FAILS else 0)
