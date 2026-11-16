"""Govee lights over the local network (Govee "LAN control", no cloud account needed).

Protocol: JSON over UDP. Commands go to the device on port 4003, discovery ("scan") to port
4001 (multicast 239.255.255.250 or unicast), and devices answer on port 4002 of the sender.
LAN control has to be switched on for each device in the Govee Home app.

Segment colours use "ptReal" packets (BLE-style 20-byte frames); per-light animation uses
the "razer" (DreamView) streaming mode. Both were verified on model H806A.
"""
import base64
import ipaddress
import json
import logging
import os
import socket
import threading
import time

from .base import Kit as BaseKit

log = logging.getLogger("houselights")

LABEL = "Govee (Wi-Fi, LAN control)"
NOTE = "Switch on LAN Control for each device in the Govee Home app first."
TESTED = True

# Models known to work. lights_per_segment: how many lights one segment colours, counted
# from light 1. max_lights: a streaming frame carries at most 255 lights.
MODELS = {
    "H806A": {"label": "Permanent Outdoor Lights Pro (H806A)", "lights_per_segment": 5, "max_lights": 255},
}

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

    def scan(self, targets=(), wait=2.5, multicast=True):
        """Ask devices to identify themselves: multicast on this network, plus unicast to each
        address in `targets` (needed when the lights are on another subnet)."""
        found = {}
        with self._reply_lock:
            rx = self._listen()
            try:
                body = {"account_topic": "reserve"}
                if multicast:
                    try:
                        m = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        m.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                        m.sendto(json.dumps({"msg": {"cmd": "scan", "data": body}}).encode(), (MULTICAST, SCAN_PORT))
                        m.close()
                    except OSError as e:
                        log.warning("multicast scan failed: %s", e)
                for ip in targets:
                    try:
                        self.send(ip, "scan", body, port=SCAN_PORT)
                    except OSError:
                        pass
                end = time.time() + wait
                while time.time() < end:
                    try:
                        d, a = rx.recvfrom(4096)
                    except socket.timeout:
                        continue
                    m = self._msg(d)
                    if m and m.get("cmd") == "scan" and isinstance(m.get("data"), dict):
                        data = m["data"]
                        found[data.get("ip") or a[0]] = data
            finally:
                rx.close()
        return found


LAN = Lan()


def expand_targets(text, limit=1024):
    """'192.168.1.0/24, 10.0.0.7' -> list of addresses to scan one by one."""
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
    sku = str(d.get("sku", "?"))
    dev = str(d.get("device", ""))
    return {"ip": ip, "type": "govee", "model": sku, "device_tail": dev[-5:], "lights": None,
            "supported": sku in MODELS, "label": MODELS.get(sku, {}).get("label", f"Govee {sku} (not supported yet)")}


def probe(info):
    """Add by address: ask that one device who it is."""
    ip = expand_targets(info.get("ip", ""))
    if len(ip) != 1:
        raise ValueError("type one IP address")
    found = LAN.scan(ip, wait=2.0, multicast=False)
    if not found:
        raise ValueError(f"no Govee device answered at {ip[0]}. Is LAN Control on in the Govee Home app?")
    return [_row(a, d) for a, d in found.items()]


def discover(targets=""):
    """Devices that answered a scan: [{ip, model, device_tail, supported, label}]."""
    found = LAN.scan(expand_targets(targets))
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
    CAPS = {"stream": True, "static": "segments", "pick": True, "status": True, "count": "manual",
            "restore": "auto"}
    max_stream_lights = 255

    def __init__(self, controller, live):
        super().__init__(controller, live)
        self.lan = LAN

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
        self._razer(RAZER_ON)

    def stream_frame(self, colors):
        self._razer(razer_frame(colors))

    def stream_end(self):
        self._razer(RAZER_OFF)
