# Getting the local key for Tuya / Smart Life lights

House Lights talks to Tuya / Smart Life lights over your own network, with no cloud in
between. To do that it needs two things for each light controller:

- the **device id**, which the setup wizard usually finds by itself, and
- the **local key**, a 16-character password the controller wants before it takes commands.

The local key lives in Tuya's cloud, and you fetch it **once**: the setup wizard's
**Get keys from Tuya** button gets every key at once, with the free `tinytuya` library, from a
free Tuya developer project you set up. This page walks through it. Plan on about 20 minutes
the first time.

> Tuya / Smart Life support in House Lights has been tested with a stand-in for the
> tinytuya library, not yet with real Tuya lights. If you try it, please tell us how it went.

## 1. Is my kit Tuya, WLED, or both?

Look at the box, the manual and the app you use:

| You see | What it is | What to do |
|---|---|---|
| **Smart Life** or **Tuya Smart** app | Tuya | Follow this page |
| A brand's own app (**ASAHOM**, TreatLife and others) that looks a lot like Smart Life | Tuya, under another name | Follow this page, starting with step 3 |
| **WLED** (on the box, or the controller's address opens a WLED page in a browser) | WLED | Skip this page: set the controller up in the WLED app, then run **Find my lights** again. WLED needs no key and can do more (animated themes light by light). |

Not sure? Run **Find my lights** in the setup wizard. A WLED controller shows up as a
**WLED** row, already ticked. A Tuya controller shows up as a **Tuya** row, with a box above
the list to get the keys.

## 2. The lights must be in the Smart Life app

Tuya's developer site can only link two apps: **Smart Life** and **Tuya Smart**. Brand apps
(ASAHOM and others) are built on Tuya but belong to that brand, and their keys can't be
looked up from outside. If your lights are in a brand app, you can't get their keys until you
move them to Smart Life.

## 3. Moving lights from a brand app to Smart Life

Do this **before** you get the keys: a light gets a **new** local key each time it is paired
again, so moving it later makes the old key stop working.

1. Install the **Smart Life** app and sign in (or create an account). Pick the same country
   or region you live in; you'll need it again in step 4.
2. In the brand app, open the light, tap the pencil (or the settings icon), and choose
   **Remove device**. This lets the controller be paired again.
3. Put the controller in pairing mode. The kit's manual says how; on many kits you hold the
   controller's button until the lights blink quickly.
4. In Smart Life, tap **+** then **Add device** and follow the app. Check that you can turn
   the lights on and off from Smart Life.

You can keep using Smart Life day to day afterwards. Don't move the lights back to the brand
app, or the keys will change.

## 4. Getting the keys

House Lights needs tinytuya installed (Tuya lights need it anyway):

- Windows: `venv\Scripts\pip install tinytuya`
- Linux, macOS or a Raspberry Pi: `venv/bin/pip install tinytuya`

Then:

1. **Make a free developer account** at [iot.tuya.com](https://iot.tuya.com/). It's Tuya's
   site for developers; it costs nothing for this.
2. **Create a cloud project.** Under **Cloud**, create a project for smart home use. For the
   **data center**, pick the one for where you live. The right one isn't always the obvious
   one: if no devices show up in step 5, edit the project to use another data center (or make
   a new project) and try again. This is the most common snag.
3. **Check the API services.** The project needs **IoT Core** and **Authorization**. Tuya
   renames its screens now and then; the
   [tinytuya README](https://github.com/jasonacox/tinytuya#setup-wizard---getting-local-keys)
   has the current names and screenshots.
4. **Note the Access ID and Access Secret** from the project's overview page. The setup
   wizard asks for them.
5. **Link your Smart Life account.** In the project, open **Devices**, then
   **Link Tuya App Account**, then **Add App Account**. Choose **Automatic** and
   **Read Only Status**, and a QR code appears. In Smart Life, open **Me**, tap the scan icon
   at the top right, and scan it. Your lights now show in the project's device list.
6. **Get the keys in the setup wizard.** In **1 Scout**, after **Find my lights**, press
   **Get keys from Tuya…** in the box above the list. Type the Access ID, the Access Secret and
   the data center you picked in step 2 (Western America is `us`, Eastern America `us-e`,
   Central Europe `eu`, Western Europe `eu-w`, India `in`, Singapore `sg`, China `cn`), then
   press **Get keys**. House Lights asks Tuya for every device in your Smart Life account, with
   its key and its name from the app, so the rows show which light is which.

   **Or use tinytuya's own wizard** from the House Lights folder:
   - Windows: `venv\Scripts\python -m tinytuya wizard`
   - Linux, macOS or a Raspberry Pi: `venv/bin/python -m tinytuya wizard`

   It asks for the same three things and one device id. For the device id, type `scan` to let
   it find one, or copy any light's **Virtual ID** from Smart Life (open the light, tap the
   pencil, then **Device Information**). It then lists every device with its **id** and
   **local key**, and saves them in a file called `devices.json`. Type each key in the setup
   wizard's **2 Spotlight** (below).

What House Lights does with them: it asks Tuya's cloud once, when you press **Get keys**, and
uses the Access Secret for that request only: it isn't saved. It keeps the keys in memory and
never sends one to the web page; **Go live** saves only the keys of the lights you ticked.
That's the only time House Lights talks to the internet for Tuya lights.

The IoT Core service is a free trial that runs out after a month. You only need it while you
fetch keys, so that's fine. If you need new keys later, extend the trial from the project
(the tinytuya README shows how).

## 5. In the setup wizard

1. In **1 Scout**, tick the **Tuya** row for each of your lights. After **Get keys from Tuya**,
   each row shows the light's name from Smart Life and "✓ Key from Tuya", so plugs and bulbs are
   easy to leave unticked. A row marked "⚠ Not in your Smart Life account" is in another app
   or another account: see step 3, then get the keys again.
2. **2 Spotlight** goes through your lights one at a time. A light with its key blinks like
   any other, and its Smart Life name is suggested as its name. A light without a key asks for
   it first: press **Get keys from Tuya…** there, or type its 16-character **local key** from
   tinytuya's list (the page shows the end of its device id, like `…f9a1c`, to match them),
   pick the version tinytuya listed (3.3 if unsure) and press **Check the key**. Once the key
   works, the light blinks.

Close the Smart Life app on your phone while you test: Tuya lights take one connection at a
time. The keys are saved in `data/secrets.json`, readable only by you. They never go into
`config.json` and are never sent to the web page.

Keep `devices.json` (and `tuya-raw.json`, which the wizard writes next to it) private too:
they hold every key of every device in your account. Don't add them to a public repository.

## When a key stops working

A controller gets a new local key each time it is paired again: after it was removed and added
back in Smart Life, moved to another app, or reset. Press **Get keys from Tuya** in the
setup wizard again (or run `python -m tinytuya wizard` again and type the new key in
**2 Spotlight**).

## Other questions

- **A light is marked "Not in your Smart Life account", or isn't in tinytuya's list.** It's
  probably still in a brand app, in another
  family member's Smart Life account, or the cloud project's data center doesn't match your
  account's region. Check step 3, and step 2 of "Getting the keys".
- **Can House Lights use the key from the ASAHOM app?** The key itself would work, but brand
  apps don't let anyone outside the brand look it up. Moving the lights to Smart Life is the
  way that works.
- **Does House Lights need the internet afterwards?** No. It asks Tuya's cloud once, when
  you press **Get keys from Tuya**. Once the key is saved, it talks to the lights over your own
  network only.
