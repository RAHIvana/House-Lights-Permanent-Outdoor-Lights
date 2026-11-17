"""The optional dashboard password: how it is stored, who gets in, wrong guesses, change, remove, and that
a damaged password file never means "no password". A small server runs on this computer for a moment.

    python tests/test_auth.py
"""
import getpass
import http.client
import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="hl-auth-")
os.environ["HOUSELIGHTS_HOME"] = HOME             # before anything reads the settings
os.environ["HOUSELIGHTS_DRY"] = "1"
os.environ.pop("HOUSELIGHTS_ALLOWED_HOSTS", None)
sys.path.insert(0, ROOT)
from houselights import auth, settings  # noqa: E402

auth.ITERATIONS = 2000                            # login uses 600,000; the tests make dozens of hashes


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        check.failed = True


check.failed = False
PATH = settings.path(auth.FILE)
PW, PW2 = "correct horse battery", "another long phrase"

# --- the stored password ---------------------------------------------------------------------------------
check("no file: no password", auth.read() is None and not auth.enabled())
a = auth.make(PW)
check("password: the right one verifies, wrong ones don't",
      auth.verify(PW, a) and not auth.verify(PW[:-1], a) and not auth.verify("", a)
      and not auth.verify(None, a) and not auth.verify(12345678, a) and not auth.verify(PW, None))
b = auth.make(PW)
check("password: each hash has its own salt and its own cookie key",
      len({a["salt"], b["salt"]}) == 2 and a["hash"] != b["hash"] and a["key"] != b["key"])
check("password: nothing stored is the password", PW not in json.dumps(a))
check("password: the number of PBKDF2 rounds is kept with the hash", a["iterations"] == 2000)
check("password: a huge guess is refused without hashing it", not auth.verify("x" * 5000, a))
check("password: 8 to 200 characters",
      [bool(auth.check_new(x)) for x in ("1234567", "12345678", "x" * 200, "x" * 201, "", None, 12345678)]
      == [True, False, False, True, True, True, True])

# --- the login cookie ------------------------------------------------------------------------------------
now = 1_000_000.0
c = auth.new_cookie(a, now)
exp, _, sig = c.partition(".")
flip = lambda s: s[:-1] + ("0" if s[-1] != "0" else "1")  # noqa: E731
check("cookie: good for 30 days", auth.cookie_ok(c, a, now + 1) and auth.cookie_ok(c, a, now + 29 * 86400)
      and not auth.cookie_ok(c, a, now + 31 * 86400))
check("cookie: a changed signature, a later expiry, another key or rubbish is refused",
      not auth.cookie_ok(f"{exp}.{flip(sig)}", a, now + 1)
      and not auth.cookie_ok(f"{int(exp) + 86400}.{sig}", a, now + 1)
      and not auth.cookie_ok(auth.new_cookie(b, now), a, now + 1)
      and not any(auth.cookie_ok(x, a, now + 1) for x in ("", "x", "1.2.3", ".", "abc.def", None)))
check("cookie: nothing works against a damaged password file", not auth.cookie_ok(c, auth.BROKEN, now + 1))

# --- wrong guesses ---------------------------------------------------------------------------------------
t = [100.0]
th = auth.Throttle(clock=lambda: t[0])
for _ in range(4):
    th.fail("1.1.1.1")
check("throttle: four wrong tries cost nothing", th.wait("1.1.1.1") == 0)
th.fail("1.1.1.1")
check("throttle: the fifth starts a 30 second wait", th.wait("1.1.1.1") == 30)
check("throttle: another address isn't held up", th.wait("2.2.2.2") == 0)
t[0] += 31
check("throttle: the wait ends", th.wait("1.1.1.1") == 0)
waits = []
for _ in range(7):
    th.fail("1.1.1.1")
    waits.append(th.wait("1.1.1.1"))
    t[0] += waits[-1] + 1
check("throttle: it doubles, then stops at 15 minutes", waits == [60, 120, 240, 480, 900, 900, 900])
th.ok("1.1.1.1")
for _ in range(4):
    th.fail("1.1.1.1")
check("throttle: a right password starts the count again", th.wait("1.1.1.1") == 0)
th.fail("9.9.9.9")
t[0] += 4000
th.fail("3.3.3.3")
check("throttle: addresses not seen for an hour are forgotten", "9.9.9.9" not in th.who)
small = auth.Throttle()
small.MAX = 3
for i in range(8):
    small.fail(f"10.0.0.{i}")
