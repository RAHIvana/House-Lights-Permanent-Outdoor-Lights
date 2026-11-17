# Writing a controller driver

A **driver** is how House Lights talks to one kind of light controller. Everything above the
drivers (the dashboard, themes, schedules, the setup wizard) is the same for every kind; a
driver only has to find controllers, say what they can do, and carry out a handful of commands.

| Driver | Controllers | How it talks | Tested on real hardware |
|---|---|---|---|
| `govee.py` | Govee Wi-Fi lights with LAN Control | UDP: scan on 4001, replies on 4002, commands on 4003 | Yes (H806A) |
| `wled.py` | Controllers running WLED | HTTP JSON API, and UDP realtime (DNRGB) for animation | Simulator only |
| `jellyfish.py` | JellyFish Lighting | WebSocket on port 9000 | Simulator only |
| `tuya.py` | Tuya / Smart Life | the `tinytuya` package, one colour at a time | Stand-in only |

`base.py` holds the `Kit` base class and the capability keys, `net.py` the shared network helpers,
and `__init__.py` the registry. How the setup wizard uses a driver is in
[light-discovery.md](../../docs/light-discovery.md); notes on what Govee really does are in
[govee-lan-notes.md](../../docs/govee-lan-notes.md).

## What a driver is made of

A driver is one module in this folder with these names:

| Name | What it is |
|---|---|
| `LABEL`, `NOTE`, `TESTED` | Shown in the setup wizard: the kind's name, a line on how to get it ready, and whether it has been seen working on real hardware (`False` until it has) |
| `MODELS` | `{model: {"label", "lights_per_segment", "max_lights"}}`: the models it knows by name |
| `available()` | `(ok, reason)`: `(False, "install tinytuya")` when an optional package is missing |
| `options(c, secret)` | Checks the driver's own settings for one controller and returns `(opts, secret)` |
| `discover(targets, deep, expect, known)` | Finds controllers on the network; returns scan rows |
| `probe(info)` | Checks one controller at an address; returns scan rows |
| `read_status(kits)` | Asks controllers for their state; returns `{controller id: status or None}` |
| `Kit` | The class with the commands (below) and `Kit.CAPS` |
| *optional:* `model_info(model)`, `TIERS`, `MODELS_NOTE` | For kinds where models differ a lot (Govee) |

### `options(c, secret)`

`c` is the controller as the wizard or `config.json` has it: `type`, `model`, `ip`, plus any extra
fields of this kind (`zone`, `device_id`, `version`, `local_key`...). `secret` is what was saved for
this controller before. Check the fields and return:

- `opts`: what is saved on the controller in `config.json` (`{"zone": "Zone1"}`),
- `secret`: what must not be in `config.json` (`{"local_key": "..."}`). It goes to `secrets.json`
  (readable only by the owner) and **is never sent to the web page**.

Raise `ValueError("a message a person can act on")` for bad input; the wizard shows it. Drivers with
nothing to add return `({}, {})`.

### `discover(targets, deep, expect, known)`

- `targets` is the text typed in **Where to look** (`"192.168.2.0/24, 192.168.2.7"`), or `""` for "this
  network". Turn it into addresses with `govee.expand_targets(targets)`: it checks the format and
  accepts **home addresses only**, at most 1024. WLED and JellyFish use it, so should you.
- `deep` means "try harder" (longer waits, more rounds).
- `known` is a list of addresses already found: skip them. `expect` is how many controllers of this
  kind the user said they have: stop early once you have that many (counting `known`).
