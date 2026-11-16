# House Lights on a Raspberry Pi

A Raspberry Pi makes a good always-on home for House Lights: small, quiet, and it uses a few
watts. This guide goes from an empty SD card to the dashboard starting by itself at boot.

> **Not tested on a Raspberry Pi yet.** Everything here is standard Raspberry Pi OS and
> Python, and House Lights has no compiled parts of its own, but nobody has reported a
> run on a Pi so far. If you try it, please report what worked and what didn't.

## Which boards work?

House Lights is a Python web server. It needs a board that runs a full Linux and Python 3.10
or newer, so it runs on Raspberry Pi computers, but not on microcontrollers.

| Board | Works? | Notes |
|---|---|---|
| **Raspberry Pi 5** | Yes | Fastest. Needs the 5V 5A USB-C supply (27 W). |
| **Raspberry Pi 4**, **Pi 400** | Yes | Plenty for everything. 5V 3A USB-C supply. |
| **Raspberry Pi 3B, 3B+, 3A+** | Yes | Use the Lite OS (no desktop). Wi-Fi is 2.4 GHz only. 5V 2.5A micro-USB supply. |
| **Raspberry Pi Zero 2 W** | Should work | 512 MB of memory and Wi-Fi only (2.4 GHz). Fine for static themes and schedules; animated themes on several runs may need a lower frame rate (see *Slower boards*). |
| Raspberry Pi 2 (older v1.1), Pi 1, **Pi Zero / Zero W** (the original, not "2") | Not recommended | These run only the 32-bit OS (Pi 1 and Zero: ARMv6). Some Python packages House Lights needs may have no ready-made build there, so pip would try to build them from source, which needs extra tools and can take hours or fail. Untested. |
| **Raspberry Pi Pico / Pico W / Pico 2**, **Arduino**, **ESP32**, **ESP8266** | No (as the server) | These are microcontrollers: no Linux, no full Python. They can't run House Lights. |

**ESP32 and ESP8266 as light controllers.** These boards can't run the server, but they make
very good *light controllers*: flash the free [WLED](https://kno.wled.ge/) firmware on one,
wire it to an addressable LED strip, and House Lights controls it like any WLED controller,
light by light. So a Raspberry Pi running House Lights plus an ESP32 running WLED is a
complete do-it-yourself setup.

Other single-board computers (Orange Pi, Rock Pi, and so on) running a 64-bit Debian or
Ubuntu should work the same way, with their own way of writing the SD card.

## What you need

- A Raspberry Pi from the "Yes" rows above, with its proper power supply. Phone chargers
  often can't supply enough current and cause random restarts.
- A microSD card, **8 GB or larger**. Class 10, U1 or A1 on the label; very old or slow cards
  make the Pi sluggish.
- A computer to write the card (Windows, macOS or Linux), and an SD card reader.
- Your home Wi-Fi name and password, or an Ethernet cable to the router (more reliable).

No screen or keyboard is needed: you set everything up from your computer over SSH.

## 1. Write the SD card

1. Install **Raspberry Pi Imager** from <https://www.raspberrypi.com/software/> and start it.
2. **Choose device**: your board (Raspberry Pi 5, 4, 3 or Zero 2 W).
3. **Choose OS**: *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)**.
   - *Lite* has no desktop, which leaves more memory for the server. On a Pi 4 or 5 the full
     desktop version also works if you want to use the Pi with a screen.
   - Make sure it says **64-bit**.