check("throttle: the list of addresses stays small", len(small.who) <= 3)

# --- the command line ------------------------------------------------------------------------------------
answers = iter(["short", "long enough one", "long enough two", "long enough one", "long enough one"])
getpass.getpass = lambda prompt="": next(answers)
check("--set-password: too short is refused", auth.cli(True) == 1 and not os.path.exists(PATH))
check("--set-password: two different answers are refused", auth.cli(True) == 1 and not os.path.exists(PATH))
check("--set-password: sets it", auth.cli(True) == 0 and auth.verify("long enough one", auth.read()))
check("--remove-password: takes it away", auth.cli(False) == 0 and auth.read() is None)
check("--remove-password: with none set is fine", auth.cli(False) == 0)

# --- a damaged file is never "no password" ----------------------------------------------------------------
broken = ["not json", "[]", "{}", json.dumps(dict(a, iterations=0)), json.dumps(dict(a, iterations="x")),
          json.dumps(dict(a, salt="zz")), json.dumps({k: v for k, v in a.items() if k != "key"}),
          json.dumps(dict(a, iterations=10 ** 9))]
bad = []
for text in broken:
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(text)
    if auth.read() is not auth.BROKEN or not auth.enabled():
        bad.append(text[:30])
check(f"file: damaged or odd contents count as a password nobody knows {bad}", not bad)
auth.remove()

# --- a real server -----------------------------------------------------------------------------------------
import uvicorn  # noqa: E402

from houselights import app as web  # noqa: E402

