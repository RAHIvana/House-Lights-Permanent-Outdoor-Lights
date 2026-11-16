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

print(f"\n{'ALL OK' if not FAILS else f'{len(FAILS)} FAILED'}")
sys.exit(1 if FAILS else 0)
