"""Simulated Govee LAN devices, for trying House Lights without real lights.

    python tools/fake_govee.py --count 3

Starts devices at 127.0.0.11, 127.0.0.12, ... (Linux: every 127.x address works; on macOS
use --base 127.0.0.1 --count 1). They answer unicast "scan" and "devStatus", and keep the
power, brightness and colour they are sent. In the setup wizard, scan "127.0.0.11-13" by
typing the addresses, e.g. 127.0.0.11, 127.0.0.12, 127.0.0.13 (or 127.0.0.8/29).

Real devices use ports 4001 (scan), 4002 (replies) and 4003 (commands). To run beside real
devices or another program using those ports, move both sides to other ports:

    HOUSELIGHTS_GOVEE_PORTS=14001,14002,14003 python tools/fake_govee.py
    HOUSELIGHTS_GOVEE_PORTS=14001,14002,14003 python -m houselights
"""
import argparse
import base64
import ipaddress
import json
import os
import select
import socket
import sys
import time


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--base", default="127.0.0.11", help="address of the first device")
    ap.add_argument("--model", default="H806A")
    ap.add_argument("--lights", default="60", help="lights on each device, e.g. 50,120,73 (a longer frame shows only these)")
    ap.add_argument("--state", help="write every device's state to this JSON file after each change")
    a = ap.parse_args()
    scan_port, reply_port, cmd_port = (int(p) for p in os.environ.get("HOUSELIGHTS_GOVEE_PORTS", "4001,4002,4003").split(","))

    counts = [int(x) for x in a.lights.split(",")]
    devices, socks = {}, {}
    for k in range(a.count):
        ip = str(ipaddress.ip_address(a.base) + k)
        devices[ip] = {"device": f"FA:KE:00:00:00:00:00:{k + 1:02X}", "sku": a.model, "onOff": 1, "brightness": 50,
                       "color": {"r": 255, "g": 160, "b": 80}, "colorTemInKelvin": 2200,
                       "lights": counts[min(k, len(counts) - 1)],
                       "streaming": False, "frames": 0, "last_frame": None, "segment_packets": 0, "commands": 0}
        for port in (scan_port, cmd_port):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if os.name != "nt":               # on Windows it would share the port with a second copy
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((ip, port))
            except OSError as e:
                sys.exit(f"can't use {ip}:{port} ({e}). Is another simulator running? "
                         "On macOS use --base 127.0.0.1 --count 1.")
            socks[s] = ip
    print(f"{a.count} simulated {a.model} device(s): {', '.join(devices)} "
          f"(ports scan {scan_port}, reply {reply_port}, command {cmd_port})", flush=True)

    def save():
        if a.state:
            tmp = a.state + ".tmp"
            with open(tmp, "w") as f:
                json.dump(devices, f, indent=1)
            os.replace(tmp, a.state)

    def reply(sock, to_ip, cmd, data):
        sock.sendto(json.dumps({"msg": {"cmd": cmd, "data": data}}).encode(), (to_ip, reply_port))

    save()
    last_print = {}
    while True:
        ready, _, _ = select.select(list(socks), [], [], 1.0)
        for s in ready:
            ip = socks[s]
            d = devices[ip]
            try:
                data, (src, _) = s.recvfrom(65535)
                msg = json.loads(data)["msg"]
                cmd, body = msg["cmd"], msg.get("data") or {}
            except (ValueError, KeyError, TypeError, OSError):
                continue
            d["commands"] += 1
            if cmd == "scan":
                reply(s, src, "scan", {"ip": ip, "device": d["device"], "sku": d["sku"],
                                       "bleVersionHard": "0", "bleVersionSoft": "0",
                                       "wifiVersionHard": "0", "wifiVersionSoft": "0"})
            elif cmd == "devStatus":
                reply(s, src, "devStatus", {k: d[k] for k in ("onOff", "brightness", "color", "colorTemInKelvin")})
                continue                                   # status reads don't change anything
            elif cmd == "turn":
                d["onOff"] = int(body.get("value", 0))
            elif cmd == "brightness":
                d["brightness"] = int(body.get("value", 50))
            elif cmd == "colorwc":
                d["color"] = body.get("color", d["color"])
                d["colorTemInKelvin"] = int(body.get("colorTemInKelvin", 0))
            elif cmd == "ptReal":
                d["segment_packets"] += 1
            elif cmd == "razer":
                pkt = base64.b64decode(body.get("pt", ""))
                if pkt[:6] == bytes.fromhex("bb0001b1010a"):
                    d["streaming"] = True
                elif pkt[:6] == bytes.fromhex("bb0001b1000b"):
                    d["streaming"] = False
                elif len(pkt) > 6 and pkt[3] == 0xB0:
                    n = min(pkt[5], d["lights"])             # a longer frame: only the real lights show
                    d["frames"] += 1
                    d["last_frame"] = [f"#{pkt[6 + 3 * i]:02x}{pkt[7 + 3 * i]:02x}{pkt[8 + 3 * i]:02x}" for i in range(n)]
                    if time.time() - last_print.get(ip, 0) < 5:   # don't print 15 frames a second
                        save()
                        continue
                    last_print[ip] = time.time()
            print(f"{time.strftime('%H:%M:%S')} {ip} {cmd} {json.dumps(body)[:90]}", flush=True)
            save()


if __name__ == "__main__":
    main()
