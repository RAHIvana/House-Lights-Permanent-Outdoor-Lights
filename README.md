# House Lights

A web dashboard for permanent outdoor lights (roofline and eave lights), run on a computer in
your home. Play animated themes light by light, apply static themes, schedule them by clock
time or sunrise/sunset, and design new looks in a scene editor. No cloud account and no app
login: it talks to the light controllers directly over your home network.

- 79 themes: everyday, Diwali and Hindu festivals, Christmas, Halloween, Thanksgiving, US
  holidays, celebrations and birthdays, school spirit.
- Quick Settings with theme tiles, a Visualization of every run, a panel per run, a Scene
  editor and Schedules. Light and dark page themes; works on a phone.
- A setup wizard on first start: it finds your controllers, helps you count the lights,
  plays test patterns, and saves your settings.

## Supported controllers

| Controller | What works | Tested with real hardware? |
|---|---|---|
| **Govee** Permanent Outdoor Lights Pro **H806A** | Everything: animated themes light by light, static themes, colours, schedules | **Yes** |
| **WLED**: the open-source controller firmware (ESP8266/ESP32), also on some brand-name kits | Everything: animated themes light by light, static themes, colours, schedules | Not yet: tested against a simulator built from the WLED documentation |
| **JellyFish Lighting** | Static themes (up to 30 colours per pattern: exact for banded themes, rounded otherwise), colours, on/off, brightness, schedules. Animated themes show as a still picture | Not yet: simulator built from JellyFish's API documentation |
| **Tuya / Smart Life**: the app platform behind many Amazon brands, e.g. most ASAHOM kits | One colour at a time: colours, warm white, on/off, brightness, schedules. Themes show their main colour | Not yet: tested with a stand-in for the tinytuya library |

If you try one of the untested kinds, please report what works and what doesn't.

### Which one is my brand?

Look at the app your lights use:

| Your lights use | Brands (examples) | Pick in the wizard |
|---|---|---|
| **Govee Home** app | Govee | Govee |
| **Smart Life** or **Tuya Smart** app | Most **ASAHOM** kits, and many other Amazon permanent-light brands | Tuya / Smart Life |
| **WLED** app, or a WLED page when you open the controller's address in a browser | DIY and open-source controllers, controllers sold "with WLED", **ASAHOM Pro** models sold as having WLED. Some owners of other brands swap in a WLED controller | WLED |
| **JellyFish** app | JellyFish Lighting | JellyFish |
| Another app (Gemstone, Oelo, Trimlight, Eufy, Nanoleaf, Lumary, ...) | | Not supported yet: no local API we could use, or not checked yet |

WLED is the most capable choice: every light can have its own colour, and animated themes
play smoothly. Tuya / Smart Life lights take one colour at a time.

## Install

You need **Python 3.10 or newer** and about 50 MB of disk. Everything is Python; nothing to
compile.

**Linux** (Ubuntu, Debian, Raspberry Pi OS 64-bit):

