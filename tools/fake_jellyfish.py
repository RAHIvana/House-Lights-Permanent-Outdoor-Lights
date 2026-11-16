"""Simulated JellyFish Lighting controllers, for trying House Lights without real lights.

    python tools/fake_jellyfish.py --count 1 --zones Front:120,Back:80

Controllers at 127.0.0.31, ... (Linux; on macOS use --base 127.0.0.1 --count 1). Each serves
the documented WebSocket API at ws://<ip>:<port>/ws: "get zones" and "runPattern". Real
controllers use port 9000; use another port when testing beside one:

    HOUSELIGHTS_JELLYFISH_PORT=19000 python tools/fake_jellyfish.py
    HOUSELIGHTS_JELLYFISH_PORT=19000 python -m houselights
"""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
import socketserver
import struct
import threading
import time

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _read_frame(rfile):
    h = rfile.read(2)
    if len(h) < 2:
        return None, None
    op, n = h[0] & 0x0F, h[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", rfile.read(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rfile.read(8))[0]
    mask = rfile.read(4) if h[1] & 0x80 else b""
    data = rfile.read(n)
    if mask:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return op, data


def _frame(payload, op=1):
    n = len(payload)
    head = bytes([0x80 | op]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536
                                 else bytes([127]) + struct.pack(">Q", n))
    return head + payload


class Controller:
    def __init__(self, ip, zones):
        self.ip = ip
        self.zones = {name: {"numPixels": n, "portMap": [{"ctlrName": f"JellyFish-{ip.split('.')[-1]}.local",
                                                          "phyEndIdx": n - 1, "phyPort": k + 1, "phyStartIdx": 0,
                                                          "zoneRGBStartIdx": 0}]}
                      for k, (name, n) in enumerate(zones)}
        self.running = {name: {"state": 0, "data": None, "file": ""} for name, _ in zones}
        self.messages = 0
        self.lock = threading.Lock()

    def handle(self, msg):
        with self.lock:
            self.messages += 1
            if msg.get("cmd") == "toCtlrGet" and msg.get("get") == [["zones"]]:
                return {"cmd": "fromCtlr", "save": True, "zones": self.zones}
            rp = msg.get("runPattern")
            if msg.get("cmd") == "toCtlrSet" and isinstance(rp, dict):
                data = json.loads(rp["data"]) if rp.get("data") else None
                for z in rp.get("zoneName") or list(self.zones):
                    if z in self.running:
                        self.running[z] = {"state": rp.get("state", 1), "data": data or self.running[z]["data"],
                                           "file": rp.get("file", "")}
                return {"cmd": "fromCtlr", "runPattern": rp}
            return {"cmd": "fromCtlr", "error": "unknown command"}

    def shown(self, zone):
        """What a person would see on a zone (our reading of the documented pattern fields)."""
        r, n = self.running[zone], self.zones[zone]["numPixels"]
        if not r["state"] or not r["data"]:
            return ["#000000"] * n
        d = r["data"]
        flat = d["colors"]
        pal = ["#%02x%02x%02x" % tuple(flat[i:i + 3]) for i in range(0, len(flat) - 2, 3)]
        b = max(1, d.get("numOfLeds", 1)) if d.get("type") == "Multi-Paint" else 1
        return [pal[(i // b) % len(pal)] for i in range(n)]


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True            # restart right away, even while old connections close
    daemon_threads = True


def serve(base="127.0.0.31", count=1, zones=(("Zone", 50),), port=19000, state_file=None, quiet=True):
    ctrls = []
    for k in range(count):
        ip = str(ipaddress.ip_address(base) + k)
        c = Controller(ip, zones)
        ctrls.append(c)

        class Handler(socketserver.StreamRequestHandler):
            ctl = c

            def handle(self):
                head = b""
                while b"\r\n\r\n" not in head:
                    chunk = self.request.recv(4096)
                    if not chunk:
                        return
                    head += chunk
                lines = head.decode("latin-1").split("\r\n")
                if not lines[0].startswith("GET /ws "):
                    self.request.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                    return
                key = next(l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("sec-websocket-key:"))
                acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
                self.request.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                                      f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
                while True:
                    op, data = _read_frame(self.rfile)
                    if op is None:
                        return
                    if op == 8:                    # answer the close, then let the client hang up first,
                        try:                       # so the waiting socket is the client's, not this port
                            self.request.sendall(_frame(b"\x03\xe8", 8))
                            self.request.settimeout(2)
                            while self.request.recv(1024):
                                pass
                        except OSError:
                            pass
                        return
                    if op != 1:
                        continue
                    msg = json.loads(data)
                    reply = self.ctl.handle(msg)
                    if not quiet:
                        print(f"{time.strftime('%H:%M:%S')} {self.ctl.ip} {json.dumps(msg)[:110]}", flush=True)
                    if state_file:
                        dump(ctrls, state_file)
                    self.request.sendall(_frame(json.dumps(reply).encode()))

        srv = _Server((ip, port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return ctrls


def dump(ctrls, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({c.ip: {z: {"state": c.running[z]["state"], "pixels": c.zones[z]["numPixels"],
                              "data": c.running[z]["data"], "shown": c.shown(z)} for z in c.zones}
                   for c in ctrls}, f)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--base", default="127.0.0.31")
    ap.add_argument("--zones", default="Zone:50", help="zones and pixel counts, e.g. Front:120,Back:80")
    ap.add_argument("--state", help="write what each zone shows to this JSON file")
    a = ap.parse_args()
    zones = [(z.split(":")[0], int(z.split(":")[1])) for z in a.zones.split(",")]
    port = int(os.environ.get("HOUSELIGHTS_JELLYFISH_PORT", "19000"))
    ctrls = serve(a.base, a.count, zones, port, a.state, quiet=False)
    print(f"{a.count} simulated JellyFish controller(s): {', '.join(c.ip for c in ctrls)} (port {port})", flush=True)
    while True:
        time.sleep(1)
        if a.state:
            dump(ctrls, a.state)


if __name__ == "__main__":
    main()
