"""Govee lights over the local network (Govee "LAN control", no cloud account needed).

Protocol: JSON over UDP. Commands go to the device on port 4003, discovery ("scan") to port
4001 (multicast 239.255.255.250 or unicast), and devices answer on port 4002 of the sender.
LAN control has to be switched on for each device in the Govee Home app.

Govee documents only the basic LAN commands: turn, brightness, colorwc (colour or colour
temperature) and devStatus. Segment colours use "ptReal" packets (BLE-style 20-byte frames)
and per-light animation the "razer" (DreamView) streaming mode; neither is documented, and
both were verified on model H806A only. So what a controller may do depends on its model
(SKU), in three tiers (model_info()):
  full   H806A: per-light streaming, segment colours (5 lights each), up to 255 lights
  try    permanent outdoor families with LAN control (H705x, H706x, H707x, H805x, H3A5x):
         basic control, per-light streaming allowed but untested ("stream_untested"), no
         segment colours: a static theme shows its main colour (or plays as a stream)
  basic  any other model that answers the scan: on/off, brightness, one colour, white,
         status, schedules; a theme shows its main colour
"""
import base64
import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time

from .base import ONE_COLOUR_CAPS, NotAllowed
from .base import Kit as BaseKit

log = logging.getLogger("houselights")

LABEL = "Govee (Wi-Fi, LAN control)"
NOTE = "Switch on LAN Control for each device in the Govee Home app first."
TESTED = True

# What each tier may do (see base.py for the keys). "stream_untested": per-light streaming is
# allowed but has not been seen working on that model: the page and wizard say "try it".
FULL_CAPS = {"stream": True, "static": "segments", "pick": True, "status": True, "count": "manual",
             "restore": "auto"}
TRY_CAPS = {"stream": True, "stream_untested": True, "static": "segments", "pick": False, "status": True,
            "count": "manual", "restore": "auto"}
BASIC_CAPS = dict(ONE_COLOUR_CAPS)        # like a Tuya strip: one colour at a time, put back after a test

# lights_per_segment: how many lights one segment colours, counted from light 1 (0: no
# segments, the whole run is one colour). max_lights: a streaming frame carries at most 255
# lights; a run that doesn't stream only needs a count to draw it on the page.
TIERS = {
    "full": {"label": "Full support", "caps": FULL_CAPS, "lights_per_segment": 5, "max_lights": 255,
             "note": "Everything: themes light by light, segment colours. Tested on real controllers."},
    "try": {"label": "Basic control; light-by-light themes to try", "caps": TRY_CAPS, "lights_per_segment": 0,
            "max_lights": 255,
            "note": "On/off, brightness, colours and schedules work. Light-by-light themes (Play live) are "
                    "untested on this model: try them. Static themes show their main colour."},
    "basic": {"label": "Basic control", "caps": BASIC_CAPS, "lights_per_segment": 0, "max_lights": 3000,
              "note": "On/off, brightness, one colour, white and schedules. Themes show their main colour."},
}

TRY_FAMILIES = ("H705A", "H705B", "H705C", "H705D", "H705E", "H705F",      # Permanent Outdoor Lights (2)
                "H706A", "H706B", "H706C",                                 # Permanent Outdoor Lights Pro
                "H707A", "H707B", "H707C",                                 # Prism (community lists)
                "H805A", "H805B", "H805C",                                 # Elite
                "H3A51", "H3A52", "H3A53")                                 # 2 Pro (LAN control unconfirmed)

# Models known by name: the full tier and the "try" families. Any other SKU-shaped model is
# accepted in the basic tier (model_info()).
MODELS = {"H806A": {"label": "Govee H806A", "tier": "full", "lights_per_segment": 5, "max_lights": 255},
          **{m: {"label": f"Govee {m}", "tier": "try", "lights_per_segment": 0, "max_lights": 255}
             for m in TRY_FAMILIES}}
MODELS_NOTE = ("H806A: everything (tested). H705A-F, H706A-C, H707A-C, H805A-C, H3A51-53: basic control, "
               "light-by-light themes to try. Any other Govee model with LAN Control: basic control.")
SKU = re.compile(r"H[0-9A-Z]{4,5}")