s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
server = uvicorn.Server(uvicorn.Config(web.app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.1)
check("test server started", server.started)


def req(method, path, headers=None, body=None):
    cn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        cn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        h = {"Host": f"127.0.0.1:{port}"}
        h.update(headers or {})
        data = body.encode() if isinstance(body, str) else body
        if data is not None or method in ("POST", "PUT"):
            h["Content-Length"] = str(len(data or b""))
        for k, v in h.items():
            cn.putheader(k, v)
        cn.endheaders(data)
        r = cn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")
    finally:
        cn.close()


J = {"Content-Type": "application/json"}
PAGE = {"Accept": "text/html"}


def post(path, obj, cookie=None, extra=None):
    h = dict(J, **(extra or {}))
    if cookie:
        h["Cookie"] = cookie
    return req("POST", path, h, json.dumps(obj))


def get(path, cookie=None, extra=None):
    h = dict(extra or {})
    if cookie:
        h["Cookie"] = cookie
    return req("GET", path, h)


def jar(hd):
    return hd["set-cookie"].split(";")[0]


try:
    # no password: nothing changes for anyone
    st, hd, body = get("/api/config")
    check("no password: the dashboard opens and says so", st == 200 and json.loads(body)["password"] is False)
    check("no password: the wizard's state says so too", json.loads(get("/api/setup")[2])["password"] is False)
    st, hd, _ = get("/login", extra=PAGE)
    check("no password: /login goes to the dashboard", st == 303 and hd["location"] == "/")
    st, hd, _ = post("/api/login", {"password": "anything"})
    check("no password: logging in is a no-op that sets no cookie", st == 200 and "set-cookie" not in hd)

    # setting one
    check("set: too short is refused", (lambda r: r[0] == 400 and "at least 8" in r[2])(post("/api/password", {"new": "short"})))
    check("set: too long is refused", post("/api/password", {"new": "x" * 201})[0] == 400)
    check("set: nothing, or not text, is refused", post("/api/password", {})[0] == 400 and post("/api/password", {"new": 12345678})[0] == 400)
    check("set: nothing was stored by the refusals", auth.read() is None)
    st, hd, body = post("/api/password", {"new": PW})
    sc = hd.get("set-cookie", "")
    check("set: the first password needs no login and logs this browser in", st == 200 and sc.startswith(auth.COOKIE + "="))
    check("set: the cookie is HttpOnly, SameSite=Lax, for 30 days, whole site, and not Secure on plain http",
          "httponly" in sc.lower() and "samesite=lax" in sc.lower() and "max-age=2592000" in sc.lower()
          and "path=/" in sc.lower() and "secure" not in sc.lower())
    with open(PATH, encoding="utf-8") as f:
        text = f.read()
    check("set: the file holds a hash, never the password", PW not in text and json.loads(text)["iterations"] == 2000)
    check("set: only this user can read the file (checked on Linux and Mac; Windows sets its own access list)",
          os.name == "nt" or stat.S_IMODE(os.stat(PATH).st_mode) == 0o600)
    cookie = jar(hd)

    # with a password on
    st, hd, _ = get("/", extra=PAGE)
    check("on: a page without login goes to the login page, and comes back after",
          st == 303 and hd["location"] == "/login?next=/")
    st, hd, _ = get("/setup.html?step=save", extra=PAGE)
    check("on: ... keeping where it was going", st == 303 and hd["location"] == "/login?next=/setup.html?step=save")
    for path in ("/api/config", "/api/status", "/api/setup", "/api/schedules", "/api/themes"):
        st, hd, body = get(path)
        check(f"on: {path} without login is refused", st == 401 and json.loads(body).get("login") is True)
    check("on: a change without login is refused, and nothing happens", post("/api/stop-all", {})[0] == 401)
    check("on: the page's own scripts need a login too", get("/app.js")[0] == 401 and get("/setup.js")[0] == 401)
    pub = [p for p in ("/login", "/login.js", "/login.css", "/style.css", "/theme-init.js", "/icon.svg",
                       "/icon-192.png", "/icon-512.png", "/manifest.webmanifest") if get(p)[0] != 200]
    check(f"on: the login page and what it needs are open {pub}", not pub)
    st, hd, body = get("/login", extra=PAGE)
    check("on: the login page has the security headers too", "content-security-policy" in hd and "Log in" in body)
    check("on: nothing else slips through odd spellings",
          all(get(p)[0] in (401, 404) for p in ("//api/config", "/api/config/", "/LOGIN.JS", "/login.js/../app.js", "/%2e%2e/app.js")))

    # logging in
    wrong = [post("/api/login", x)[0] for x in ({"password": PW + "x"}, {"password": ""}, {"password": 123},
                                                 {"password": ["a"]}, {})]
    check("login: wrong, empty, not text and missing passwords are refused", wrong == [401] * 5)
    auth.THROTTLE = auth.Throttle()                  # those five used up the free tries
    st, _, body = post("/api/login", {"password": PW + "x"})
    check("login: ... and the answer says so", st == 401 and "not right" in body)
    auth.THROTTLE = auth.Throttle()
    st, hd, _ = post("/api/login", {"password": PW})
    check("login: the right password gives a cookie", st == 200 and hd["set-cookie"].startswith(auth.COOKIE + "="))
    cookie = jar(hd)
    st, hd, body = get("/api/config", cookie)
    check("login: with the cookie the dashboard opens and says a password is on", st == 200 and json.loads(body)["password"] is True)
    check("login: ... and the wizard's state does too, without any hash, salt or key in it",
          (lambda r: r[0] == 200 and json.loads(r[2])["password"] is True
           and not any(x in r[2] for x in (auth.read()["hash"], auth.read()["salt"], auth.read()["key"])))(get("/api/setup", cookie)))
    check("login: pages open with the cookie", get("/", cookie, PAGE)[0] == 200 and get("/app.js", cookie)[0] == 200)
    mine = auth.read()
    fakes = {"a changed signature": cookie[:-1] + ("0" if cookie[-1] != "0" else "1"), "rubbish": f"{auth.COOKIE}=nonsense",
             "an old one": f"{auth.COOKIE}=" + auth.new_cookie(mine, time.time() - 40 * 86400),
             "another key": f"{auth.COOKIE}=" + auth.new_cookie(auth.make("other password"))}
    bad = [k for k, v in fakes.items() if get("/api/config", v)[0] != 401]
    check(f"login: a made-up, old or changed cookie is refused {bad}", not bad)
    check("login: the Host and Origin checks still come first, with a good cookie",
          get("/api/config", cookie, {"Host": "evil.example"})[0] == 403
          and post("/api/stop-all", {}, cookie, {"Origin": "http://evil.example"})[0] == 403)
    check("login: a login from another site is refused too", post("/api/login", {"password": PW}, None, {"Origin": "http://evil.example"})[0] == 403)

    # wrong guesses at the door
    auth.THROTTLE = auth.Throttle()
    first = [post("/api/login", {"password": "nope nope nope"})[0] for _ in range(5)]
    st, hd, body = post("/api/login", {"password": PW})
    check("lockout: five wrong guesses, then even the right password waits",
          first == [401] * 5 and st == 429 and int(hd["retry-after"]) > 0 and "Wait" in body)
    check("lockout: changing the password can't be guessed at either",
          post("/api/password", {"current": "wrong wrong", "new": PW2}, cookie)[0] == 429)
    auth.THROTTLE = auth.Throttle()

    # changing it
    st, _, body = post("/api/password", {"new": PW2}, cookie)
    check("change: it needs the current password", st == 401 and "current" in body and auth.verify(PW, auth.read()))
    check("change: a wrong current password is refused", post("/api/password", {"current": "wrong wrong", "new": PW2}, cookie)[0] == 401)
    check("change: a too-short new one is refused", post("/api/password", {"current": PW, "new": "short"}, cookie)[0] == 400)
    auth.THROTTLE = auth.Throttle()
    st, hd, _ = post("/api/password", {"current": PW, "new": PW2}, cookie)
    new_cookie = jar(hd)
    check("change: with the current password it works and keeps this browser logged in",
          st == 200 and new_cookie != cookie and get("/api/config", new_cookie)[0] == 200)
    check("change: every other browser is logged out", get("/api/config", cookie)[0] == 401)
    check("change: the old password no longer works, the new one does",
          post("/api/login", {"password": PW})[0] == 401 and post("/api/login", {"password": PW2})[0] == 200)
    auth.THROTTLE = auth.Throttle()
    cookie = new_cookie

    # logging out
    st, hd, _ = post("/api/logout", {}, cookie)
    check("logout: the cookie is cleared", st == 200 and "max-age=0" in hd["set-cookie"].lower())

    # taking it off
    check("remove: it needs the current password", post("/api/password/remove", {}, cookie)[0] == 401
          and post("/api/password/remove", {"current": "wrong wrong"}, cookie)[0] == 401 and auth.enabled())
    auth.THROTTLE = auth.Throttle()
    st, hd, _ = post("/api/password/remove", {"current": PW2}, cookie)
    check("remove: with it the password is gone and the cookie is cleared",
          st == 200 and not auth.enabled() and not os.path.exists(PATH) and "max-age=0" in hd["set-cookie"].lower())
    st, _, body = get("/api/config")
    check("remove: the dashboard opens for everyone again", st == 200 and json.loads(body)["password"] is False)
    check("remove: with none set it is a no-op", post("/api/password/remove", {})[0] == 200)

    # a damaged file locks the door, never opens it
    post("/api/password", {"new": PW})
    cookie = None
    with open(PATH, "w", encoding="utf-8") as f:
        f.write("this is not json")
    st, _, body = get("/api/config")
    check("damaged: the dashboard stays closed", st == 401)
    st, _, body = post("/api/login", {"password": PW})
    check("damaged: login says what is wrong and how to fix it", st == 401 and "--remove-password" in body)
    check("damaged: a cookie from before doesn't open it", get("/api/config", f"{auth.COOKIE}=" + auth.new_cookie(a))[0] == 401)
    check("damaged: --remove-password opens it again", auth.cli(False) == 0 and get("/api/config")[0] == 200)

    # the setup the wizard saves doesn't touch the password
    st, hd, _ = post("/api/password", {"new": PW})
    with open(PATH, "rb") as f:
        before = f.read()
    settings.save({"controllers": [{"id": "front", "type": "govee", "model": "H806A", "ip": "192.168.2.20", "name": "Front"}],
                   "runs": [{"name": "Front", "controller": "front", "lights": 50}]})
    with open(PATH, "rb") as f:
        after = f.read()
    check("wizard: saving the setup leaves the password alone", before == after and auth.enabled())
    check("wizard: and the saved setup holds no password", "hash" not in open(settings.path("config.json"), encoding="utf-8").read())
finally:
    server.should_exit = True
    thread.join(15)
    shutil.rmtree(HOME, ignore_errors=True)

# --- the pages -----------------------------------------------------------------------------------------------
static = os.path.join(ROOT, "houselights", "static")


def page(name):
    with open(os.path.join(static, name), encoding="utf-8") as f:
        return f.read()


check("pages: the dashboard and the wizard have a Log out button", 'id="logout"' in page("index.html") and 'id="logout"' in page("setup.html"))
check("pages: the wizard's last step has the password block", 'id="pw-body"' in page("setup.html"))
check("pages: the login page has a password box and no inline script",
      'type="password"' in page("login.html") and 'autocomplete="current-password"' in page("login.html")
      and "<script>" not in page("login.html"))
check("pages: the scripts send a logged-out visitor to the login page",
      "/login?next=" in page("app.js") and "/login?next=" in page("setup.js"))
check("pages: the login page only goes back to a path on this site", "(?![\\/\\\\])" in page("login.js"))

sys.exit(1 if check.failed else 0)
