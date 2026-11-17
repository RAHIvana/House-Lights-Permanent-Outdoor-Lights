"""Checks on every web request, because House Lights has no login.

Without them, a web page you open on some other site could talk to the dashboard through your
own browser: by pointing a made-up name at your computer's address ("DNS rebinding"), by sending
a request that needs no permission (a plain form), or by showing the dashboard in a hidden frame.

- Host: only IP addresses, localhost, one-word names and names ending in .local, .lan, .home,
  .home.arpa, .localdomain or .internal are answered, plus this computer's own name and any names
  in the environment variable HOUSELIGHTS_ALLOWED_HOSTS (comma separated). A name from the public
  internet is not, so a rebinding page can't reach the dashboard.
- Origin: a request that changes something must come from the dashboard's own page, or from no web
  page at all (a script, curl).
- Content type: a request with a body must say it is JSON.
- Headers: a content security policy, no framing, no sniffing, no referrer.
"""
import ipaddress
import os
import socket
from functools import lru_cache
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

UNSAFE = ("POST", "PUT", "PATCH", "DELETE")
HOME_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".localdomain", ".internal", ".localhost")

# Scripts only from the dashboard's own files (no inline scripts, no other sites); styles may be
# inline (the page sets colors that way); pictures may come from a file you chose (a photo's colors).
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=(), usb=()",
}
MSG_HOST = ("House Lights answers only to IP addresses, localhost and names on your own network (like pi.local). "
            "To allow another name, list it in the HOUSELIGHTS_ALLOWED_HOSTS environment variable.")
MSG_ORIGIN = "This request came from another web page, so House Lights refused it."
MSG_TYPE = "Send JSON, with a Content-Type of application/json."


def split_host(value):
    """'Pi.local:8090' -> 'pi.local'; '[::1]:8090' -> '::1'; '' -> ''."""
    v = (value or "").strip().lower()
    if v.startswith("["):
        end = v.find("]")
        return v[1:end] if end > 0 else ""
    if v.count(":") == 1:
        v = v.split(":")[0]
    return v.rstrip(".")


@lru_cache(maxsize=1)
def own_name():
    try:
        return socket.gethostname().lower()
    except OSError:
        return ""


def allowed_extra():
    return {h.strip().lower().rstrip(".") for h in os.environ.get("HOUSELIGHTS_ALLOWED_HOSTS", "").split(",") if h.strip()}


def host_allowed(value, extra=()):
    """May a request with this Host header be answered?"""
    name = split_host(value)
    if not name:
        return False
    try:
        ipaddress.ip_address(name)             # an address: rebinding needs a name
        return True
    except ValueError:
        pass
    if name == "localhost" or "." not in name or name.endswith(HOME_SUFFIXES):
        return True
    return name == own_name() or name in {h.lower().rstrip(".") for h in extra}


def origin_ok(origin, host):
    """No Origin: not a web page. Otherwise it must be this very server (same host and port)."""
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return parts.netloc.lower() == (host or "").strip().lower()


def fetch_site_ok(value):
    """Browsers say where a request came from; for changes, only the dashboard's own page (or the
    address bar) will do."""
    return (value or "").lower() in ("", "same-origin", "none")


def content_type_ok(method, headers):
    """A request that changes something and has a body must say it is JSON."""
    if method not in UNSAFE:
        return True
    has_body = headers.get("content-length", "0") not in ("", "0") or "transfer-encoding" in headers
    if not has_body:
        return True
    return headers.get("content-type", "").split(";")[0].strip().lower() == "application/json"


def install(app):
    """Add the checks and the headers to every response of a FastAPI app."""
    @app.middleware("http")
    async def guard(request, call_next):
        h = request.headers
        problem = None
        if not host_allowed(h.get("host", ""), allowed_extra()):
            problem = (403, MSG_HOST)
        elif request.method in UNSAFE and not (origin_ok(h.get("origin", ""), h.get("host", ""))
                                               and fetch_site_ok(h.get("sec-fetch-site", ""))):
            problem = (403, MSG_ORIGIN)
        elif not content_type_ok(request.method, h):
            problem = (415, MSG_TYPE)
        resp = JSONResponse({"detail": problem[1]}, status_code=problem[0]) if problem else await call_next(request)
        for k, v in HEADERS.items():
            resp.headers[k] = v
        return resp
