"""Small network helpers for the drivers, standard library only: JSON over HTTP, a minimal
WebSocket client, probing many addresses at once, and finding this computer's network."""
import base64
import hashlib
import ipaddress
import json
import os
import socket
import struct
import urllib.request
from concurrent.futures import ThreadPoolExecutor

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# --- HTTP JSON ----------------------------------------------------------------------------
def http_json(url, body=None, timeout=3.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else {}


# --- WebSocket client (RFC 6455, text frames, no extensions) -----------------------------------
def _ws_frame(payload, opcode=1):
    """A client frame: FIN, opcode, masked payload."""
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 65536:
        head += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", n)
    mask = os.urandom(4)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def _recv_exact(sock, n, buf):
    while len(buf) < n:
        chunk = sock.recv(65536)
        if not chunk:
            raise OSError("connection closed")
        buf += chunk
    return buf[:n], buf[n:]


def _ws_read(sock, buf):
    """One whole message (joins fragments). Returns (opcode, payload, rest of buffer)."""
    parts, opcode = [], None
    while True:
        h, buf = _recv_exact(sock, 2, buf)
        fin, op = h[0] & 0x80, h[0] & 0x0F
        masked, n = h[1] & 0x80, h[1] & 0x7F
        if n == 126:
            ext, buf = _recv_exact(sock, 2, buf)
            n = struct.unpack(">H", ext)[0]
        elif n == 127:
            ext, buf = _recv_exact(sock, 8, buf)
            n = struct.unpack(">Q", ext)[0]
        mask = b""
        if masked:
            mask, buf = _recv_exact(sock, 4, buf)
        data, buf = _recv_exact(sock, n, buf)
        if masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if op == 9:                                  # ping: answer and keep reading
            sock.sendall(_ws_frame(data, 10))
            continue
        if op == 10:
            continue
        if op != 0:
            opcode = op
        parts.append(data)
        if fin:
            return opcode, b"".join(parts), buf


def ws_exchange(host, port, path, messages, reply=True, timeout=3.0):
    """Open a WebSocket, send each message (str), and return the first text reply parsed as
    JSON (or None when reply=False or nothing came back in time)."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("WebSocket handshake: connection closed")
            buf += chunk
            if len(buf) > 65536:
                raise OSError("WebSocket handshake: reply too long")
        head, buf = buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " ":
            raise OSError(f"WebSocket handshake refused: {lines[0]}")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if not any(l.lower().startswith("sec-websocket-accept:") and l.split(":", 1)[1].strip() == accept for l in lines):
            raise OSError("WebSocket handshake: bad accept key")
        for m in messages:
            sock.sendall(_ws_frame(m.encode()))
        result = None
        if reply:
            try:
                while True:
                    op, data, buf = _ws_read(sock, buf)
                    if op == 8:
                        break
                    if op == 1:
                        try:
                            result = json.loads(data)
                        except ValueError:
                            continue
                        break
            except socket.timeout:
                pass
        try:
            sock.sendall(_ws_frame(struct.pack(">H", 1000), 8))
        except OSError:
            pass
        return result
    finally:
        sock.close()


# --- scanning ------------------------------------------------------------------------------
HOME_ADDRESSES = "192.168.x.x, 10.x.x.x, 172.16 to 172.31.x.x"


def is_home_address(ip):
    """True for an address on your own network: loopback, 192.168.x.x, 10.x.x.x, 172.16-31.x.x,
    link-local, and IPv6 private ones. House Lights sends packets to what it is told to, and its login
    is optional, so it will not be pointed at the internet."""
    try:
        a = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    # "reserved" is only meaningful for IPv4 here (240.x.x.x, broadcast); Python also calls ::1 reserved
    return (a.is_private or a.is_loopback or a.is_link_local) and not (
        a.is_multicast or a.is_unspecified or (a.version == 4 and a.is_reserved))


def local_networks():
    """This computer's own /24 network, to scan when the user typed no addresses.
    (Connecting a UDP socket sends nothing; it only picks the outgoing interface.)"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip.startswith("127."):
            return []
        return [str(ipaddress.ip_network(ip + "/24", strict=False))]
    except OSError:
        return []


def probe_many(fn, ips, workers=64):
    """fn(ip) for every address at once; returns {ip: result} for those that didn't fail."""
    out = {}

    def one(ip):
        try:
            r = fn(ip)
            if r is not None:
                out[ip] = r
        except Exception:                            # nothing there, refused, timed out, not our kind
            pass
    if ips:
        with ThreadPoolExecutor(max_workers=min(workers, len(ips))) as pool:
            list(pool.map(one, ips))
    return out


def kelvin_to_rgb(k):
    """Rough color of white light at k kelvin, for controllers without a white channel."""
    import math
    t = max(1000, min(40000, int(k))) / 100
    r = 255 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255 if t >= 66 else 0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    return tuple(max(0, min(255, round(v))) for v in (r, g, b))
