# How House Lights finds and sets up your lights

The first time you open House Lights (and whenever you press **Change setup** on the Settings
tab) the **setup wizard** runs. Its job is to turn "some lights somewhere on my network" into a
saved description of your house that the dashboard can draw and every theme can play on:

- which **controllers** there are,
- which **run** of lights each one drives,
- how many lights are in each run, and which end is light 1,
- where the runs sit along the house (left to right),
- where the house is, for sunrise and sunset.

This page explains how the wizard gets there: what it asks the network, which test patterns it
plays on your lights, which answers it looks for, and what it does with them. It is for people
who wonder why the wizard asks what it asks, and for contributors who change it. The step by
step walk-through for users is in the [README](../README.md#the-setup-wizard); adding a new kind
of controller is in the [drivers guide](../houselights/drivers/README.md).

Where the code is: `houselights/setup.py` (the wizard's API and its test patterns),
`houselights/static/setup.js` (the pages and the questions), `houselights/settings.py` (what
gets saved and how it is checked).

## Words used

| Word | Meaning |
|---|---|
| **Controller** | The box on your network that drives lights (a Govee, WLED, JellyFish or Tuya / Smart Life device). It has an IP address. |
| **Run** | One series of lights on one controller, in a line, like the eave over the garage. The page and `config.json` call it a run. One controller gives one run; a JellyFish controller has several zones and each zone is its own run. |
| **Light** | One LED (or one pixel). Themes give every light its own colour. |
| **Light 1** | The first light of a run, the way the controller counts. It can be at either end of the house, so the wizard finds out which. |
| **Segment** | A group of lights the controller colours as one. Govee H806A: 5 lights. WLED and JellyFish: 1 (every light is its own). Tuya and basic Govee models: the whole run is one segment. |
| **Frame** | One colour for every light, sent many times a second to play an animated theme ("streaming", 15 frames a second). |
| **Test pattern** | A pattern the wizard plays on a run so that you can look at the lights and answer a question. |

## The five steps at a glance

| # | Step | The question | What the lights do | What it saves |
|---|---|---|---|---|
| 1 | **Scout** (find) | Which controllers are on my network? | Nothing. The questions to the network change nothing. | One `controllers` entry and one `runs` entry per ticked controller |
| 2 | **Spotlight** (name) | Which lights are these, what do I call them, where are they on the house? | The whole run blinks. | The run's `name` and `short` name, and the order of `runs` |
| 3 | **Tally** (count) | How many lights does the run have, and which end is light 1? | Counting and checking patterns | `lights`, `light1` and `reverse` |
| 4 | **Sun clock** (place) | Where and when? | Nothing | `timezone`, `location` and `mode` |
| 5 | **Go live** (save) | Is this right? | Nothing | Writes `config.json` (and Tuya keys to `secrets.json`), restarts the server |

Every step can be clicked once settings exist, and deep links go straight to one:
`setup.html?step=count&controller=<controller id>` counts one controller, `?step=place` opens
the sun clock (also `find`, `name`, `save`, or the step's number 1 to 5). The Settings tab's
**Test** button for a run opens the count step for just that controller.

## Step 1: Scout, finding the controllers

**Asking changes nothing.** Every kind of controller is asked "who are you?" in its own way,
all at once:

| Kind | How it is asked | What an answer tells us | Quick scan | Deep scan |
|---|---|---|---|---|
| **Govee** | UDP: a `scan` message to the multicast address `239.255.255.250` port 4001, and the same message straight to each address you typed. Devices answer on UDP port 4002; commands later go to port 4003. | The model number (SKU) and the end of the device id | up to 3 s, 10 rounds | up to 30 s, 100 rounds |
| **WLED** | HTTP: `GET /json/info` on each address | Firmware version, name, MAC address and the **light count** (`leds.count`) | 1 s per address | 4 s per address |
| **JellyFish** | WebSocket (port 9000, path `/ws`): ask for the `zones` | One row per zone, with its pixel count (`numPixels`) | 1 s per address | 4 s per address |
| **Tuya / Smart Life** | Listen only (sends nothing): the broadcasts Tuya devices make on UDP 6666 and 6667 every few seconds. Typed addresses are tried on TCP 6668 instead. | The device id and protocol version (6666 is readable; 6667 is encrypted) | listens 6 s | listens 20 s |

Things worth knowing:

- **Govee controllers ignore most requests.** Measured on H806A over Wi-Fi, they answer one in
  four to one in ten. A single try misses them at random, so the scan asks again, only the
  addresses that have not answered, up to the round limit. That is also why there is a deep scan,
  and why the card for each kind asks **How many controllers?** If the scan finds fewer than the
  number you picked, it runs a deep scan by itself and stops as soon as it has them all.
- **Where to look.** Leave it empty and Govee asks by multicast on this computer's own network,
  WLED and JellyFish ask this computer's own /24 network (256 addresses). Type addresses or networks
  (`192.168.2.0/24, 192.168.2.7`) when the lights are on another network section. At most 1024
  addresses per scan, and only **home addresses** are accepted (192.168.x.x, 10.x.x.x,
  172.16 to 172.31.x.x, loopback, link-local): the server will not be pointed at the internet.
- **Add by address** asks one address as every kind at once ("who are you?") and keeps what
  answers. Once one kind has answered, the others get one more second, not their whole timeout.
  The result reads like "192.168.2.50 is a WLED controller".
- **Tuya needs more.** Its rows need the device id and the 16-character **local key** (from
  `python -m tinytuya wizard`), and the optional `tinytuya` package. Smart Life rows are never
  ticked by themselves, because plugs, bulbs and other gadgets use Smart Life too.
- **Govee LAN Control** must be switched on for each device in the Govee Home app, or it will
  not answer. Another program on UDP port 4002 (for example Home Assistant's Govee integration)
  takes the replies: stop it while scanning.

**What a scan answer looks like** to the wizard (a "row"):

| Field | Meaning |
|---|---|
| `type`, `ip` | The kind of controller and its address |
| `model` | A Govee SKU such as `H806A`, or `WLED`, `JellyFish`, `Tuya light` |
| `label` | What the list shows, for example "Govee H806A" or "WLED 0.14.0 · Garage" |
| `supported`, `tier` | Whether House Lights can use it, and for Govee how much: `full`, `try` or `basic` (see the [drivers guide](../houselights/drivers/README.md#models-and-tiers)) |
| `lights` | The light count, when the controller says so (WLED, JellyFish); otherwise `null` |
| `zone` | JellyFish only: the zone this row is |
| `device_tail`, `device_id`, `version`, `needs_key` | The end of the device id for recognising it, and the Tuya details |

**What it saves.** Every ticked row becomes a `controllers` entry (an id built from its kind
and address, like `govee-192-168-2-20`) and a `runs` entry with a placeholder name
(`Run 1`, or the zone's name), `lights` filled in if the controller reported them, and
`light1` empty (not checked yet).

## Step 2: Spotlight, which lights are these?

One controller at a time, the wizard plays the **Blink** test the moment the page comes up:

- **Pattern `identify`:** the whole run is white for 2 seconds, then dark for 2 seconds, again
  and again. It is easy to spot from the street.
- Controllers that cannot change quickly (Tuya: every 2 s, JellyFish: every second) blink white and
  blue instead of white and dark.
- If a controller that streams (Govee, WLED) was off, it is switched on for the test and **switched off
  again** when the tests are over.

**The answer we want:** "Yes, that is the run I expected", then:

1. a **name** (up to 40 characters, for the page) and a **short name** (up to 12, for buttons),
2. its **place on the house**, standing in front of it, left to right.

**"Nothing blinked"** opens a checklist: is the controller powered and working in its own app,
is LAN Control on (Govee), is this computer on the same network and not a guest network, is a
firewall blocking Python on private networks?

**What it saves:** `runs[].name`, `runs[].short`, and the **order** of `runs`. That order is how
the dashboard draws your house and how patterns that span the whole house travel from one end
to the other. (The controller takes the run's name as its own.)

## Step 3: Tally, counting the lights and finding light 1

Why it matters: a theme is one colour per light. A wrong count shows as a pattern cut off or
spilling past the end, and without knowing which end is light 1 an animation can run the wrong
way along the house. Govee H806A also colours **static** themes per 5-light segment, so the
segment count has to be right too.

For each run, in order along the house, the wizard goes through three phases: **Count**,
**Check the ends**, **Done**. If the run already has a count (from the controller or from an
earlier setup) it first asks "N lights. Is that right?"; **Yes** skips straight to the check.

Which patterns are offered depends on what the controller can do (its *capabilities*, described
in the [drivers guide](../houselights/drivers/README.md#capabilities-caps)):

| Controller | How the count is found | How light 1 is found |
|---|---|---|
| **Govee H806A** (full) | Counted with segment colours, patterns A and B below | Pattern C |
| **Govee H705, H706, H707, H805, H3A5x** ("try") | Typed (no segment colours on these) | Pattern C. It also shows at once whether the model plays light by light. |
| **WLED** | The controller reports it; the wizard asks you to confirm it | The Check pattern, with orange lights past the end |
| **JellyFish** | The zone reports its pixel count | You pick the end from a list: it cannot show single lights |
| **Tuya, other Govee models** (basic) | Typed | You pick the end from a list |

### Govee H806A: A, B and C

Why not just stream a frame of the right length? A Govee stream frame of N colours is
**stretched over the whole run in N equal parts**, so it cannot show "lights past the end".
Counting therefore uses the **segment command**, which colours fixed groups of 5 lights from light 1,
the same way the Govee Home app counts. (The findings behind this are in
[govee-lan-notes.md](govee-lan-notes.md).)

| | What the lights show | The question | What we do with the answer |
|---|---|---|---|
| **A** `seg4` ("Colour pattern") | Every group of 5 lights takes the next colour in turn: green, white, red, yellow, then green again. It is set when the page opens and stays on the lights until the next test or theme. | "What colour is the last block at the far end?" and "How many blocks of that colour?" | groups = 4 × (blocks − 1) + the colour's place (green 1, white 2, red 3, yellow 4). Example: 6 red blocks → 4 × (6 − 1) + 3 = 23 groups. |
| **B** `seglast` ("Last group pattern") | Every group is white and only group number *groups* is red. If the groups were miscounted, any group after the red is blue. | "How many red lights at the end?" (1 to 5) | lights = 5 × (groups − 1) + red. Example: 5 × 23 + 5 = 120 lights. **Blue after the red means a colour was miscounted:** count again. |
| **C** `ends` ("Ends pattern") | A frame of exactly the count: light 1 red, the last light blue, everything between white. | "Red and blue should each be a single light at the very ends. Which end is the red at?" | `light1` = left or right. If red or blue covers two lights, or is not at the very end, the count is off: count again. |

A single light past the end that never changes is not driven by the controller: the controller
drives as many lights as it is set up for in the Govee Home app. Leave it out of the count, or
use **Type the number from the Govee app**.

### WLED: the Check pattern

The count is already known (`leds.count`). The **Check** pattern (`check`) shows the run as light 1
red, the lights between dim white, the last light blue, and **20 orange lights past the end** (the
frame is deliberately longer than the count). The questions, in order:

1. **"Where is the red light?"** Left, right, or "can't tell". If you cannot tell, the **Direction**
   pattern (`chase`) runs a white dot from light 1 to the last light at 8 lights a second:
   "Where does it start?" Answers: `light1` = left or right (or still unknown).
2. **"Do you see any other colour, like orange, after the blue?"**
   - **No, blue is the last light:** the count is right.
   - **Yes, orange after the blue:** the count is too low. You say **how many orange lights** (1 to 20),
     the wizard adds them to `lights` and checks again. All 20 orange? Add them and check again:
     the next check shows 20 more.
   - **I don't see blue at all:** the count is too high (the blue light is past the end).
     Count again or change the number.

### Controllers that cannot show single lights

JellyFish, Tuya and basic Govee models change one colour (or a limited palette) at a time, so there
is nothing to count by eye. You type the count (for JellyFish it is prefilled from the zone) and, on
the **Done** page, pick which end light 1 is at (**Left end**, **Right end**, or **Not sure yet**).

### More tests (any controller, any time)

| Pattern | What the lights show | Use it to |
|---|---|---|
| `ruler` "Check the count" | Light 1 red, last light blue, every 10th light white, every 5th dim | Check the count by eye |
| `chase` "Direction" | A white dot runs from light 1 (red) to the last light (blue) | Find light 1's end |
| `rgb` "Colours" | First third red, middle third green, last third blue | See whether the colours are right. If not, please report the controller. |
| `segments` "Segment groups" | Groups of one segment in alternating orange and blue | See how the run divides into segments (the size static themes are sent in) |

Controllers with `count: "manual"` and one colour per light (no controller today) would count with the
**marker** patterns instead: `markers` (dim white with the first light of every segment red or green
in turn, every tenth blue; you count the markers) and `tail` (the last group red; lights =
segment size × (markers − 1) + red).

### Done

The summary line ("Garage roofline: 120 lights, light 1 at the left end") comes with a **sweep**:
a dot runs from light 1 in the chosen direction. It shows what the dashboard will do: it turns runs
round as needed, so patterns travel the same way along the whole house.

## Answers into configuration

| You answer | The wizard works out | Saved as |
|---|---|---|
| The lights blinked; a name and short name; a place | nothing | `runs[].name`, `runs[].short`, order of `runs` |
| Last colour and number of blocks (Govee A) | groups = 4 × (blocks − 1) + place of the colour | nothing yet: it sets pattern B |
| Red lights at the end (Govee B) | lights = 5 × (groups − 1) + red | `runs[].lights` |
| A typed number | the number, 1 to the model's maximum (255 for streaming Govee) | `runs[].lights` |
| Orange lights after the blue (WLED) | lights = lights + orange | `runs[].lights`, then it checks again |
| The end the red light is at | `light1` = `left` or `right`; `reverse` = `true` for right | `runs[].light1`, `runs[].reverse` |
| ZIP code (or latitude and longitude) | latitude, longitude, place name | `location` |
| Time zone | warns if noon there would not fall between 10:30 and 14:30 | `timezone` |
| Live or practice | nothing | `mode` |

And what the saved values are used for afterwards:

- `lights` and the model's segment size give the segments: `ceil(lights / lights_per_segment)`.
  The dashboard draws every run to scale.
- **Static themes** are rounded to one colour per segment and sent as segment commands (one per
  colour); controllers that take a whole frame (WLED, JellyFish) get one colour per light.
- **Animated themes** are sent as one colour per light, 15 times a second.
- `reverse` makes the dashboard turn a run's frames round, so an animation moves across the house
  the way it moves on the page.
- The order of `runs` is the left to right order of the house, used for whole-house themes.

## Step 4: Sun clock

The time zone comes from the browser (**Change** to pick another). Type a **ZIP code** and press
**Look up**: the server asks zippopotam.us (the ZIP is checked first and the country must be two
letters) and the wizard shows today's sunrise and sunset for it. Or type latitude and longitude, or
use the device's location (browsers share it only on https or localhost). The wizard warns when the
time zone does not fit the place. You also pick the **mode**: **Live** sends to the lights, **Practice**
only logs (the same as starting the server with `--dry`; if you did, it stays in practice mode).

Leaving the location empty is fine: clock-time schedules work, sunrise and sunset schedules do not.

## Step 5: Go live

Before saving, the wizard checks that every run has a different name and a light count. Pressing
**Go live**:

1. stops any test that is playing and switches off again the controllers it had switched on,
2. sets `reverse` on every run from its `light1`,
3. sends the settings to the server, which validates them again (controller addresses must be home
   addresses, models must be known, names and counts must make sense),
4. writes `config.json`, with keys such as Tuya's local key in `secrets.json` instead (readable only by
   you, never sent to the page),
5. restarts itself with the new settings and sends you to the dashboard.

What a saved `config.json` looks like (made-up names and addresses):

```json
{
  "version": 1,
  "mode": "live",
  "listen": {"host": "0.0.0.0", "port": 8090},
  "stream_fps": 15,
  "timezone": "America/New_York",
  "location": {"lat": 40.75, "lon": -73.99, "zip": "10001", "place": "New York, NY"},
  "controllers": [
    {"id": "govee-192-168-2-20", "type": "govee", "model": "H806A", "ip": "192.168.2.20", "name": "Garage roofline", "enabled": true},
    {"id": "wled-192-168-2-31", "type": "wled", "model": "WLED", "ip": "192.168.2.31", "name": "Porch", "enabled": true}
  ],
  "runs": [
    {"name": "Garage roofline", "short": "Garage", "subtitle": "", "start": "", "controller": "govee-192-168-2-20",
     "lights": 120, "light1": "left", "reverse": false, "baseline": {"brightness": 50, "kelvin": 2200}},
    {"name": "Porch", "short": "Porch", "subtitle": "", "start": "", "controller": "wled-192-168-2-31",
     "lights": 50, "light1": "right", "reverse": true, "baseline": {"brightness": 50, "kelvin": 2200}}
  ]
}
```

Runs are listed left to right along the house. `baseline` is the warm white a run returns to.

## Safety

- **Scanning only reads.** Tests do change the lights: each streamed test stops by itself after 60
  seconds. The Govee counting colours (A and B) stay until the next test or theme.
- **Going back.** When a test stops, Govee and WLED return to what they showed; Tuya lights are saved
  before the test and put back afterwards; JellyFish cannot report what it showed, so afterwards pick a
  theme or use its own app. The wizard says which applies to the controller in front of you.
- **Practice mode** (`--dry`) sends nothing: the strip on the page shows what the lights would do.
  Simulators for Govee, WLED and JellyFish in `tools/` let you try the whole wizard without lights (see
  "Try it without lights" in the README).
- **Home addresses only.** Scans, "add by address" and saved controllers refuse addresses outside your own
  network, and the server answers only to IP addresses, `localhost` and names on your own network.

## When the answers look wrong

| What you see | What it means | What to do |
|---|---|---|
| Nothing blinks | The command did not arrive | Power, Govee LAN Control, same network, firewall (see Spotlight above) |
| Govee: blue after the red in pattern B | A colour was miscounted in pattern A | **Count the colours again** |
| Govee: red or blue in pattern C covers two lights | The count is off by some lights | **Count again**, or type the number from the Govee app |
| WLED: orange after the blue | The count is too low | Say how many orange lights; the wizard adds them |
| WLED: no blue at all | The count is too high | Count again or change the number |
| Light 1 is at the right end | The run is installed right to left | Pick **Right end**: the dashboard turns it round |
| The scan finds fewer controllers than you have | Govee answers few requests | Pick **How many controllers?**, or press **Deep scan** |
| Only Govee is missing | LAN Control is off, or another program holds UDP 4002 | Switch LAN Control on; stop other Govee programs while scanning |
