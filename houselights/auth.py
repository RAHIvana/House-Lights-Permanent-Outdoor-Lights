"""An optional password for the dashboard.

Off by default: with no password anyone on your home network who opens the page can control the
lights (README, "Security"). With one, every page and every request needs a login first.

- Where: access.json in the settings folder, readable only by you (like secrets.json). It is not part
  of config.json, so the wizard never sends it to the page and saving the setup never touches it.
  Changing it needs no restart.
- What is kept: a salted PBKDF2-SHA256 hash of the password, never the password, and a random key
  that signs the login cookie. A new password makes a new key, which logs every browser out.
- Login: a cookie (HttpOnly, SameSite=Lax, 30 days) holding an expiry time and its signature. Nothing
  about it is kept on the server, so a restart (saving the setup restarts the server) logs nobody out.
- Wrong guesses: 5 free tries per address, then 30 seconds, doubling up to 15 minutes.
- A file that can't be read counts as a password nobody knows, never as "no password".
- Forgot it: python -m houselights --remove-password (or --set-password) on the computer running
  House Lights, or delete access.json.

The page is plain HTTP on your own network, so the password protects against guests and curious
people, not against someone already watching the traffic on your Wi-Fi.
"""
import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import threading
import time
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from . import settings

log = logging.getLogger("houselights")

FILE = "access.json"
COOKIE = "hl_session"
DAYS = 30
ITERATIONS = 600_000                    # PBKDF2-SHA256, the 2023 OWASP number; only login pays for it
MIN_LEN, MAX_LEN = 8, 200
BROKEN = {"broken": True}
MSG_BROKEN = ("The password file is damaged. On the computer that runs House Lights, run "
              "python -m houselights --remove-password (then --set-password for a new one).")

# What a visitor may fetch without logging in: the login page and what it needs.
PUBLIC = frozenset(("/login", "/api/login", "/login.js", "/login.css", "/style.css", "/theme-init.js",
                    "/icon.svg", "/icon-192.png", "/icon-512.png", "/manifest.webmanifest"))

_warned = set()


def _file():
    return settings.path(FILE)


def read():
    """None when no password is set; else the stored entry. An unreadable file gives BROKEN."""
    try:
        with open(_file(), encoding="utf-8") as f:
            a = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        a = None
    try:
        good = (isinstance(a, dict) and 1 <= a["iterations"] <= 10_000_000
                and bytes.fromhex(a["salt"]) and bytes.fromhex(a["key"]) and bytes.fromhex(a["hash"]))
    except (KeyError, TypeError, ValueError):
        good = False
    if good:
        return a
    if _file() not in _warned:
        _warned.add(_file())
        log.error("%s can't be read: until it is removed (python -m houselights --remove-password) "
                  "nobody can log in", FILE)
    return BROKEN


def enabled():
    return read() is not None


# --- the password --------------------------------------------------------------------------------
def _hash(pw, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iterations).hex()


def make(pw, iterations=None):
    """What to store for a password: a fresh salt, its hash and a fresh cookie key."""
    n = iterations or ITERATIONS
    salt = os.urandom(16)
    return {"version": 1, "iterations": n, "salt": salt.hex(), "hash": _hash(pw, salt, n),
            "key": secrets.token_hex(32)}


def verify(pw, a):
    if not a or a.get("broken") or not isinstance(pw, str) or len(pw) > 1000:
        return False
    return hmac.compare_digest(_hash(pw, bytes.fromhex(a["salt"]), a["iterations"]), a["hash"])


def check_new(pw):
    """The reason a new password is refused, or ''."""
    if not isinstance(pw, str) or not pw:
        return "Type the new password."
    if len(pw) < MIN_LEN:
        return f"Use at least {MIN_LEN} characters."
    if len(pw) > MAX_LEN:
        return f"Use at most {MAX_LEN} characters."
    return ""


def store(pw):
    """Set or change the password. Returns the new entry."""
    a = make(pw)
    settings.write_private(FILE, a)
    return a


def remove():
    try:
        os.remove(_file())
    except FileNotFoundError:
        pass


# --- the login cookie ----------------------------------------------------------------------------
def _sign(key, exp):
    return hmac.new(bytes.fromhex(key), str(exp).encode("ascii"), "sha256").hexdigest()


def new_cookie(a, now=None):
    exp = int((time.time() if now is None else now) + DAYS * 86400)
    return f"{exp}.{_sign(a['key'], exp)}"


def cookie_ok(value, a, now=None):
    if not value or not a or a.get("broken"):
        return False
    exp, _, sig = str(value).partition(".")
    try:
        e = int(exp)
    except ValueError:
        return False
    if e < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(sig, _sign(a["key"], e))


