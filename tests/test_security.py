"""Web security basics: which Host names and Origins are answered, security headers, home-network
addresses only, and that the page never puts theme or run names into its HTML unescaped.
No lights needed; a small server runs on this computer for a moment.

    python tests/test_security.py
"""
import http.client
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="hl-security-")
os.environ["HOUSELIGHTS_HOME"] = HOME             # before anything reads the settings
os.environ["HOUSELIGHTS_DRY"] = "1"
os.environ.pop("HOUSELIGHTS_ALLOWED_HOSTS", None)
sys.path.insert(0, ROOT)
from houselights import guard, settings  # noqa: E402
from houselights.drivers import govee, net  # noqa: E402


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        check.failed = True


check.failed = False


def raises(fn, text=""):
    try:
        fn()
    except ValueError as e:
        return text.lower() in str(e).lower()
    return False


# --- Host names ---------------------------------------------------------------------------------------
ok_hosts = ["192.168.2.9:8090", "10.0.0.5", "127.0.0.1:8090", "localhost:8090", "[::1]:8090", "raspberrypi:8090",
            "pi.local", "Pi.Local:8090", "lights.lan", "nas.home.arpa", "house.internal"]
bad_hosts = ["", "evil.example", "evil.example:8090", "192.168.2.9.evil.example", "lights.mysite.net", "localhost.evil.com",
             "[::1", "a.b.c.d"]
check("Host: addresses, localhost, one-word and home names are answered",
      [h for h in ok_hosts if not guard.host_allowed(h)] == [])
check("Host: names from the public internet are not", [h for h in bad_hosts if guard.host_allowed(h)] == [])
check("Host: a name can be allowed by listing it", guard.host_allowed("lights.mysite.net", {"lights.mysite.net"})
      and not guard.host_allowed("other.mysite.net", {"lights.mysite.net"}))
os.environ["HOUSELIGHTS_ALLOWED_HOSTS"] = " Lights.MySite.net, ,x.example."
check("Host: HOUSELIGHTS_ALLOWED_HOSTS is read", guard.allowed_extra() == {"lights.mysite.net", "x.example"})
os.environ.pop("HOUSELIGHTS_ALLOWED_HOSTS")

# --- Origin and fetch site ------------------------------------------------------------------------------
check("Origin: none (a script) is fine", guard.origin_ok("", "192.168.2.9:8090"))
check("Origin: the dashboard itself is fine", guard.origin_ok("http://192.168.2.9:8090", "192.168.2.9:8090")
      and guard.origin_ok("http://Pi.local", "pi.local"))
check("Origin: another site, port or scheme is refused",
      not guard.origin_ok("http://evil.example", "192.168.2.9:8090")
      and not guard.origin_ok("http://192.168.2.9:9999", "192.168.2.9:8090")
      and not guard.origin_ok("null", "192.168.2.9:8090") and not guard.origin_ok("file:///x", "x")
      and not guard.origin_ok("http://192.168.2.9:8090.evil.example", "192.168.2.9:8090"))
check("Sec-Fetch-Site: only same-origin, none or absent",
      all(guard.fetch_site_ok(v) for v in ("", "same-origin", "none")) and not any(guard.fetch_site_ok(v) for v in ("cross-site", "same-site")))
check("Content type: a body must be JSON",
      guard.content_type_ok("POST", {"content-length": "0"}) and guard.content_type_ok("GET", {"content-type": "text/plain"})
      and guard.content_type_ok("POST", {"content-length": "5", "content-type": "application/json; charset=utf-8"})
      and not guard.content_type_ok("POST", {"content-length": "5", "content-type": "text/plain"})
      and not guard.content_type_ok("POST", {"content-length": "5"}))

# --- home addresses only -----------------------------------------------------------------------------------
home = ["192.168.1.5", "10.0.0.1", "172.16.0.1", "172.31.255.254", "127.0.0.1", "169.254.1.1", "192.0.2.7", "fe80::1", "fd00::5", "::1"]
away = ["8.8.8.8", "172.32.0.1", "11.0.0.1", "0.0.0.0", "255.255.255.255", "224.0.0.1", "2001:4860:4860::8888", "::ffff:8.8.8.8", "abc", ""]
check("addresses: home ones", [a for a in home if not net.is_home_address(a)] == [])
check("addresses: internet, multicast, broadcast and nonsense are not", [a for a in away if net.is_home_address(a)] == [])
check("scan targets: a home network is expanded", len(govee.expand_targets("192.168.2.0/24, 10.0.0.7")) == 255)
check("scan targets: internet addresses and networks are refused",
      raises(lambda: govee.expand_targets("8.8.8.8"), "own network") and raises(lambda: govee.expand_targets("8.8.8.0/24"), "own network")
      and raises(lambda: govee.expand_targets("192.168.2.5, 1.1.1.1"), "own network") and raises(lambda: govee.expand_targets("0.0.0.0/0"), "own network"))