4. **Choose storage**: your SD card. Check it is the card, not another drive: it gets erased.
5. **Next** → **Edit settings**:
   - **General**
     - Hostname: `houselights` (you'll reach the Pi as `houselights.local`).
     - Username and password: pick your own and **write them down**. There is no default
       login on current Raspberry Pi OS; if you forget them, the easiest fix is writing the
       card again.
     - Wireless LAN: your Wi-Fi name and password, and your **Wi-Fi country**. Tick
       *Hidden SSID* if your network name is hidden.
     - Locale: your time zone and keyboard layout.
   - **Services**: tick **Enable SSH** → *Use password authentication*.
6. **Save** → **Yes** → **Yes**. Writing and verifying takes 5 to 15 minutes. If Windows then
   offers to format the card, say no.

### Which Wi-Fi networks work

- **Pi 3, Pi Zero 2 W**: 2.4 GHz only. A network that offers 2.4 and 5 GHz under one name is
  fine. Pi 4 and 5 also work on 5 GHz.
- Security **WPA2-Personal** (one shared password) or **WPA2/WPA3 mixed**. A WPA3-only
  network may refuse the older boards.
- Not: guest networks (they usually keep devices apart, so the Pi couldn't reach your lights
  or your phone), networks with a sign-in web page, or *Enterprise* networks with a username.
- Use the same network as your light controllers, or one that your router lets reach them.

## 2. First start and logging in

1. Put the card in the Pi and plug in the power. The first start takes 2 to 3 minutes: it
   restarts once and joins your Wi-Fi.
2. On your computer, open a terminal (Windows: PowerShell; macOS: Terminal) and run, with
   your username:

   ```sh
   ssh yourname@houselights.local
   ```

   Answer `yes` to the question about the host's authenticity, then type your password
   (nothing shows while you type).
3. If `houselights.local` isn't found, look in your router's list of devices for
   `houselights` and use its address instead: `ssh yourname@192.168.1.57`, for example. If a
   screen is connected, the Pi's address is also shown above the login prompt.

**Tip:** in your router, reserve a fixed address for the Pi (often called *DHCP
reservation*), so the dashboard is always at the same address.

## 3. Install House Lights

On the Pi (in the SSH window):

```sh
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3 python3-venv git
python3 --version        # must be 3.10 or newer
uname -m                 # aarch64 means the 64-bit OS

git clone https://github.com/RAHIvana/Permanent-Outdoor-Liight-Controller.git houselights
cd houselights
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

For **Tuya / Smart Life** lights, also run `venv/bin/pip install tinytuya`.

The `full-upgrade` can take a while the first time, longest on a Pi 3 or Zero 2 W.

## 4. Try it

```sh
venv/bin/python -m houselights --dry
```

On your phone or computer, open **http://houselights.local:8090/** (or
`http://ADDRESS:8090/` with the Pi's address). The setup wizard opens; the main
[README](README.md#the-setup-wizard) explains each step.

- `--dry` is practice mode: commands are logged and nothing is sent to the lights. Use it
  for a first look, especially if another program or computer already controls your
  lights. When everything looks right, stop it with Ctrl+C and start it without `--dry`
  (or choose *Live* in the wizard's *Time and place* step).
- If your lights are on a different network or subnet than the Pi, type that network in the
  wizard's scan box (like `192.168.2.0/24`).
- Only one House Lights server should control a set of lights at a time.

## 5. Start it automatically at boot

Once it works, make it a service. On the Pi, from the `houselights` folder:

```sh
sudo tee /etc/systemd/system/houselights.service >/dev/null <<EOF
[Unit]
Description=House Lights
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/python -m houselights
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now houselights
```

`$USER` and `$PWD` fill in your username and folder. Stop any copy you started by hand
first (Ctrl+C), or the port is taken.

Useful commands:

```sh
systemctl status houselights          # running?
journalctl -u houselights -f          # live log (Ctrl+C to leave)
sudo systemctl restart houselights    # restart
sudo systemctl stop houselights       # stop until the next boot
sudo systemctl disable houselights    # don't start at boot any more
```

## Updating

```sh
cd ~/houselights
git pull
venv/bin/pip install -r requirements.txt
sudo systemctl restart houselights
```

Your settings in `data/` are kept. Back up that folder to keep your setup, for example
`scp -r yourname@houselights.local:houselights/data houselights-backup` from your computer.

## Slower boards and Wi-Fi

- **Animated themes stutter** (most likely on a Pi 3 or Zero 2 W with several runs): lower
  the frame rate. Stop the server, edit `data/config.json`, change `"stream_fps": 15` to
  `10`, and start it again.
- **Wi-Fi power saving** can delay the packets of animated themes. To switch it off for your
  Wi-Fi connection (current Raspberry Pi OS, which uses NetworkManager):

  ```sh
  nmcli -t -f NAME,TYPE connection show          # find your Wi-Fi connection's name
  sudo nmcli connection modify "NAME" 802-11-wireless.powersave 2
  sudo nmcli connection up "NAME"
  ```

  An Ethernet cable avoids this altogether.
- **Power**: `vcgencmd get_throttled` should print `throttled=0x0`. Anything else means the
  power supply is too weak or the Pi got too hot; that causes slowdowns and crashes.

## Troubleshooting

| Problem | Try |
|---|---|
| `houselights.local` not found | Wait another minute; use the address from your router's device list. Some older Windows versions don't resolve `.local` names. |
| SSH says *Permission denied* | Wrong username or password. If forgotten, write the card again with Imager. |
| The Pi never shows up on the network | Check the Wi-Fi name, password and country in Imager; on Pi 3 / Zero 2 W the network must offer 2.4 GHz. Try an Ethernet cable. |
| `pip install` builds something for a long time or fails | You're probably on the 32-bit OS or an older board. Use Raspberry Pi OS Lite **64-bit** on a board from the "Yes" rows. |
| The wizard's scan finds nothing | Type your lights' network or addresses in the scan box. Check the controller's own requirements in the main [README](README.md#getting-each-kind-of-controller-ready) (for example LAN Control in the Govee app). |
| Page doesn't open from the phone | Is the phone on the same Wi-Fi (not a guest network)? Is the server running (`systemctl status houselights`)? |

## Good to know

- **No login**: anyone on your home network who opens the page can control the lights. Don't
  forward port 8090 on your router to the internet.
- The SD card is the weak point of a Pi that runs for years. Keep a backup of `data/`, and
  if the card dies, write a new one with these steps and copy `data/` back.
