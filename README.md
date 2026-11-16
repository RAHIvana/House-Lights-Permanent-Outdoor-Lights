# House Lights

A web dashboard for permanent outdoor lights (roofline and eave lights), run on a computer in
your home. It works with **Govee**, **JellyFish**, **ASAHOM** and other brands that use the
Smart Life / Tuya app, and open-source **WLED** controllers (see
[Supported controllers](#supported-controllers)). Play animated themes light by light, apply
static themes, schedule them by clock time or sunrise/sunset, and make your own themes. No
cloud account and no app login: it talks to the light controllers directly over your home
network.

Run it on a computer you already have (**Windows**, **Mac** or Linux) or on a
**Raspberry Pi 3 or newer**, on the same home network as the lights. Leave it running for
schedules to work; any phone or computer on that network can open the dashboard.

- 79 built-in themes: everyday, Diwali and Hindu festivals, Christmas, Halloween,
  Thanksgiving, US holidays, celebrations and birthdays, school spirit.
- Quick Settings with theme tiles, a Visualization of every run, a panel per run, a Themes tab
  to make your own, and Schedules. Light and dark page themes; works on a phone.
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
(3 or newer, 64-bit OS) should work the same way but haven't been tested yet. On a Raspberry
Pi use the 64-bit Raspberry Pi OS: on the 32-bit one, pip may have to compile a dependency.

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

1. **Lights**: tick every kind of controller you have. You can mix them. If you know how
   many controllers of each kind you have, pick the number: the scan then tells you when
   it has found them all, and runs a deep scan by itself if some didn't answer.
2. **Controllers**: press **Scan**. It asks controllers on your network to identify
   themselves and changes nothing. Tick the ones to use. If your lights are on another
   network or subnet than this computer, type that network (like `192.168.2.0/24`) or the
   controllers' addresses before scanning. You can also add a controller by its address.
   If some controllers are missing, press **Missing lights? Run deep scan**: it keeps
   asking for up to half a minute. Govee controllers ignore many requests (often three in
   four), so a quick scan can miss them; asking again finds them.
   A JellyFish controller shows one line per zone; each zone becomes its own run.
3. **Name and count**: one card per run. Give it a name and a short name, the number of
   lights if you know it (WLED and JellyFish report theirs; leave it blank if you don't
   know: the Test step helps you count), and which end light 1 is at, as you face the
   lights. Runs can be installed left to right or right to left; "Light 1 is at" lets each
   one still show the right way round. Put the runs in order along the house, left to
   right, with ▲ and ▼: themes that play across the whole house use this order.
4. **Test**: one controller at a time ("Controller 2 of 3: Garage"):
   - **Find it**: the run blinks. Did the run you expected blink? If another one did, pick
     it and the names swap. If nothing blinked, the wizard lists what to check.
   - **Count** (Govee): every segment's first light lights up red or green, and you type how
     many of those markers you see. Then the last segment lights up red, and you type how
     many red lights you see. The wizard works out the count, like `5 × 14 + 3 = 73`. You
     can also type the number from the Govee Home app.
   - **Check** (Govee and WLED): light 1 red, the last light blue, plus 20 orange lights past
     the end. Say whether red is on the left or the right (can't tell? a dot runs from light
     1). Orange after the blue means the count is too low: type how many and it checks
     again. No blue at all means the count is too high.
   - **Done**: a summary like "Garage: 50 lights, light 1 at the right end".

   JellyFish and Tuya only blink. **More tests** has the extra patterns (colours, segment
   groups). Tests stop by themselves after a minute. Govee and WLED go back to what they
   showed; Tuya lights are saved before the test and put back afterwards. JellyFish can't
   report what it showed, so after testing pick a theme or use the JellyFish app.
5. **Time and place**: the time zone comes from this device (**Change** to pick another).
   For sunrise/sunset schedules, type your ZIP code and press **Look up** (it asks
   zippopotam.us); the wizard shows today's sunrise and sunset, and warns if the time zone
   doesn't fit the place. You can also use this device's location or type latitude and
   longitude.
6. **Save**: a table of the runs, with links to change or count each one. Every run needs
   its number of lights. Settings go to `data/config.json` and the server restarts with
   them.

With saved settings, every step at the top of the wizard can be clicked. Links:
`setup.html?step=4&controller=<controller id>` tests just that controller, and
`setup.html?step=5` opens Time and place.

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

## Themes

The **Themes** tab lists your own themes first (**My themes**), then the built-in ones by
group. Pick any theme to open it in the editor; nothing is sent to the lights until you press
an amber button.

- **Make one**: press **New theme**, or open a built-in theme and change it. Built-in themes
  never change: **Save** on one makes a copy in My themes. Your themes appear everywhere a
  theme is picked: Quick Settings tiles, schedules, the Visualization and the Controllers tab.
- **Movement**: Bands, Gradient, Solid, Random (still), Chase, Twinkle, Drift, Fireworks,
  Swirl, Flow, Steps, Beat, Breathe, Heartbeat, Flicker (candle, failing bulb, lightning or
  fire), Candles and Game day, each with its colors and settings. A built-in theme can be a
  movement too.
- **Layers**: up to three, for example a base plus **Sparkle** or an occasional **Comet** on
  top. A layer adds its light, covers the one below (black is see-through) or keeps the
  brightest.
- **Shape**: left to right, right to left, back and forth, or from the middle outward;
  mirrored around the middle; and **Whole house**, which lays the theme along all the runs
  as one long strip (in the order of the runs, each run's direction taken into account).
- **Sequence**: up to eight themes, each for its own time, cross-fading into the next.
- **Ideas**: **Show me variations** (six small previews with the settings nudged; tap one to
  use it), **Surprise me** (keep the colors or the movement if you like), about 40 palettes,
  colors from one color (complementary, triadic and so on) or from a photo (the photo stays
  in your browser), warm/cool and brightness for the whole palette, **Tap tempo** for the
  beat, and **Paint by hand**, segment by segment.
- **Favourites** (★) come first in Quick Settings; built-in groups you don't use can be
  hidden there. **Export** downloads your themes as a `.json` file; **Import** adds them on
  another house.

Your themes are kept in `themes.json` in the settings folder. If a schedule uses a theme you
delete, the schedule reports an error until you pick another theme.

## Good to know

- **No login.** Anyone who can open the page can control the lights. Keep it on your home
  network and don't forward the port to the internet.
- Your files in `data/`: `config.json` (settings), `secrets.json` (Tuya keys, if any),
  `schedules.json`, `themes.json` (your themes), `state.json` (what was last applied) and
  `logs/`. Back up this folder to keep your setup.
- To update: `git pull`, then `venv/bin/pip install -r requirements.txt` (Windows:
  `venv\Scripts\pip install -r requirements.txt`), then restart.
- **Strips on the page** are drawn the way each run is installed: a run whose light 1 is at
  its right end is drawn from the right, so an animation moves across the screen the same way
  it moves on the house. At **Fit**, the longest run fills the width and the others are drawn
  to scale.
- **Settings tab**: each run's **Test** button opens the wizard's test step for just that
  controller, and **Change ZIP / time zone** opens the time-and-place step.
- **Server clock**: the Schedules panel shows the server's time next to today's sunrise and
  sunset. Schedules run on the server's clock, so if it is more than two minutes off from
  the clock of the device you're browsing on, the panel warns you to check the server's date
  and time settings.

## Tests

No lights needed:

```sh
venv/bin/python tests/test_settings.py
venv/bin/python tests/test_setup.py         # wizard helpers; the ZIP lookup is faked, no internet
venv/bin/python tests/test_schedule.py
venv/bin/python tests/test_themes.py       # theme engine, storage, whole-house span
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