- Return a list of scan rows (below), sorted by address. Raise `ValueError` for a problem the user can
  fix (shown on this kind's card) and let an `OSError` through for "could not scan the network".
- Never send anything that changes a light. Scanning is only "who are you?".

### `probe(info)`

The **Add by address** button asks the drivers at once with `probe({"ip": ip})`, so `probe` must work
with an address alone. (Tuya is the exception: it cannot be asked without its key, so there the wizard only
checks that the port answers.) Return the scan rows for that address, or raise `ValueError` ("no X device
answered at ...") when nothing of your kind is there. Other fields the user typed arrive in `info` too
(`zone`, `device_id`, `local_key`...).

### Scan rows

| Field | Meaning |
|---|---|
| `ip`, `type` | Address and the driver's name in `DRIVERS` |
| `model` | A key of `MODELS`, or a model your `model_info()` accepts |
| `label` | Text for the list ("Govee H806A", "WLED 0.14.0 · Garage") |
| `supported` | `False` shows the row as "not supported yet" and it cannot be ticked |
| `lights` | The light count if the controller can say so, else `None` (the wizard then counts) |
| `device_tail` | The last five characters of an id or MAC, so people can tell identical boxes apart |
| `zone` | When one address has several lights (JellyFish zones): one row per zone |
| `tier` | For kinds with tiers, the model's tier |
| *driver specific* | `device_id`, `version`, `needs_key` for Tuya, and so on |

### Status

`read_status(kits)` gets the `Kit`s of this driver and returns a dict for every one:

```python
{"onOff": 1, "brightness": 50, "color": {"r": 255, "g": 140, "b": 0}, "colorTemInKelvin": 0}
```

`onOff` is 0 or 1, `brightness` is 1 to 100, `colorTemInKelvin` is 0 when the light shows a colour.
Use `None` for a controller that did not answer. The dashboard asks every 15 seconds, so ask all
controllers **at once** (`net.probe_many`) and keep the timeout short. A driver that cannot report
state sets `status: False` in its caps and returns `None` for everything.

## The `Kit` class

One `Kit` is one controller. The app makes it with `Kit(controller, live)`: `controller` is a
`settings.Controller` (`id`, `type`, `model`, `ip`, `name`, `enabled`, `options`, `secret`) and `live`
is `False` in practice mode (`--dry`).

| Method | When it is called | Notes |
|---|---|---|
| `power(on)` | On, Off, schedules, before streaming | Take `self.lock` |
| `brightness(value)` | The brightness slider | A percentage, 1 to 100 |
| `color(rgb)` | One colour on the whole controller | `rgb` is `(r, g, b)`, 0 to 255 |
| `kelvin(k)` | White by temperature, like 2200 K | Without a white channel use `net.kelvin_to_rgb(k)` |
| `segments(segs, rgb, nseg)` | A static theme, one call per colour | Segment numbers start at 0; `nseg` is the run's segment count. **The caller holds `self.lock`.** Raise `ValueError` if segments are not supported. |
| `show_lights(colors)` | A static theme on a controller that takes a whole frame (`static` "lights" or "palette") | One colour per light. **The caller holds `self.lock`.** |
| `preview_static(colors)` | The page's picture of what `show_lights` will show | Return `colors` unchanged unless you approximate (JellyFish: 30 colour blocks) |
| `stream_begin()` / `stream_frame(colors)` / `stream_end()` | Animated themes (see below) | Called from the streaming thread |
| `snapshot()` / `restore(snap)` | Around wizard tests, when `restore` is `"snapshot"` | Save what the controller shows; put it back |

Rules that every driver follows (they are what make practice mode and disabled controllers safe):

- **Call `self.guard()` before anything that sends.** It raises `NotAllowed` for a disabled controller.
- **When `self.live` is false, log and send nothing.** Reading (status) is still allowed. Log lines
  start with `self.prefix` and `self.tag` (`LIVE sim_front(127.0.0.11) ...` or `DRY ...`).
- **One command at a time per controller:** take `self.lock` in the commands that you implement yourself.
- Never put a secret in a log line.
- Raise `ValueError` for a request the controller cannot do, and `OSError` for a network problem.

## Capabilities (CAPS)

`Kit.CAPS` (or the `caps` of a model, below) tells the dashboard and the wizard what the controller can
do. Ask `drivers.model_caps(kind, model)` or `kit.caps` for one controller, not `Kit.CAPS`.

| Key | Values | What changes |
|---|---|---|
| `stream` | `True` / `False` | **Per-light frames many times a second.** `True`: animated themes and "Play live" work, and the wizard can show single lights. `False`: animated themes show as a still picture (or the theme's main colour). |
| `static` | `"segments"`, `"lights"`, `"palette"` | **How a static theme is sent.** `"segments"`: rounded to one colour per segment, then one `segments()` call per colour. `"lights"`: one `show_lights()` call with a colour for every light. `"palette"`: like `"lights"` but approximate (limited colour blocks); implement `preview_static`. |
| `pick` | `True` / `False` | Segments can be picked and coloured one by one on the page |
| `status` | `True` / `False` | The controller reports power, brightness and colour |
| `count` | `"manual"`, `"reported"`, `"display"` | Where the light count comes from: the wizard counts with test patterns / the controller says / it is typed and only used to draw the run |
| `restore` | `"auto"`, `"snapshot"`, `"none"` | After a wizard test: the controller goes back by itself / we save and restore it with `snapshot()` and `restore()` / it cannot (the wizard says so) |
| `stream_untested` | optional `True` | Streaming is allowed but not yet seen working on this model: the page says "try it" |
| `frame` | optional `"stretch"` | A frame of N colours is spread over the whole run in N equal parts (Govee). The wizard then counts with segment colours instead of frames. |

Two ready-made sets in `base.py`: `ONE_COLOUR_CAPS` (one colour at a time, state reported, saved and
restored; Tuya and basic Govee models) and the default `Kit.CAPS`.

Which wizard tests a controller gets follows from its caps (`allowed_tests` in `setup.py`):

| Caps | Tests offered |
|---|---|
| `stream` and `frame: "stretch"` and `pick` (Govee full) | `identify`, `seg4`, `seglast`, `ends`, `ruler`, `chase`, `rgb`, `segments` |
| `stream` and `frame: "stretch"`, no `pick` (Govee try) | `identify`, `ends`, `ruler`, `chase`, `rgb` |
| `stream`, no `frame`, `count` not `"manual"` (WLED) | `identify`, `check`, `ruler`, `chase`, `rgb`, `segments` |
| `stream`, no `frame`, `count: "manual"` | the above plus the marker counting tests `markers`, `tail` |
| no `stream`, `static` "lights" or "palette" (JellyFish) | `identify`, `rgb` |
| no `stream`, `static: "segments"` (Tuya, basic Govee) | `identify` |

## Models and tiers

`MODELS` lists the models by name. `lights_per_segment` is how many lights one segment colours,
counted from light 1 (`5` on Govee H806A, `1` when every light is its own, `0` when the whole run is
one colour). `max_lights` is the most a run can have (a streaming frame carries at most
`Kit.max_stream_lights`, 255 by default). `drivers.model_info(kind, model)` turns an entry into
`{model, label, tier, caps, max_lights, lights_per_segment, note}`; without tiers the tier is `None`
and the caps are `Kit.CAPS`.

When models of one kind differ, implement `model_info(model)` yourself, as Govee does, and give the
kit a `caps` property that returns the model's caps. Govee has three tiers:

| Tier | Models | What works |
|---|---|---|
| `full` | H806A | Everything: light by light, segment colours. Tested on real controllers. |
| `try` | H705, H706, H707, H805, H3A5x families | On, off, brightness, colours, schedules; light by light is allowed but untested |
| `basic` | Any other SKU-shaped model | One colour at a time |

Add `MODELS_NOTE` (which models are in which tier) and `TIERS` (label, note, caps per tier) and the
wizard shows them.

## What the app does with your driver

- **Applying a static theme.** The theme is rendered to one colour per light. With one colour
  everywhere the app calls `color()`. Otherwise, `static: "segments"` rounds it to one colour per
  segment (the most common colour of the segment's lights) and calls `segments()` once per colour while
  holding `kit.lock`; `"lights"` and `"palette"` call `preview_static()` then `show_lights()` once.
- **Playing an animated theme** (`stream: True`). Power on, then a thread: `stream_begin()`, a 0.3
  second pause, then `stream_frame(colors)` at `stream_fps` frames a second (15 by default), then
  `stream_end()` when it stops or fails. `colors` is a list of `(r, g, b)` integers, 0 to 255, already
  scaled by the brightness level. Asking for more lights than `max_stream_lights` is refused. Any direct
  command (colour, power) takes the controller out of streaming first, so `stream_end()` must leave it
  in a normal state.
- **Status.** `read_status` every 15 seconds while the page is open.
- **Wizard tests.** Streaming controllers get test frames through the same `stream_*` methods.
  Controllers that cannot stream get the frames as `show_lights()` (or the main colour with `color()`)
  at most `slow_fps` times a second; when `restore` is `"snapshot"`, `snapshot()` is called before and
  `restore()` after.

## Shared helpers (`net.py`)

| Helper | What it does |
|---|---|
| `http_json(url, body=None, timeout=3.0)` | GET, or POST with a JSON body when `body` is given; returns the parsed JSON (`{}` for an empty answer) |
| `ws_exchange(host, port, path, messages, reply=True, timeout=3.0)` | A small WebSocket client: sends each message and returns the first reply parsed as JSON |
| `probe_many(fn, ips, workers=64)` | Runs `fn(ip)` for every address at once; returns `{ip: result}` for those that did not raise and did not return `None` |
| `local_networks()` | This computer's own /24 network, for scans with nothing typed |
| `is_home_address(ip)`, `HOME_ADDRESSES` | Whether an address is on your own network (192.168.x.x, 10.x.x.x, 172.16 to 172.31.x.x, loopback, link-local) |
| `kelvin_to_rgb(k)` | A rough colour for white at `k` kelvin |
| `govee.expand_targets(text, limit=1024)` | Typed targets to a list of addresses, home addresses only |

## A minimal driver

A made-up HTTP controller that shows one colour at a time. Enough to see the shape; real ones need more
care around timeouts and errors.

```python
"""Acme lights: a made-up HTTP controller, as an example."""
import logging
import socket

from . import net
from .base import ONE_COLOUR_CAPS, Kit as BaseKit

log = logging.getLogger("houselights")

LABEL = "Acme lights (one colour at a time)"
NOTE = "Switch on the local API in the Acme app first."
TESTED = False                                  # True only after it worked on real hardware
MODELS = {"Acme strip": {"label": "Acme light strip", "lights_per_segment": 0, "max_lights": 2000}}


def available():
    return True, ""


def options(c, secret):
    return {}, {}


def _row(ip, info):
    return {"ip": ip, "type": "acme", "model": "Acme strip", "supported": True,
            "label": f"Acme {info.get('name', '')}".strip(), "device_tail": str(info.get("id", ""))[-5:],
            "lights": info.get("pixels")}


def _info(ip, timeout):
    return net.http_json(f"http://{ip}/info", timeout=timeout)


def discover(targets="", deep=False, expect=0, known=()):
    from .govee import expand_targets          # home addresses only
    ips = expand_targets(targets) if str(targets or "").strip() else expand_targets(",".join(net.local_networks()))
    ips = [ip for ip in ips if ip not in set(known)]
    found = net.probe_many(lambda ip: _info(ip, 4.0 if deep else 1.0), ips)
    return [_row(ip, i) for ip, i in sorted(found.items(), key=lambda kv: socket.inet_aton(kv[0]))]


def probe(info):
    ip = str(info.get("ip", "")).strip()
    try:
        return [_row(ip, _info(ip, 2.0))]
    except Exception as e:
        raise ValueError(f"no Acme controller answered at {ip} ({type(e).__name__})") from None


def _status_one(ip):
    s = net.http_json(f"http://{ip}/state", timeout=1.5)
    return {"onOff": 1 if s["on"] else 0, "brightness": s["bri"], "color": dict(zip("rgb", s["rgb"])),
            "colorTemInKelvin": 0}


def read_status(kits):
    got = net.probe_many(_status_one, sorted({k.c.ip for k in kits}), workers=16)
    return {k.c.id: got.get(k.c.ip) for k in kits}


class Kit(BaseKit):
    CAPS = dict(ONE_COLOUR_CAPS)                # one colour at a time, state reported, saved and put back

    def _send(self, body, what):
        self.guard()                            # a disabled controller gets nothing
        log.info("%s %s Acme %s", self.prefix, self.tag, what)
        if self.live:                           # practice mode only logs
            net.http_json(f"http://{self.c.ip}/set", body, timeout=3.0)

    def power(self, on):
        with self.lock:
            self._send({"on": bool(on)}, "power")

    def brightness(self, value):
        with self.lock:
            self._send({"bri": int(value)}, f"brightness {value}")

    def color(self, rgb):
        with self.lock:
            self._send({"on": True, "rgb": list(rgb[:3])}, f"colour {tuple(rgb[:3])}")

    def kelvin(self, k):
        self.color(net.kelvin_to_rgb(k))

    def snapshot(self):
        return read_status([self]).get(self.c.id)

    def restore(self, snap):
        if snap:
            c = snap["color"]
            self.color((c["r"], c["g"], c["b"]))
            self.brightness(snap["brightness"])
            self.power(bool(snap["onOff"]))
```

## Adding a driver: the checklist

1. **Write the module** `houselights/drivers/<kind>.py` as above, with a `Kit` subclass and caps that tell
   the truth (a driver that claims `stream` must deliver frames the controller shows light by light).
2. **Register it** in `drivers/__init__.py`: import the module and add it to `DRIVERS`.
3. **Teach the wizard its name.** In `houselights/setup.py` add the kind to `IDENTIFY` (the **Add by
   address** check: `"<kind>": _ask("<kind>")`) and to `_what()` (the sentence "192.168.2.50 is a ..."). In
   `houselights/static/setup.js` add it to `KINDS`, `KIND_NAME` and `HELP` (how to recognise the kind and
   how to get it ready), and give its badge a colour (`.badge.k-<kind>`) in `static/setup.css`.
4. **Write a simulator** in `tools/fake_<kind>.py` that answers like the real controller, on
   `127.0.0.x` addresses. Let the driver move its ports with an environment variable
   (`HOUSELIGHTS_GOVEE_PORTS`, `HOUSELIGHTS_WLED_PORTS`, `HOUSELIGHTS_JELLYFISH_PORT` are the examples) so a
   simulator can run beside real controllers.
5. **Add tests** to `tests/test_drivers.py`: start the simulator, then check discovery, `probe`, each
   command and (if it streams) a few frames. Libraries that need hardware get a stand-in, as `FakeBulb`
   does for tinytuya.
6. **Update the README:** the "Supported controllers" table (keep **Tested with real hardware?** at "Not
   yet" until someone has run it on the real thing), "Which one is my brand?", and "Getting each kind of
   controller ready".
7. **Run everything** with `--dry` and the simulator first: `python -m houselights --dry`, then the
   wizard with the simulator's addresses typed into **Where to look**.
8. **Ask for a controller report** from someone with the hardware (the "My controller works / doesn't"
   issue form). Set `TESTED = True` and update the README only after that.

## Things learned the hard way

- **Govee drops UDP messages.** Send what matters twice, and scan by asking again (only the addresses
  that have not answered). Sending "start streaming" again in the middle of a stream makes the lights
  flash, so send it only at the start. A stream frame of N colours is stretched over the whole run, so
  count with segment commands, not frames ([govee-lan-notes.md](../../docs/govee-lan-notes.md)).
- **WLED ignores per-light colours that arrive together with `"on"`**: turn it on first, then send
  the colours. Its realtime mode ends by itself about 2 seconds after the last frame, so `stream_end()`
  has nothing to do.
- **Tuya devices take one connection at a time**, so close the Smart Life app while testing.
- **JellyFish cannot report what a zone shows** (`status: False`, `restore: "none"`) and holds at most 30
  colour blocks in a pattern, so its static themes are approximations: implement `preview_static`.
- **Windows and UDP ports.** Do not set `SO_REUSEADDR` on a listening UDP socket there: the bind then
  succeeds beside another program already on the port, and that program keeps getting every reply.
  Without it the bind fails and says why.
- **Only home addresses.** House Lights has no login. Scans, **Add by address** and saved controllers are
  limited to your own network, and drivers must use `expand_targets` for typed addresses.
- **Secrets stay in `secrets.json`**: never in `config.json`, never in a log line, never in a row sent to the
  page (the user's typed key goes the other way only).
- **No real addresses, names, device ids or keys in the repository**, tests and examples included
  (examples use `192.168.2.x`).
