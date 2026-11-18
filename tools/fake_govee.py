"""Simulated Govee LAN devices, for trying House Lights without real lights.

    python tools/fake_govee.py --count 3

Starts devices at 127.0.0.11, 127.0.0.12, ... (Linux and Windows: every 127.x address works;
on macOS use --base 127.0.0.1 --count 1). They answer unicast "scan" and "devStatus", and keep
the power, brightness and color they are sent (turn, brightness, colorwc). In the setup
wizard, scan "127.0.0.11-13" by typing the addresses, e.g. 127.0.0.11, 127.0.0.12, 127.0.0.13
(or 127.0.0.8/29).

--model takes any Govee SKU (e.g. H806A, H706B, H7060). --no-razer simulates a model that
ignores the undocumented commands: per-light streaming ("razer") and segment colors
("ptReal") are counted as ignored and change nothing.

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
import threading
import time


def _ports():
    return tuple(int(p) for p in os.environ.get("HOUSELIGHTS_GOVEE_PORTS", "4001,4002,4003").split(","))


def serve(base="127.0.0.11", count=1, model="H806A", lights=(60,), ports=None, razer=True, state_file=None,
          quiet=True, background=True):
    """Start `count` simulated devices. Returns {ip: device state dict} (updated live). With
    background=False it serves in this thread forever (the command line)."""
    scan_port, reply_port, cmd_port = ports or _ports()
    devices, socks = {}, {}
    for k in range(count):
        ip = str(ipaddress.ip_address(base) + k)
        devices[ip] = {"device": f"FA:KE:00:00:00:00:00:{k + 1:02X}", "sku": model, "onOff": 1, "brightness": 50,
                       "color": {"r": 255, "g": 160, "b": 80}, "colorTemInKelvin": 2200,
                       "lights": lights[min(k, len(lights) - 1)], "razer": razer,
                       "streaming": False, "frames": 0, "last_frame": None, "segment_packets": 0,
                       "ignored": 0, "commands": 0}
        for port in (scan_port, cmd_port):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if os.name != "nt":               # on Windows it would share the port with a second copy
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((ip, port))
            except OSError as e:
                raise OSError(f"can't use {ip}:{port} ({e}). Is another simulator running? "
                              "On macOS use --base 127.0.0.1 --count 1.") from None
            socks[s] = ip

    def say(text):
        if not quiet:
            print(text, flush=True)

    def save():
        if state_file:
            tmp = state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(devices, f, indent=1)
            os.replace(tmp, state_file)

    def reply(sock, to_ip, cmd, data):
        sock.sendto(json.dumps({"msg": {"cmd": cmd, "data": data}}).encode(), (to_ip, reply_port))

    def handle(s, last_print):
        ip = socks[s]
        d = devices[ip]
        try:
            data, (src, _) = s.recvfrom(65535)
            msg = json.loads(data)["msg"]
            cmd, body = msg["cmd"], msg.get("data") or {}
        except (ValueError, KeyError, TypeError, OSError):
            return
        d["commands"] += 1
        if cmd == "scan":
            reply(s, src, "scan", {"ip": ip, "device": d["device"], "sku": d["sku"],
                                   "bleVersionHard": "0", "bleVersionSoft": "0",
                                   "wifiVersionHard": "0", "wifiVersionSoft": "0"})
        elif cmd == "devStatus":
            reply(s, src, "devStatus", {k: d[k] for k in ("onOff", "brightness", "color", "colorTemInKelvin")})
            return                                         # status reads don't change anything
        elif cmd == "turn":
            d["onOff"] = int(body.get("value", 0))
        elif cmd == "brightness":
            d["brightness"] = int(body.get("value", 50))
        elif cmd == "colorwc":
            d["color"] = body.get("color", d["color"])
            d["colorTemInKelvin"] = int(body.get("colorTemInKelvin", 0))
        elif cmd in ("ptReal", "razer") and not razer:   # a model without these commands
            d["ignored"] += 1
            if time.time() - last_print.get(ip, 0) < 5:
                save()
                return
            last_print[ip] = time.time()
        elif cmd == "ptReal":
            d["segment_packets"] += 1
        elif cmd == "razer":
            pkt = base64.b64decode(body.get("pt", ""))
            if pkt[:6] == bytes.fromhex("bb0001b1010a"):
                d["streaming"] = True
            elif pkt[:6] == bytes.fromhex("bb0001b1000b"):
                d["streaming"] = False
            elif len(pkt) > 6 and pkt[3] == 0xB0:
                n = min(pkt[5], d["lights"])                 # a longer frame: only the real lights show
                d["frames"] += 1
                d["last_frame"] = [f"#{pkt[6 + 3 * i]:02x}{pkt[7 + 3 * i]:02x}{pkt[8 + 3 * i]:02x}" for i in range(n)]
                if time.time() - last_print.get(ip, 0) < 5:   # don't print 15 frames a second
                    save()
                    return
                last_print[ip] = time.time()
        say(f"{time.strftime('%H:%M:%S')} {ip} {cmd}{' (ignored)' if cmd in ('ptReal', 'razer') and not razer else ''} "
            f"{json.dumps(body)[:90]}")
        save()

    def loop():
        last_print = {}
        while True:
            ready, _, _ = select.select(list(socks), [], [], 1.0)
            for s in ready:
                handle(s, last_print)

    say(f"{count} simulated {model} device(s){'' if razer else ' ignoring razer/ptReal'}: {', '.join(devices)} "
        f"(ports scan {scan_port}, reply {reply_port}, command {cmd_port})")
    save()
    if not background:
        loop()
    threading.Thread(target=loop, name="fake-govee", daemon=True).start()
    return devices


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--base", default="127.0.0.11", help="address of the first device")
    ap.add_argument("--model", default="H806A", help="the Govee SKU it reports, e.g. H806A, H706B, H7060")
    ap.add_argument("--lights", default="60", help="lights on each device, e.g. 50,120,73 (a longer frame shows only these)")
    ap.add_argument("--no-razer", action="store_true",
                    help="ignore per-light streaming and segment colors, like a model without them")
    ap.add_argument("--state", help="write every device's state to this JSON file after each change")
    a = ap.parse_args()
    try:
        serve(a.base, a.count, a.model, [int(x) for x in a.lights.split(",")], razer=not a.no_razer,
              state_file=a.state, quiet=False, background=False)
    except OSError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