# --- wrong guesses -------------------------------------------------------------------------------
class Throttle:
    """Per address: FREE wrong guesses, then a wait that starts at BASE seconds and doubles up to CAP."""
    FREE, BASE, CAP, FORGET, MAX = 5, 30, 900, 3600, 1000

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.who = {}

    def wait(self, who):
        """Seconds to wait before this address may guess again (0: go ahead)."""
        with self.lock:
            e = self.who.get(who)
            return max(0, math.ceil(e["until"] - self.clock())) if e else 0

    def fail(self, who):
        with self.lock:
            now = self.clock()
            for k in [k for k, e in self.who.items() if now - e["seen"] > self.FORGET and e["until"] < now]:
                del self.who[k]
            if who not in self.who and len(self.who) >= self.MAX:
                del self.who[min(self.who, key=lambda k: self.who[k]["seen"])]
            e = self.who.setdefault(who, {"n": 0, "until": 0, "seen": now})
            e["n"] += 1
            e["seen"] = now
            if e["n"] >= self.FREE:
                e["until"] = now + min(self.CAP, self.BASE * 2 ** (e["n"] - self.FREE))

    def ok(self, who):
        with self.lock:
            self.who.pop(who, None)


THROTTLE = Throttle()


def _who(request):
    return request.client.host if request.client else "?"


def _set_cookie(resp, request, a):
    resp.set_cookie(COOKIE, new_cookie(a), max_age=DAYS * 86400, path="/", httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")


def _guess(request, a, pw, what):
    """Count one guess of the password; raises the answer when it's wrong or the address must wait."""
    if a.get("broken"):
        raise HTTPException(401, MSG_BROKEN)
    who = _who(request)
    wait = THROTTLE.wait(who)
    if wait:
        raise HTTPException(429, f"Too many wrong tries. Wait {wait} seconds, then try again.",
                            headers={"Retry-After": str(wait)})
    if not verify(pw, a):
        THROTTLE.fail(who)
        raise HTTPException(401, what)
    THROTTLE.ok(who)


# --- the pages and calls -------------------------------------------------------------------------
router = APIRouter()
LOGIN_PAGE = os.path.join(settings.PKG, "static", "login.html")


@router.get("/login")
def login_page():
    if read() is None:
        return RedirectResponse("/", 303)
    return FileResponse(LOGIN_PAGE)


@router.post("/api/login")
def login(body: dict, request: Request):
    a = read()
    if a is None:
        return {"ok": True}                          # no password: nothing to log in to
    _guess(request, a, body.get("password"), "That password is not right.")
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, request, a)
    return resp


@router.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.post("/api/password")
def set_password(body: dict, request: Request):
    """Set a password, or change it (then the current one is needed too)."""
    problem = check_new(body.get("new"))
    if problem:
        raise HTTPException(400, problem)
    had = read()
    if had is not None:
        _guess(request, had, body.get("current"), "The current password is not right.")
    try:
        a = store(body["new"])
    except (OSError, ValueError) as e:
        raise HTTPException(400, f"Could not save the password: {e}") from None
    log.info("dashboard password %s", "changed" if had is not None else "set")
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, request, a)                    # this browser stays logged in; the others are logged out
    return resp


@router.post("/api/password/remove")
def remove_password(body: dict, request: Request):
    a = read()
    if a is not None:
        _guess(request, a, body.get("current"), "The current password is not right.")
        remove()
        log.info("dashboard password removed")
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


def _wants_page(request):
    return request.method in ("GET", "HEAD") and "text/html" in request.headers.get("accept", "") \
        and not request.url.path.startswith("/api/")


def install(app):
    """Add the login pages and the check on every request. Install it before guard.install, so the
    Host and Origin checks run first."""
    app.include_router(router)

    @app.middleware("http")
    async def gate(request, call_next):
        a = read()
        if a is None or request.url.path in PUBLIC or cookie_ok(request.cookies.get(COOKIE), a):
            return await call_next(request)
        if _wants_page(request):
            where = request.url.path + ("?" + request.url.query if request.url.query else "")
            return RedirectResponse("/login?next=" + quote(where, safe="/?=&"), 303)
        return JSONResponse({"detail": "Log in first.", "login": True}, status_code=401)


# --- python -m houselights --set-password / --remove-password --------------------------------------
def cli(set_it):
    import getpass
    if not set_it:
        existed = os.path.exists(_file())
        remove()
        print("The dashboard no longer asks for a password." if existed else "No password was set.")
        return 0
    pw = getpass.getpass("New dashboard password: ")
    problem = check_new(pw)
    if problem:
        print(problem)
        return 1
    if getpass.getpass("Type it again: ") != pw:
        print("The two passwords differ: nothing was changed.")
        return 1
    try:
        store(pw)
    except (OSError, ValueError) as e:
        print(f"Could not save the password: {e}")
        return 1
    print(f"Password set (in {_file()}). Browsers that were logged in must log in again.")
    return 0