check("scan targets: still too big", raises(lambda: govee.expand_targets("10.0.0.0/8"), "too big"))
cfg = {"controllers": [{"id": "x", "model": "H806A", "ip": "8.8.8.8"}], "runs": [{"name": "A", "controller": "x", "lights": 5}]}
check("settings: a controller on an internet address is refused", raises(lambda: settings.validate(cfg), "own network"))

# --- the page: names never become markup --------------------------------------------------------------------
static = os.path.join(ROOT, "houselights", "static")
bad = []
for name in os.listdir(static):
    if name.endswith(".js"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if "innerHTML" in line or "insertAdjacentHTML" in line:
                    for fn in ("labelOf(", "shortName(", "names(", ".name", ".label"):
                        for m in re.finditer(re.escape(fn), line):
                            if not line[:m.start()].rstrip().endswith("esc("):
                                bad.append(f"{name}:{n} {fn}")
check(f"page: names put into HTML are escaped {bad}", not bad)
inline = []
for name in os.listdir(static):
    if name.endswith(".html"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            inline += [name for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>", f.read())]
check(f"page: no inline scripts (the content security policy forbids them) {inline}", not inline)
check("page: theme-init.js exists for the early light/dark look", os.path.exists(os.path.join(static, "theme-init.js")))

# --- a real server ---------------------------------------------------------------------------------------------
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
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        h = {"Host": f"127.0.0.1:{port}"}
        h.update(headers or {})
        data = body.encode() if isinstance(body, str) else body
        if data is not None or method in ("POST", "PUT"):
            h["Content-Length"] = str(len(data or b""))
        for k, v in h.items():
            c.putheader(k, v)
        c.endheaders(data)
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")
    finally:
        c.close()


try:
    st, hd, body = req("GET", "/api/config")
    check("server: the page's own requests work", st == 200 and "configured" in body)
    check("server: security headers on every answer",
          all(hd.get(k.lower()) for k in guard.HEADERS) and "script-src 'self'" in hd["content-security-policy"]
          and hd["x-frame-options"] == "DENY" and hd["x-content-type-options"] == "nosniff"
          and "frame-ancestors 'none'" in hd["content-security-policy"])
    st, hd, body = req("GET", "/")
    check("server: the page has the headers too", st == 200 and "content-security-policy" in hd)
    st, hd, body = req("GET", "/api/config", {"Host": "evil.example"})
    check("server: a public name is refused (DNS rebinding)", st == 403 and "HOUSELIGHTS_ALLOWED_HOSTS" in body
          and "content-security-policy" in hd)
    check("server: home names are answered", all(req("GET", "/api/config", {"Host": h})[0] == 200
                                                 for h in (f"localhost:{port}", "pi.local", "192.168.2.9:8090")))
    own = f"http://127.0.0.1:{port}"
    check("server: a change from another site is refused", req("POST", "/api/stop-all", {"Origin": "http://evil.example"})[0] == 403)
    check("server: ... even with a JSON body", req("POST", "/api/themes/prefs", {"Origin": "http://evil.example", "Content-Type": "application/json"}, "{}")[0] == 403)
    check("server: a change the browser calls cross-site is refused", req("POST", "/api/stop-all", {"Sec-Fetch-Site": "cross-site"})[0] == 403)
    check("server: a change from the dashboard's own page works",
          req("POST", "/api/stop-all", {"Origin": own, "Sec-Fetch-Site": "same-origin"})[0] == 200)
    check("server: a script with no Origin works", req("POST", "/api/stop-all")[0] == 200)
    check("server: a body that is not JSON is refused", req("POST", "/api/themes/prefs", {"Content-Type": "text/plain"}, "{}")[0] == 415)
    check("server: JSON works", req("POST", "/api/themes/prefs", {"Content-Type": "application/json", "Origin": own}, "{}")[0] == 200)
    check("server: reading from another site is not blocked here (the browser does that)",
          req("GET", "/api/config", {"Origin": "http://evil.example"})[0] == 200)
finally:
    server.should_exit = True
    thread.join(15)
    shutil.rmtree(HOME, ignore_errors=True)

sys.exit(1 if check.failed else 0)