def model_info(sku):
    """{model, label, tier, caps, max_lights, lights_per_segment, note} for a Govee model
    (SKU, e.g. "H806A"), or None if it doesn't look like one. Unknown SKUs are "basic"."""
    sku = str(sku or "").strip().upper()
    if not SKU.fullmatch(sku):
        return None
    known = MODELS.get(sku)
    tier = known["tier"] if known else "basic"
    t = TIERS[tier]
    return {"model": sku, "label": known["label"] if known else f"Govee {sku}", "tier": tier,
            "caps": dict(t["caps"]), "max_lights": known["max_lights"] if known else t["max_lights"],
            "lights_per_segment": known["lights_per_segment"] if known else t["lights_per_segment"],
            "note": t["note"]}

# HOUSELIGHTS_GOVEE_PORTS="scan,reply,command" moves the ports, only for the simulator
# (tools/fake_govee.py) so it can run beside real devices. Real devices use 4001,4002,4003.
SCAN_PORT, REPLY_PORT, CMD_PORT = (int(p) for p in os.environ.get("HOUSELIGHTS_GOVEE_PORTS", "4001,4002,4003").split(","))
MULTICAST = "239.255.255.250"


class Lan:
    _reply_lock = threading.Lock()          # one owner of the reply port at a time

    def __init__(self):
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, ip, cmd, data, port=None):
        self.tx.sendto(json.dumps({"msg": {"cmd": cmd, "data": data}}).encode(), (ip, port or CMD_PORT))

    def _listen(self):
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if os.name != "nt":
            # Not on Windows: there the bind then succeeds beside another program already on
            # this port, and that program keeps getting every reply, so a scan silently finds
            # nothing. Without it, the bind fails and says why.
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            rx.bind(("", REPLY_PORT))
        except OSError as e:
            rx.close()
            raise OSError(f"can't listen for Govee replies on UDP port {REPLY_PORT}; is another program "
                          f"using it? ({e.strerror or e})") from None
        rx.settimeout(0.2)
        return rx

    @staticmethod
    def _msg(data):
        try:
            return json.loads(data)["msg"]
        except (ValueError, KeyError, TypeError):
            return None

    def status(self, ips, rounds=2, wait=1.2):
        """devStatus for several devices at once. Binds the reply port only while asking."""
        result = {ip: None for ip in ips}
        if not ips:
            return result
        with self._reply_lock:
            rx = self._listen()
            try:
                for _ in range(rounds):
                    pending = [ip for ip, v in result.items() if v is None]
                    if not pending:
                        break
                    for ip in pending:
                        self.send(ip, "devStatus", {})
                    end = time.time() + wait
                    while time.time() < end and any(result[ip] is None for ip in pending):
                        try:
                            d, a = rx.recvfrom(4096)
                        except socket.timeout:
                            continue
                        m = self._msg(d)
                        if a[0] in result and m and m.get("cmd") == "devStatus":
                            result[a[0]] = m.get("data")
            finally:
                rx.close()
        return result

    def scan(self, targets=(), wait=2.5, multicast=True, rounds=3, expect=0, known=()):
        """Ask devices to identify themselves: multicast on this network, plus unicast to each
        address in `targets` (needed when the lights are on another subnet).

        Asks `rounds` times within `wait` seconds, each time only the addresses that haven't
        answered yet. Controllers answer only some requests (measured on H806A over Wi-Fi: one
        in 4 to one in 10), so a single try misses them at random; asking again finds them.
        Stops early when every unicast target has answered (without multicast), or when
        `expect` devices are known, counting the addresses in `known` found before."""
        found, answered = {}, set()
        targets = [ip for ip in targets if ip not in set(known)]
        period = wait / max(1, rounds)

        def done():
            if expect and len(set(found) | set(known)) >= expect:
                return True
            return not multicast and all(ip in answered for ip in targets)

        def collect(until):
            while time.time() < until and not done():
                try:
                    d, a = rx.recvfrom(4096)
                except (socket.timeout, ConnectionResetError):
                    continue
                m = self._msg(d)
                if m and m.get("cmd") == "scan" and isinstance(m.get("data"), dict):
                    data = m["data"]
                    found[data.get("ip") or a[0]] = data
                    answered.update({a[0], str(data.get("ip") or a[0])})

        with self._reply_lock:
            rx = self._listen()
            rx.settimeout(0.02)
            try:
                body = {"account_topic": "reserve"}
                start, multicast_ok = time.time(), multicast
                for r in range(rounds):
                    if done():
                        break
                    if multicast_ok:
                        try:
                            m = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            m.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                            m.sendto(json.dumps({"msg": {"cmd": "scan", "data": body}}).encode(), (MULTICAST, SCAN_PORT))
                            m.close()
                        except OSError as e:
                            log.warning("multicast scan failed: %s", e)
                            multicast_ok = False
                    todo = [ip for ip in targets if ip not in answered]
                    for k in range(0, len(todo), 16):      # spread a big burst, reading replies meanwhile
                        for ip in todo[k:k + 16]:
                            try:
                                self.send(ip, "scan", body, port=SCAN_PORT)
                            except OSError:
                                pass
                        if len(todo) > 16:
                            collect(time.time() + min(0.01, period / 40))
                    collect(start + period * (r + 1))
            finally:
                rx.close()
        return found


