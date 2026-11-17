"""Simulated WLED controllers, for trying House Lights without real lights.

    python tools/fake_wled.py --count 2 --lights 60,150

Devices at 127.0.0.21, 127.0.0.22, ... (Linux and Windows; on macOS use --base 127.0.0.1
--count 1). Each serves the WLED JSON API (/json/info, /json/state) on HTTP and takes UDP
realtime packets (DRGB, DNRGB) by the same rules as the real receiver (wled00/udp.cpp): a DRGB
packet needs more than 4 bytes, a DNRGB packet more than 7 (so one light by DNRGB is ignored),
byte 1 is the timeout in seconds (0 leaves realtime mode at once, 255 never times out). Real WLED uses port 80 and 21324; port 80 needs admin rights,
so the simulator uses other ports and House Lights must be told:

    HOUSELIGHTS_WLED_PORTS=18080,21325 python tools/fake_wled.py
    HOUSELIGHTS_WLED_PORTS=18080,21325 python -m houselights
"""
import argparse
import ipaddress
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Device:
    def __init__(self, ip, n, k):
        self.ip, self.n = ip, n
        self.on, self.bri = True, 128
        self.col = [255, 160, 80]
        self.leds = [list(self.col) for _ in range(n)]      # what the lights show outside realtime
        self.live_frame, self.live_until = None, 0.0
        self.mac = f"fa1e0000{k:04x}"
        self.posts, self.packets, self.released = 0, 0, 0
        self.lock = threading.Lock()

    @property
    def live(self):
        return time.monotonic() < self.live_until

    def info(self, udp_port):
        return {"ver": "0.15.0", "vid": 2412100, "name": f"Sim WLED {self.ip.split('.')[-1]}", "brand": "WLED",
                "product": "FOSS", "mac": self.mac, "ip": self.ip, "udpport": udp_port, "live": self.live,
                "leds": {"count": self.n, "rgbw": False, "lc": 1, "pwr": 0, "maxseg": 16}}

    def state(self):
        return {"on": self.on, "bri": self.bri, "transition": 7, "ps": -1,
                "seg": [{"id": 0, "start": 0, "stop": self.n, "len": self.n, "on": True, "bri": 255,
                         "col": [list(self.col), [0, 0, 0], [0, 0, 0]], "fx": 0}]}

    @staticmethod
    def _rgb(c):
        if isinstance(c, str):
            return [int(c[i:i + 2], 16) for i in (0, 2, 4)]
        return list(c[:3])

    def apply(self, body):
        with self.lock:
            self.posts += 1
            if body.get("on") == "t":
                self.on = not self.on
            elif "on" in body:
                self.on = bool(body["on"])
            if "bri" in body:
                self.bri = max(1, min(255, int(body["bri"])))
            if body.get("live") is False:
                self.live_until = 0.0
            segs = body.get("seg")
            for seg in ([segs] if isinstance(segs, dict) else segs or []):
                if seg.get("col"):
                    self.col = self._rgb(seg["col"][0])
                    self.leds = [list(self.col) for _ in range(self.n)]
                if "i" in seg:
                    self._individual(seg["i"])

    def _individual(self, arr):
        """WLED "i": colours from LED 0; a number sets where the next colour goes; two numbers
        and a colour fill a range [start, stop)."""
        k, pos = 0, 0
        while k < len(arr):
            e = arr[k]
            if isinstance(e, int):
                if k + 2 < len(arr) and isinstance(arr[k + 1], int):
                    for j in range(max(0, e), min(self.n, arr[k + 1])):
                        self.leds[j] = self._rgb(arr[k + 2])
                    k += 3
                    continue
                pos = e
            else:
                if 0 <= pos < self.n:
                    self.leds[pos] = self._rgb(e)
                pos += 1
            k += 1

    def realtime(self, pkt):
        """The same rules as WLED's receiver (wled00/udp.cpp, handleNotifications): at most 1472 bytes;
        byte 1 = 0 cancels realtime mode at once; the timeout is set before the pixels are looked at;
        DRGB (2) applies pixels only if the packet is longer than 4 bytes, DNRGB (4) only if longer
        than 7; a pixel needs all of its 3 bytes."""
        with self.lock:
            if len(pkt) < 2 or len(pkt) > 1472 or pkt[0] not in (2, 4):
                return
            proto, timeout = pkt[0], pkt[1]
            if timeout == 0:
                self.live_until = 0.0
                self.released += 1
                return
            if self.live_frame is None or not self.live:
                self.live_frame = [[0, 0, 0] for _ in range(self.n)]       # realtime starts black
            self.live_until = time.monotonic() + (10 ** 9 if timeout == 255 else timeout)
            self.packets += 1
            if proto == 2 and len(pkt) > 4:
                start, first = 0, 2
            elif proto == 4 and len(pkt) > 7:
                start, first = (pkt[2] << 8) | pkt[3], 4
            else:
                return
            for k, i in enumerate(range(first, len(pkt) - 2, 3)):
                if start + k < self.n:
                    self.live_frame[start + k] = list(pkt[i:i + 3])

    def shown(self):
        """What a person would see now."""
        if not self.on:
            return [[0, 0, 0]] * self.n
        return self.live_frame if self.live and self.live_frame else self.leds


def serve(base="127.0.0.21", count=1, lights=(60,), http_port=None, udp_port=None, state_file=None, quiet=True):
    http_port, udp_port = http_port or 18080, udp_port or 21325
    devices = []
    for k in range(count):
        ip = str(ipaddress.ip_address(base) + k)
        dev = Device(ip, lights[min(k, len(lights) - 1)], k + 1)
        devices.append(dev)

        class Handler(BaseHTTPRequestHandler):
            d = dev

            def log_message(self, *a):
                pass

            def _send(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/json/info":
                    self._send(self.d.info(udp_port))
                elif self.path == "/json/state":
                    self._send(self.d.state())
                else:
                    self._send({"error": 404}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path in ("/json/state", "/json"):
                    self.d.apply(body)
                    self._send({"success": True})
                    if not quiet:
                        print(f"{time.strftime('%H:%M:%S')} {self.d.ip} POST {json.dumps(body)[:100]}", flush=True)
                    if state_file:
                        dump(devices, state_file)
                else:
                    self._send({"error": 404}, 404)

        httpd = ThreadingHTTPServer((ip, http_port), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.bind((ip, udp_port))

        def udp_loop(sock=u, d=dev):
            while True:
                pkt, _ = sock.recvfrom(65535)
                d.realtime(pkt)
        threading.Thread(target=udp_loop, daemon=True).start()
    return devices


def dump(devices, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({d.ip: {"lights": d.n, "on": d.on, "bri": d.bri, "live": d.live, "posts": d.posts,
                          "packets": d.packets, "shown": ["#%02x%02x%02x" % tuple(c) for c in d.shown()]}
                   for d in devices}, f)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--base", default="127.0.0.21")
    ap.add_argument("--lights", default="60", help="lights per device, e.g. 60,150")
    ap.add_argument("--state", help="write what each device shows to this JSON file every second")
    a = ap.parse_args()
    http_port, udp_port = (int(p) for p in os.environ.get("HOUSELIGHTS_WLED_PORTS", "18080,21325").split(","))
    devices = serve(a.base, a.count, [int(x) for x in a.lights.split(",")], http_port, udp_port, a.state, quiet=False)
    print(f"{a.count} simulated WLED device(s): {', '.join(d.ip for d in devices)} (HTTP {http_port}, UDP {udp_port})",
          flush=True)
    while True:
        time.sleep(1)
        if a.state:
            dump(devices, a.state)


if __name__ == "__main__":
    main()