```sh
sudo apt install python3 python3-venv git
git clone https://github.com/RAHIvana/Permanent-Outdoor-Liight-Controller.git houselights
cd houselights
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

**macOS**: install Python from [python.org](https://www.python.org/downloads/) or with
Homebrew (`brew install python`), then the same `git clone`, `python3 -m venv venv` and
`venv/bin/pip install -r requirements.txt`.

**Windows** (PowerShell): install Python from [python.org](https://www.python.org/downloads/)
and tick "Add python.exe to PATH". Then:

```powershell
git clone https://github.com/RAHIvana/Permanent-Outdoor-Liight-Controller.git houselights
cd houselights
py -m venv venv
venv\Scripts\pip install -r requirements.txt
```

**Tuya / Smart Life lights only**: also install `tinytuya`:

```sh
venv/bin/pip install tinytuya          # Windows: venv\Scripts\pip install tinytuya
```

Tested on x86-64 Linux, and on Windows 11 with the simulators (below). macOS and Raspberry Pi
(64-bit OS) should work the same way but haven't been tested yet. On a Raspberry Pi use the
64-bit OS: on the 32-bit one, pip may have to compile a dependency.

## Start the dashboard

```sh
venv/bin/python -m houselights          # Windows: venv\Scripts\python -m houselights
```

Then open **http://localhost:8090/** on this computer, or **http://ADDRESS:8090/** from a
phone or another computer, where ADDRESS is this computer's address (`hostname -I` on Linux,
`ipconfig getifaddr en0` on macOS, `ipconfig` on Windows). Stop it with Ctrl+C.

**Windows firewall**: the first time, Windows asks whether Python may communicate on your
networks. Allow it on **Private networks**. Without that, phones and other computers can't
open the page, and messages that controllers send back on their own can be blocked: Govee
answers on UDP port 4002 and Tuya devices announce themselves by broadcast, so their scans and
Govee's status may come up empty. Your home network should be set to Private in Windows
(Settings > Network & internet > your Wi-Fi or Ethernet > Network profile type). If you
dismissed the question, allow `python.exe` under Windows Security > Firewall & network
protection > Allow an app through firewall.

Options:

```
python -m houselights [--home DIR] [--host HOST] [--port PORT] [--dry]
```

- `--home DIR`: where settings, schedules and logs are kept (default: `data/` in this folder).
- `--port PORT`: another port if 8090 is taken.
- `--dry`: practice mode. Commands are logged and nothing is sent to the lights.

## The setup wizard

The first time you open the page there are no settings yet, so the setup wizard opens. You
can run it again later from the **Settings** tab (**Change setup**).

1. **Lights**: tick every kind of controller you have. You can mix them.
2. **Controllers**: press **Scan**. It asks controllers on your network to identify
   themselves and changes nothing. Tick the ones to use. If your lights are on another
   network or subnet than this computer, type that network (like `192.168.2.0/24`) or the
   controllers' addresses before scanning. You can also add a controller by its address.
   A JellyFish controller shows one line per zone; each zone becomes its own run.
3. **Runs**: name each run of lights. WLED and JellyFish report their light counts. For
   Govee, use the count from the Govee Home app or count it in the next step.
4. **Test**: show test patterns on each run to check it:
   - **Blink**: which run is this?
   - **Count the lights** (Govee): first every segment's first light lights up red or green,
     and you type how many of those markers you see. Then the last segment lights up red,
     and you type how many red lights you see. The wizard works out the count.
   - **Check the count**: light 1 red, the last light blue. If blue isn't the very last
     light, the count is wrong.
   - **Direction**: a dot runs from light 1. Tick **Reverse** if themes should run the other
     way.
   - **Colours**, **Segment groups**.

   Tests stop by themselves after a minute. Govee and WLED go back to what they showed; Tuya
   lights are saved before the test and put back afterwards. JellyFish can't report what it
   showed, so after testing pick a theme or use the JellyFish app.
5. **Time and place**: your time zone, and your location if you want sunrise/sunset
   schedules (two decimals is enough).
6. **Save**: settings go to `data/config.json` and the server restarts with them.

## Getting each kind of controller ready

**Govee**: in the Govee Home app, open each device's settings and switch on **LAN
Control**. Discovery uses UDP ports 4001 to 4003; another program listening on port 4002
(for example a Govee integration in Home Assistant) can take the replies, so stop it while
scanning. (On Windows the scan then says the port is in use.)

**WLED**: nothing to do beyond having WLED on your network. Animated themes use WLED's UDP
realtime protocol on port 21324; in WLED's *Sync Interfaces* settings, make sure **Receive
UDP realtime** is ticked.

**JellyFish**: the controller must be reachable on your network (it listens on port 9000).
Set up the zones in the JellyFish app first.

**Tuya / Smart Life**: local control needs each device's **local key**, which comes from
Tuya's cloud once. Install tinytuya (above), pair the lights in the Smart Life app, create a
free developer account at iot.tuya.com with a cloud project linked to your app account, then
run `venv/bin/python -m tinytuya wizard` (Windows: `venv\Scripts\python -m tinytuya wizard`).
It lists every device with its id and local key.
The tinytuya README has the step-by-step guide. Tuya devices accept one connection at a time,
so close the Smart Life app while testing. The key is stored in `data/secrets.json`, readable
only by you, never in `config.json` and never sent to the web page.

## Try it without lights

Simulators for Govee, WLED and JellyFish run on this computer (Linux and Windows; on macOS
add `--base 127.0.0.1 --count 1`):

```sh
export HOUSELIGHTS_GOVEE_PORTS=14001,14002,14003 HOUSELIGHTS_WLED_PORTS=18080,21325 HOUSELIGHTS_JELLYFISH_PORT=19000
venv/bin/python tools/fake_govee.py --count 1 --lights 50 &
venv/bin/python tools/fake_wled.py --count 1 --lights 150 &
venv/bin/python tools/fake_jellyfish.py --zones Front:120,Back:45 &
venv/bin/python -m houselights --home /tmp/hl-demo --port 8094
```

Windows (PowerShell; each simulator opens its own window, close it to stop it):

```powershell
$env:HOUSELIGHTS_GOVEE_PORTS="14001,14002,14003"; $env:HOUSELIGHTS_WLED_PORTS="18080,21325"; $env:HOUSELIGHTS_JELLYFISH_PORT="19000"
Start-Process venv\Scripts\python "tools\fake_govee.py --count 1 --lights 50"
Start-Process venv\Scripts\python "tools\fake_wled.py --count 1 --lights 150"
Start-Process venv\Scripts\python "tools\fake_jellyfish.py --zones Front:120,Back:45"
venv\Scripts\python -m houselights --home $env:TEMP\hl-demo --port 8094
```

The `$env:` settings last until you close that PowerShell window.

In the wizard, tick Govee, WLED and JellyFish and scan `127.0.0.11, 127.0.0.21, 127.0.0.31`.
The extra ports keep the simulators apart from real controllers.

## Keep it running

Run it from a terminal multiplexer (tmux, screen), or as a service. A systemd example for
Linux (`/etc/systemd/system/houselights.service`; change the user and paths):

```ini
[Unit]
Description=House Lights
After=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/houselights
ExecStart=/home/pi/houselights/venv/bin/python -m houselights
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl enable --now houselights`. Animated themes play only while the server
runs; when it stops, the lights go back to their last static look.

On Windows, leave the PowerShell window open (minimised is fine). When the wizard saves, the
server restarts inside that same window, and Ctrl+C still stops it.

## Good to know

- **No login.** Anyone who can open the page can control the lights. Keep it on your home
  network and don't forward the port to the internet.
- Your files in `data/`: `config.json` (settings), `secrets.json` (Tuya keys, if any),
  `schedules.json`, `state.json` (what was last applied) and `logs/`. Back up this folder to
  keep your setup.
- To update: `git pull`, then `venv/bin/pip install -r requirements.txt` (Windows:
  `venv\Scripts\pip install -r requirements.txt`), then restart.

## Tests

No lights needed:

```sh
venv/bin/python tests/test_settings.py
venv/bin/python tests/test_schedule.py
venv/bin/python tests/test_drivers.py      # Linux and Windows: uses 127.0.0.x addresses
```

On Windows use `venv\Scripts\python tests\test_settings.py` and so on.

## Adding another kind of controller

Each kind is a driver in `houselights/drivers/`. `base.py` describes what a driver provides
and its capabilities (per-light streaming, static frames or segments, status, how the light
count is found); the setup wizard and the dashboard adapt to them.

## License

MIT, see `LICENSE`. This project is not affiliated with or endorsed by Govee, WLED,
JellyFish Lighting or Tuya.