LAN = Lan()


def expand_targets(text, limit=1024):
    """'192.168.2.0/24, 192.168.2.7' -> list of addresses to scan one by one."""
    out = []
    for part in str(text or "").replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "/" in part:
                net = ipaddress.ip_network(part, strict=False)
                if net.num_addresses > limit:
                    raise ValueError(f"{part} is too big to scan (at most {limit} addresses)")
                out += [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
            else:
                out.append(str(ipaddress.ip_address(part)))
        except ValueError as e:
            raise ValueError(str(e) if "too big" in str(e) else f"{part!r} is not an address or network") from None
    if len(out) > limit:
        raise ValueError(f"too many addresses to scan (at most {limit})")
    return out


def available():
    return True, ""


def options(c, secret):
    """Govee needs nothing beyond the address and model."""
    return {}, {}


def _row(ip, d):
    """One scan answer for the wizard. Every SKU-shaped model is supported, in its tier."""
    sku = str(d.get("sku", "?"))
    dev = str(d.get("device", ""))
    info = model_info(sku)
    if not info:
        return {"ip": ip, "type": "govee", "model": sku, "device_tail": dev[-5:], "lights": None,
                "supported": False, "tier": None, "label": f"Govee {sku} (not supported yet)"}
    return {"ip": ip, "type": "govee", "model": info["model"], "device_tail": dev[-5:], "lights": None,
            "supported": True, "tier": info["tier"], "label": info["label"]}


def probe(info):
    """Add by address: ask that one device who it is."""
    ip = expand_targets(info.get("ip", ""))
    if len(ip) != 1:
        raise ValueError("type one IP address")
    found = LAN.scan(ip, wait=6.0, multicast=False, rounds=40)      # one address: ask often, stop at the answer
    if not found:
        raise ValueError(f"no Govee device answered at {ip[0]}. Is LAN Control on in the Govee Home app?")
    return [_row(a, d) for a, d in found.items()]


QUICK_SCAN = (3.0, 10)          # seconds, rounds: one request every 0.3 s to each silent address
DEEP_SCAN = (30.0, 100)         # the wizard's deep scan, when the quick one didn't find them all


def discover(targets="", deep=False, expect=0, known=()):
    """Devices that answered a scan: [{ip, model, device_tail, supported, label}]. A deep scan
    keeps asking for longer; it stops once `expect` devices are known (with those in `known`)."""
    wait, rounds = DEEP_SCAN if deep else QUICK_SCAN
    found = LAN.scan(expand_targets(targets), wait=wait, rounds=rounds, expect=expect, known=known)
    return [_row(ip, d) for ip, d in sorted(found.items(), key=lambda kv: _ipkey(kv[0]))]


def _ipkey(ip):
    try:
        return (0, int(ipaddress.ip_address(ip)))
    except ValueError:
        return (1, 0)


def read_status(kits):
    """{controller id: {onOff, brightness, color {r,g,b}, colorTemInKelvin} or None}."""
    got = LAN.status(sorted({k.c.ip for k in kits}))
    return {k.c.id: got.get(k.c.ip) for k in kits}


# --- packets -----------------------------------------------------------------------------
def ble_frame(body):
    """BLE-style 20-byte frame: body padded to 19 bytes + XOR checksum."""
    if len(body) > 19:
        raise ValueError("frame body longer than 19 bytes")
    body = bytes(body).ljust(19, b"\0")
    c = 0
    for b in body:
        c ^= b
    return body + bytes([c])


def segment_color_packet(segs, rgb, nseg):
    """Mask is little-endian, bit s = segment s, ceil(nseg/8) bytes (at least 2)."""
    mask = 0
    for s in segs:
        mask |= 1 << s
    width = max(2, -(-nseg // 8))
    return ble_frame(bytes([0x33, 0x05, 0x15, 0x01, *rgb, 0, 0, 0, 0, 0]) + mask.to_bytes(width, "little"))


RAZER_ON = bytes.fromhex("bb0001b1010a")
RAZER_OFF = bytes.fromhex("bb0001b1000b")


def razer_frame(colors, mode=0x00):
    """BB LEN_HI LEN_LO B0 MODE N [R G B]*N XOR  (LEN = 2 + 3N; mode 0 = no blending)."""
    payload = bytes([mode, len(colors)]) + b"".join(bytes(c) for c in colors)
    pkt = bytes([0xBB, len(payload) >> 8, len(payload) & 0xFF, 0xB0]) + payload
    c = 0
    for b in pkt:
        c ^= b
    return pkt + bytes([c])


# --- one device ----------------------------------------------------------------------------
class Kit(BaseKit):
    """One Govee controller. What it may do comes from its model's tier (self.caps); CAPS is
    the driver-level summary (the full tier)."""
    CAPS = FULL_CAPS
    max_stream_lights = 255

    def __init__(self, controller, live):
        super().__init__(controller, live)
        self.lan = LAN
        self.info = model_info(controller.model) or dict(model_info("H0000"), model=controller.model,
                                                          label=f"Govee {controller.model}")    # not a SKU: basic
        self.max_stream_lights = min(255, self.info["max_lights"])

    @property
    def caps(self):
        return self.info["caps"]

    def _need(self, cap, what):
        if not self.caps.get(cap):
            raise NotAllowed(f"{self.info['label']} can't {what} (basic LAN control only)")

    def _lan(self, cmd, data):
        self.guard()
        log.info("%s %s %s %s", self.prefix, self.tag, cmd, json.dumps(data))
        if self.live:
            self.lan.send(self.c.ip, cmd, data)
            time.sleep(0.3)

    def power(self, on):
        with self.lock:
            self._lan("turn", {"value": 1 if on else 0})

    def brightness(self, value):
        with self.lock:
            self._lan("brightness", {"value": max(1, min(100, int(value)))})

    def color(self, rgb):
        r, g, b = rgb
        with self.lock:
            self._lan("colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})

    def kelvin(self, k):
        with self.lock:
            self._lan("colorwc", {"color": {"r": 0, "g": 0, "b": 0},
                                  "colorTemInKelvin": max(2000, min(9000, int(k)))})

    def segments(self, segs, rgb, nseg):
        self.guard()
        if not self.caps.get("pick"):
            raise NotAllowed(f"{self.info['label']} can't colour segments one by one (checked on H806A only)")
        segs = sorted(set(int(s) for s in segs))
        if not segs or segs[0] < 0 or segs[-1] >= nseg:
            raise ValueError(f"segments out of range 0..{nseg - 1}: {segs}")
        pkt = segment_color_packet(segs, rgb, nseg)
        log.info("%s %s ptReal segments %s #%02X%02X%02X", self.prefix, self.tag, segs, *rgb)
        if self.live:
            self.lan.send(self.c.ip, "ptReal", {"command": [base64.b64encode(pkt).decode()]})
        time.sleep(0.25 if self.live else 0.05)

    def _razer(self, pkt):
        if self.live:
            self.lan.send(self.c.ip, "razer", {"pt": base64.b64encode(pkt).decode()})

    def stream_begin(self):
        self.guard()
        self._need("stream", "play light-by-light themes")
        self._razer(RAZER_ON)

    def stream_frame(self, colors):
        self._need("stream", "play light-by-light themes")
        self._razer(razer_frame(colors))

    def stream_end(self):
        self._need("stream", "play light-by-light themes")
        self._razer(RAZER_OFF)

    # --- tests on models that don't stream: save the state and put it back -----------------
    def snapshot(self):
        if not self.live:
            return None
        try:
            return self.lan.status([self.c.ip]).get(self.c.ip)
        except OSError:
            return None

    def restore(self, snap):
        if not snap or not self.live:
            return
        col = snap.get("color") or {}
        k = int(snap.get("colorTemInKelvin") or 0)
        with self.lock:
            log.info("%s %s restore %s", self.prefix, self.tag, json.dumps(snap))
            if k:
                self._lan("colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": k})
            else:
                self._lan("colorwc", {"color": {c: int(col.get(c, 0)) for c in "rgb"}, "colorTemInKelvin": 0})
            if snap.get("brightness"):
                self._lan("brightness", {"value": max(1, min(100, int(snap["brightness"])))})
            self._lan("turn", {"value": 1 if snap.get("onOff") else 0})
