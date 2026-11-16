# House Lights

A web dashboard for permanent outdoor lights (roofline/eave lights) on your home network.
Play animated themes light by light, apply static themes, schedule them by clock time or
sunrise/sunset, and design new looks in a scene editor. No cloud account, no app login: it
talks to the light controllers directly over your LAN.

- 79 themes: everyday, Diwali and Hindu festivals, Christmas, Halloween, Thanksgiving, US
  holidays, celebrations and birthdays, school spirit. Animated themes are streamed one
  colour per light.
- Quick Settings with theme tiles, a Visualization of every run, per-run Controllers, a
  Scene editor (strip and time-strip views) and Schedules.
- A setup wizard on first start: find your controllers, name each run of lights, run test
  patterns to check the light count, direction and colours, then save.
- Light and dark page themes; works on a phone.

## Supported lights

| Controller | Status |
|---|---|
| Govee Permanent Outdoor Lights Pro **H806A** | Supported and tested |
| Other Govee models with LAN control | Not yet: the wizard lists them as "not supported yet" |
| WLED (ESP32/ESP8266, open source) | Planned |

Adding a controller type means adding a driver in `houselights/drivers/` (see
`drivers/base.py` for what a driver provides).

## Requirements

- Python 3.10 or newer.
- A computer on the same network as the lights that stays on: a home server, NAS or mini
  PC. Tested on x86-64 Linux. macOS and Raspberry Pi (64-bit OS) should work, since
  everything is Python, but haven't been tested yet.
- For Govee: **LAN Control** switched on for each device in the Govee Home app.

## Install and run

```sh
git clone <this repository> houselights
cd houselights
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python -m houselights
```

Open `http://<this computer's address>:8090/`. The first time, the setup wizard opens:

1. **Lights**: pick the kind of lights you have.
2. **Controllers**: scan the network (or type addresses) and pick the controllers to use.
   If the lights are on a different subnet than this computer, type that network, like
   `192.168.2.0/24`.
3. **Runs**: name each run of lights and enter its light count.
4. **Test**: send test patterns to each run (blink, light count, direction, colours,
   segments). Tests stop by themselves after a minute; when they stop, the lights go back to
   what they showed before.
5. **Time and place**: time zone, and your location if you want sunrise/sunset schedules.
6. **Save**: the settings go to `data/config.json` and the server restarts with them.

Change the setup any time from the **Settings** tab.

Options:

```
python -m houselights [--home DIR] [--host HOST] [--port PORT] [--dry]
```

- `--home`: where settings, schedules, state and logs live (default: `data/` in this folder).
- `--dry`: practice mode. Commands are logged and nothing is sent to the lights.

To keep it running, start it from a service manager (systemd on Linux, launchd on macOS)
or a terminal multiplexer such as tmux.

## Try it without lights

`tools/fake_govee.py` simulates Govee H806A controllers on this computer (Linux):

```sh
HOUSELIGHTS_GOVEE_PORTS=14001,14002,14003 venv/bin/python tools/fake_govee.py --count 3 &
HOUSELIGHTS_GOVEE_PORTS=14001,14002,14003 venv/bin/python -m houselights --home /tmp/hl-demo --port 8094
```

In the wizard, scan `127.0.0.8/29`. The extra ports keep the simulator apart from any real
Govee devices on your network.

## Good to know

- **No login.** Anyone who can open the page can control the lights. Keep it on your home
  network; don't forward the port to the internet.
- How Govee LAN control works: JSON over UDP. Commands go to port 4003 on the device,
  discovery to port 4001 (multicast 239.255.255.250), and devices answer on port 4002.
  Animated themes use Govee's per-light streaming mode; static themes are sent as segment
  colours (5 lights per segment on H806A) and stay on the controller.
- Animated themes play only while the server runs. When it stops, the lights go back to
  their last static look.
- Your files in `data/`: `config.json` (settings), `schedules.json`, `state.json` (what was
  last applied: controllers can't report segment colours), `logs/`.

## Tests

No lights or network needed:

```sh
venv/bin/python tests/test_settings.py
venv/bin/python tests/test_schedule.py
```

## License

MIT, see `LICENSE`. This project is not affiliated with or endorsed by Govee.
