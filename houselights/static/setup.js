"use strict";
// Setup wizard: 1 Scout (find the controllers, every kind at once), 2 Spotlight (each one
// blinks, then you name it and place it along the house), 3 Tally (count each run and find
// light 1), 4 Sun clock (time zone and location), 5 Go live (save config.json; the server
// restarts with it).
// Deep links: setup.html?step=count&controller=<id> counts only that controller (step=test
// too); ?step=place opens at Sun clock (find, name, count, place, save, or the step's number
// 1 to 5). With a saved config, every step at the top can be clicked.
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
// A file in the settings folder, written with the server's separator (backslashes on Windows).
const inHome = (home, name) => home + (home.includes("\\") ? "\\" : "/") + name;

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const W = {step: 0, info: null, cfg: null, found: [], counts: {}, testing: {}, anim: null, lps: {},
           t: null, jump: false, kinds: {}, untick: new Set(), autoTick: true, tiers: {}};
const MAX_COUNT = 12;                      // "How many controllers?" choices; 0 = not sure
const STEPS = 5;
// Steps by name, for links: setup.html?step=test&controller=<id>, ?step=place
const STEP_NAMES = ["find", "name", "count", "place", "save"];
const STEP_ALIAS = {test: "count"};          // older links
const KINDS = ["govee", "wled", "jellyfish", "tuya"];
const KIND_NAME = {govee: "Govee", wled: "WLED", jellyfish: "JellyFish", tuya: "Tuya / Smart Life"};
// Govee models differ (tiers): full = everything, nothing to say.
const TIER_NOTE = {try: "Basic control; light-by-light animation untested on this model: try it in the Check test",
                   basic: "One colour at a time"};
const INSTALL_TUYA = {win: "venv\\Scripts\\pip install tinytuya", nix: "venv/bin/pip install tinytuya"};
// "Not finding yours?": how to recognise each kind, and how to get it ready.
const HELP = {
  govee: {know: "Any Govee light that has LAN Control in the Govee Home app.",
    note: "The H806A is fully tested. Other models work at a basic level until someone tests them.",
    steps: ["In the Govee Home app, open the light's settings and switch on LAN Control.",
            "Check the light is on and works in the app.",
            "This computer must be on the same network as the lights (not a guest network)."]},
  wled: {know: "You use the WLED app, or the controller's address opens a WLED page in a browser. DIY controllers, and ASAHOM Pro kits sold with WLED.",
    steps: ["Find the controller's address in the WLED app or your router.",
            "Open that address in a browser: you should see the WLED page.",
            "For animated themes, tick Receive UDP realtime in WLED's Sync Interfaces settings."]},
  jellyfish: {know: "You use the JellyFish app. Each zone becomes its own run.",
    steps: ["Set up the zones in the JellyFish app first.",
            "The controller must be on and reachable on your network."]},
  tuya: {know: "You use Smart Life, Tuya Smart, or a brand app that links through Smart Life: ASAHOM, TreatLife, likely Astoria. "
      + "A simple test: if the Smart Life app can find and control your lights, they're Tuya, and House Lights can use them. "
      + "Plugs, bulbs and other smart-home gadgets use Smart Life too, so the scan may list devices that aren't lights: tick only your lights.",
    steps: ["Install tinytuya: on Windows run INSTALL_WIN, on Linux or a Raspberry Pi INSTALL_NIX, then start House Lights again.",
            "Get each light's local key once: link the Smart Life app to a free iot.tuya.com cloud project, then run python -m tinytuya wizard (see the README).",
            "Close the Smart Life app while testing: these lights take one connection at a time."]},
};
const TEST_HELP = {
  identify: "The whole run blinks. Is it the run you expect?",
  ruler: "Light 1 is red, the last light blue, every 10th light white. If the blue light isn't the very last light, the count is wrong.",
  chase: "A white dot runs from light 1 (red) to the last light (blue).",
  rgb: "Red, green and blue thirds. If the colours look wrong, this controller may need a fix: please report it.",
  segments: "Orange and blue groups: each group is one segment. Static themes are sent one colour per segment.",
};
const RESTORE_NOTE = {
  auto: "When a test stops, the lights go back to what they showed before.",
  snapshot: "The light's settings are saved before a test and put back afterwards.",
  none: "This controller can't report what it showed, so it can't be put back after a test: afterwards, pick a theme here or in its own app.",
};
const LIGHT1 = {left: "Left end", right: "Right end", "": "Not sure yet"};

function err(msg) { $("#err").textContent = msg || ""; }
const validIp = ip => /^\d{1,3}(\.\d{1,3}){3}$/.test(ip) && ip.split(".").every(n => Number(n) <= 255);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
function button(label, fn, cls = "") {
  const b = el("button", cls, label);
  b.onclick = async () => { err(""); try { await fn(); } catch (e) { err(e.message); } };
  return b;
}

// --- data helpers --------------------------------------------------------------------------
const drv = type => W.info.drivers.find(d => d.type === type) || {models: {}, caps: {}, tests: [], max_lights: {}, lights_per_segment: {}};
// Per model (Govee models differ): label, tier, caps, tests, limits. From the server's
// model_info, else the tier a scan reported for that model (W.tiers), else Govee "basic".
function modelInfo(type, model) {
  const d = drv(type);
  if (d.model_info?.[model]) return d.model_info[model];
  const tier = W.tiers[`${type}|${model}`] || (type === "govee" ? "basic" : null);
  return tier && d.tiers?.[tier] ? {...d.tiers[tier], model, tier, label: `${type === "govee" ? "Govee " : ""}${model}`} : null;
}
const tierOf = c => modelInfo(c.type, c.model)?.tier || null;
const modelLabel = (type, model) => modelInfo(type, model)?.label || drv(type).models[model] || model;
const maxLights = c => modelInfo(c.type, c.model)?.max_lights || drv(c.type).max_lights?.[c.model] || 3000;
const testsOf = c => modelInfo(c.type, c.model)?.tests || drv(c.type).tests || [];
const capsOf = c => modelInfo(c.type, c.model)?.caps || drv(c.type).caps || {};
const ctrlOf = cid => W.cfg.controllers.find(c => c.id === cid);
const runOf = cid => W.cfg.runs.find(r => r.controller === cid);
const where = c => c.ip + (c.zone ? ` · ${c.zone}` : "");
const sameSpot = (a, b) => a.type === b.type && a.ip === b.ip && (a.zone || "") === (b.zone || "");
const spotKey = d => `${d.type}|${d.ip}|${d.zone || ""}`;
const hasLights = r => Number(r.lights) >= 1;
const lpsOf = c => modelInfo(c.type, c.model)?.lights_per_segment ?? drv(c.type).lights_per_segment?.[c.model] ?? 0;
const segCount = c => testsOf(c).includes("seg4");            // Govee: count with segment colours
const canCount = c => segCount(c) || (testsOf(c).includes("markers") && lpsOf(c) > 0);   // or segment markers
const canCheck = c => testsOf(c).includes("check") || testsOf(c).includes("ends");   // light 1 can be shown
const ipNum = ip => ip.split(".").reduce((a, n) => a * 256 + Number(n), 0);
function ctrlId(row) {
  const base = `${row.type}-${row.ip}${row.zone ? "-" + row.zone : ""}`.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32);
  let id = base, k = 2;
  while (W.cfg.controllers.some(c => c.id === id)) id = `${base.slice(0, 29)}-${k++}`;
  return id;
}
function newRun(c, name, lights) {
  return {name, short: name.slice(0, 12), subtitle: "", start: "", controller: c.id, lights: lights || null,
          light1: "", reverse: false, baseline: {brightness: 50, kelvin: 2200}};
}
function addController(row) {
  if (W.cfg.controllers.some(c => sameSpot(c, row))) return;
  const c = {id: ctrlId(row), type: row.type, model: row.model, ip: row.ip, name: "", enabled: true};
  if (row.zone) c.zone = row.zone;
  if (row.type === "tuya") { c.device_id = row.device_id || ""; c.version = row.version || "3.3"; }
  if (row.local_key) c.local_key = row.local_key;
  W.cfg.controllers.push(c);
  W.cfg.runs.push(newRun(c, row.zone || `Run ${W.cfg.runs.length + 1}`, row.lights));
}
function removeController(id) {
  W.cfg.controllers = W.cfg.controllers.filter(c => c.id !== id);
  W.cfg.runs = W.cfg.runs.filter(r => r.controller !== id);
}
const controllerBody = c => ({id: c.id, type: c.type, model: c.model, ip: c.ip, zone: c.zone, device_id: c.device_id,
                              version: c.version, local_key: c.local_key});
// One run per controller: the controller takes the run's name (names are typed in step 2).
function syncNames() {
  for (const r of W.cfg.runs) { const c = ctrlOf(r.controller); if (c) c.name = String(r.name || "").slice(0, 40); }
}
const light1Text = r => r.light1 === "left" ? "light 1 at the left end" : r.light1 === "right" ? "light 1 at the right end" : "light 1 not checked yet";

// --- step 1: find your lights ------------------------------------------------------------------
// W.found: rows from scans and "Add by address". Ticked rows are W.cfg.controllers (saved ones
// included); the list shows both. W.kinds[type]: {state: idle | asking | deep | done | error, msg, left}.
const usable = d => d.supported && !d.needs_key && !(d.type === "tuya" && !d.device_id);
function remember(rows) {
  for (const d of rows) {
    if (d.tier) W.tiers[`${d.type}|${d.model}`] = d.tier;
    const i = W.found.findIndex(f => sameSpot(f, d));
    if (i >= 0) W.found[i] = {...W.found[i], ...d}; else W.found.push(d);
    // Tuya rows are never ticked by themselves: plugs and bulbs use Smart Life too.
    if (W.autoTick && usable(d) && d.type !== "tuya" && !W.untick.has(spotKey(d))) addController(d);
  }
}
// Every row to show: found ones, plus chosen controllers no scan has found (yet).
function allRows() {
  const rows = [...W.found];
  for (const c of W.cfg.controllers) {
    if (!rows.some(d => sameSpot(d, c))) {
      const info = modelInfo(c.type, c.model);
      rows.push({type: c.type, model: c.model, ip: c.ip, zone: c.zone, device_id: c.device_id, version: c.version,
                 supported: true, tier: info?.tier, label: modelLabel(c.type, c.model), saved: true});
    }
  }
  return rows.sort((a, b) => KINDS.indexOf(a.type) - KINDS.indexOf(b.type) || ipNum(a.ip) - ipNum(b.ip)
    || String(a.zone || "").localeCompare(String(b.zone || "")));
}
// How many controllers of a kind are known: found or chosen, one per address.
function foundCount(t) {
  const ips = new Set();
  for (const x of [...W.found, ...W.cfg.controllers]) if (x.type === t) ips.add(x.ip);
  return ips.size;
}
function drawTiles() {
  const box = $("#tiles");
  box.innerHTML = "";
  for (const t of KINDS) {
    const k = W.kinds[t] || {state: "idle"}, n = foundCount(t), tile = el("div", `tile k-${t} ${k.state}`);
    const zones = t === "jellyfish" ? allRows().filter(d => d.type === t).length : 0;
    tile.append(el("span", "tname", KIND_NAME[t]), el("b", "tnum", String(n)));
    const sub = k.state === "asking" ? "Asking…" : k.state === "deep" ? `Deep scan, ${k.left ?? ""} s left`
      : k.state === "error" ? k.msg : t === "tuya" && !drv("tuya").available ? "needs tinytuya to use"
      : zones && zones !== n ? `${zones} zones` : k.state === "done" ? (n ? (t === "tuya" ? (n === 1 ? "device" : "devices") : n === 1 ? "controller" : "controllers") : "none found") : "";
    tile.append(el("small", "tsub", sub));
    if (k.state === "asking" || k.state === "deep") tile.setAttribute("aria-busy", "true");
    box.appendChild(tile);
  }
}
function drawFound() {
  const ul = $("#found");
  ul.innerHTML = "";
  const rows = allRows();
  if (!rows.length) { ul.appendChild(el("li", "fempty muted", "Nothing found yet: press Find my lights.")); return; }
  for (const d of rows) {
    const li = el("li", "frow" + (d.supported ? "" : " off"));
    const c = W.cfg.controllers.find(x => sameSpot(x, d));
    const cb = el("input"); cb.type = "checkbox"; cb.checked = !!c; cb.disabled = !d.supported;
    cb.setAttribute("aria-label", `Use ${d.label || d.type} at ${d.ip}`);
    cb.onchange = () => {
      if (cb.checked) { W.untick.delete(spotKey(d)); addController(d); }
      else { W.untick.add(spotKey(d)); const x = W.cfg.controllers.find(x => sameSpot(x, d)); if (x) removeController(x.id); }
      drawFound(); drawTiles();
    };
    const main = el("div", "fmain");
    const title = el("div", "ftitle");
    title.append(el("b", "", d.label || modelLabel(d.type, d.model)));
    if (d.zone && !String(d.label || "").includes(d.zone)) title.append(el("span", "fzone", `zone ${d.zone}`));
    main.append(title);
    const bits = [d.ip, d.lights ? `${d.lights} lights` : "", d.device_tail && !d.zone ? `…${d.device_tail}` : "",
                  d.saved ? "in your saved setup" : ""].filter(Boolean);
    main.append(el("small", "fsub", bits.join(" · ")));
    if (TIER_NOTE[d.tier]) main.append(el("small", "ftier", TIER_NOTE[d.tier]));
    if (d.type === "tuya") main.append(el("small", "ftier", "Could be a plug, bulb or other smart-home device, not your lights: "
      + "tick it only if it's your lights. To check, open each device in the Smart Life app, tap the pencil, then "
      + `Device Information, and look for the address ${d.ip}.`));
    if (!d.supported) {
      const why = el("small", "freason", (d.reason || "Not supported yet") + (d.install ? ": " : "."));
      if (d.install) why.append(el("code", "", d.install));
      main.append(why);
    }
    if (c && c.type === "tuya") main.append(tuyaFields(c));
    if (c && (W.info.configured || c.enabled === false)) {
      const lab = el("label", "fen"), en = el("input");
      en.type = "checkbox"; en.checked = c.enabled !== false; en.onchange = () => { c.enabled = en.checked; };
      lab.append(en, " Enabled");
      main.append(lab);
    }
    const badge = el("span", `badge k-${d.type}`, KIND_NAME[d.type].split(" /")[0]);
    li.append(cb, badge, main);
    ul.appendChild(li);
  }
}
// A chosen Tuya light needs its device id (if the scan didn't hear it), local key and version.
function tuyaFields(c) {
  const box = el("div", "row ftuya");
  if (!c.device_id || !W.found.find(d => sameSpot(d, c))?.device_id) {
    const dev = el("input"); dev.type = "text"; dev.placeholder = "device id"; dev.size = 20; dev.value = c.device_id || "";
    dev.setAttribute("aria-label", "Tuya device id"); dev.oninput = () => { c.device_id = dev.value.trim(); };
    box.append(dev);
  }
  const key = el("input"); key.type = "password"; key.size = 18; key.maxLength = 16; key.autocomplete = "off";
  key.placeholder = c.has_secret ? "key saved (type to change)" : "local key (16 characters)";
  key.setAttribute("aria-label", "Tuya local key");
  key.value = c.local_key || ""; key.oninput = () => { c.local_key = key.value.trim(); };
  const ver = el("select");
  ver.setAttribute("aria-label", "Tuya protocol version");
  for (const v of ["3.1", "3.2", "3.3", "3.4", "3.5"]) ver.appendChild(new Option(v, v));
  ver.value = c.version || "3.3"; ver.onchange = () => { c.version = ver.value; };
  box.append(key, ver);
  return box;
}

// One kind: a quick scan, or a deep one (keeps asking for up to DEEP_SECONDS, stops once it
// knows `expect` controllers). Errors stay on that kind's tile.
async function scanKind(t, deep, expect = 0) {
  const body = {types: [t], targets: $("#targets").value, deep};
  if (deep) {
    body.expect = expect ? {[t]: expect} : {};
    body.known = {[t]: [...new Set([...W.found, ...W.cfg.controllers].filter(x => x.type === t).map(x => x.ip))]};
  }
  W.kinds[t] = {...W.kinds[t], state: deep ? "deep" : "asking", msg: ""};
  drawTiles();
  try {
    const r = await api("/api/setup/discover", body);
    remember(r.devices || []);
    const prob = (r.problems || {})[t];
    W.kinds[t] = prob ? {state: "error", msg: prob} : {state: "done"};
  } catch (e) { W.kinds[t] = {state: "error", msg: e.message}; }
  drawTiles(); drawFound();
}
// A countdown on the tiles of the kinds in a deep scan (and in `show`, if given).
function countdown(kinds, show) {
  let left = W.info.deep_scan_seconds || 30;
  const tick = () => {
    for (const t of kinds) if (W.kinds[t]?.state === "deep") W.kinds[t].left = left;
    drawTiles();
    if (show) show(left);
  };
  tick();
  const id = setInterval(() => { left = Math.max(1, left - 1); tick(); }, 1000);
  return () => clearInterval(id);
}
function busy(on) { for (const b of $$("#scan, #deep, .kcard .again, .kcard .kdeep")) b.disabled = on; }
function problems() {
  return KINDS.filter(t => W.kinds[t]?.state === "error").map(t => `${KIND_NAME[t]}: ${W.kinds[t].msg}`).join(" · ");
}
function summary(deepRan) {
  const n = KINDS.map(t => [t, foundCount(t)]).filter(([, n]) => n);
  const zones = allRows().filter(d => d.type === "jellyfish").length;
  const parts = n.map(([t, k]) => `${k} ${KIND_NAME[t]}` + (t === "jellyfish" && zones > k ? ` (${zones} zones)` : ""));
  const short = KINDS.filter(t => W.counts[t] && foundCount(t) < W.counts[t])
    .map(t => `${KIND_NAME[t]}: found ${foundCount(t)} of ${W.counts[t]}${deepRan ? ", even with a deep scan" : ""}.`);
  const head = parts.length ? `Found ${parts.join(", ")}${deepRan ? " after a deep scan" : ""}.` : `Nothing answered${deepRan ? ", even in a deep scan" : ""}.`;
  return [head, ...short, parts.length ? "" : "Expecting more? Try a deep scan, add one by address, or see Not finding yours? below."]
    .filter(Boolean).join(" ") + (problems() ? " " + problems() : "");
}
// "Find my lights": every kind at once. Kinds where the user said how many (in "Not finding
// yours?") and some are missing get a deep scan by themselves.
async function findAll(deep = false) {
  err(""); busy(true);
  if (!deep) W.found = [];
  $("#scan-msg").textContent = deep ? "Deep scan: asking every address again, for longer." : "Asking every controller what it is…";
  let stop = deep ? countdown(KINDS) : () => {};
  try {
    // An asked-for deep scan stops early only when a kind still misses some of the number chosen.
    await Promise.all(KINDS.map(t => scanKind(t, deep, deep && W.counts[t] > foundCount(t) ? W.counts[t] : 0)));
    let deepRan = deep;
    const short = deep ? [] : KINDS.filter(t => W.counts[t] && foundCount(t) < W.counts[t] && W.kinds[t].state !== "error");
    if (short.length) {
      $("#scan-msg").textContent = "Didn't find them all: running a deep scan.";
      stop = countdown(short);
      await Promise.all(short.map(t => scanKind(t, true, W.counts[t])));
      deepRan = true;
    }
    stop();
    $("#scan-msg").textContent = summary(deepRan);
  } finally { stop(); busy(false); }
  drawFound(); drawKinds();
}

// "Add by address": every kind is asked at that one address; whatever answers is added.
async function addByAddress(ip, msgEl, extra = null) {
  ip = ip.trim();
  if (!validIp(ip)) { msgEl.textContent = "Type an address like 192.168.2.50."; return false; }
  msgEl.textContent = `Asking ${ip} what it is…`;
  let r;
  if (extra) r = await api("/api/setup/probe", {type: "tuya", ip, ...extra});    // Tuya with its id and key
  else r = await api("/api/setup/identify", {ip});
  const rows = r.devices || [];
  for (const d of rows) { W.untick.delete(spotKey(d)); if (extra) d.local_key = extra.local_key; }
  const before = W.autoTick;
  W.autoTick = true;                        // added on purpose: tick it
  remember(rows);
  W.autoTick = before;
  msgEl.textContent = extra ? `${ip}: the key works. Added.` : r.message;
  drawTiles(); drawFound(); drawKinds();
  return rows.length > 0;
}

// --- "Not finding yours?": one card per kind -------------------------------------------------
function drawKinds() {
  const box = $("#kinds");
  const msgs = Object.fromEntries($$(".kcard", box).map(k => [k.dataset.kind, $(".kmsg", k).textContent]));
  box.innerHTML = "";
  for (const t of KINDS) {
    const d = drv(t), h = HELP[t], card = el("div", "kcard");
    card.dataset.kind = t;
    card.append(el("b", "", d.label || KIND_NAME[t]), el("p", "kknow", h.know));
    if (h.note) card.append(el("p", "note", h.note));
    const ol = el("ol", "ksteps");
    for (const s of h.steps) {
      const li = el("li");
      if (s.includes("INSTALL_WIN")) {
        li.append("Install tinytuya: on Windows run ", el("code", "", INSTALL_TUYA.win), ", on Linux or a Raspberry Pi ",
          el("code", "", INSTALL_TUYA.nix), ", then start House Lights again.");
      } else li.textContent = s;
      ol.appendChild(li);
    }
    card.append(ol);
    if (t === "tuya") card.append(el("p", d.available ? "note ok-line" : "note warn", d.available ? "tinytuya is installed." : "tinytuya is not installed yet: Smart Life devices are found but can't be used."));
    // How many, look again, add by address
    const row = el("div", "row krow"), lab = el("label", "kcount");
    const sel = el("select");
    ["Not sure", ...Array.from({length: MAX_COUNT}, (_, i) => i + 1)].forEach((v, i) => sel.appendChild(new Option(String(v), String(i))));
    sel.value = String(W.counts[t] || 0);
    sel.onchange = () => { W.counts[t] = Number(sel.value); };
    lab.append(`How many ${KIND_NAME[t]} controllers?`, sel);
    const again = button(`Look for ${KIND_NAME[t]} again`, () => lookAgain(t, card), "again");
    row.append(lab, again);
    const add = el("div", "row kadd"), ip = el("input");
    ip.type = "text"; ip.placeholder = "192.168.2.50"; ip.size = 15; ip.setAttribute("aria-label", `${KIND_NAME[t]} address`);
    add.append(ip);
    let tuyaIn = null;
    if (t === "tuya" && d.available) {          // with tinytuya: check the key right away
      const dev = el("input"), key = el("input"), ver = el("select");
      dev.type = "text"; dev.placeholder = "device id"; dev.size = 20;
      key.type = "password"; key.placeholder = "local key"; key.maxLength = 16; key.size = 16; key.autocomplete = "off";
      for (const v of ["3.1", "3.2", "3.3", "3.4", "3.5"]) ver.appendChild(new Option(v, v));
      ver.value = "3.3";
      add.append(dev, key, ver);
      tuyaIn = () => ({device_id: dev.value.trim(), local_key: key.value.trim(), version: ver.value});
    }
    add.append(button("Add by address", async () => {
      try { if (await addByAddress(ip.value, $(".kmsg", card), tuyaIn && tuyaIn())) ip.value = ""; }
      catch (e) { $(".kmsg", card).textContent = e.message; }
    }));
    const msg = el("p", "note kmsg");
    msg.setAttribute("aria-live", "polite");
    msg.textContent = msgs[t] || "";
    card.append(row, add, msg);
    box.appendChild(card);
  }
}
// Quick scan for one kind. If it found fewer than the number chosen, a deep scan follows by
// itself; with "Not sure", a button offers one.
async function lookAgain(t, card) {
  const msg = () => $(`.kcard[data-kind=${t}] .kmsg`);         // the cards may be drawn again meanwhile
  const say = text => { const m = msg(); if (m) m.textContent = text; };
  busy(true);
  let stop = () => {};
  try {
    say(`Looking for ${KIND_NAME[t]}…`);
    await scanKind(t, false);
    const want = W.counts[t] || 0;
    let n = foundCount(t);
    if (W.kinds[t].state === "error") { say(W.kinds[t].msg); return; }
    if (want && n < want) {
      const head = `Found ${n} of ${want}. Didn't find them all: running a deep scan,`;
      stop = countdown([t], left => say(`${head} ${left} s left.`));
      await scanKind(t, true, want);
      stop();
      n = foundCount(t);
      say(n >= want ? `Found all ${want}.` : `Found ${n} of ${want}, even with a deep scan. Add the missing ${want - n === 1 ? "one" : "ones"} by address.`);
    } else if (want) say(`Found all ${want}.`);
    else {
      say(`Found ${n} ${KIND_NAME[t]} controller${n === 1 ? "" : "s"}. Expecting more? `);
      const m = msg();
      if (m) m.append(button("Deep scan, 30 s", async () => {
        busy(true);
        const st = countdown([t], left => say(`Deep scan: ${left} s left.`));
        try { await scanKind(t, true, 0); } finally { st(); busy(false); }
        const k = foundCount(t);
        say(`Found ${k} ${KIND_NAME[t]} controller${k === 1 ? "" : "s"} after a deep scan.`);
      }, "small kdeep"));
    }
  } finally { stop(); busy(false); }
}

// --- step 2: Spotlight. One controller at a time: it blinks, then you name what blinked ---------
// W.n: {order: [controller ids], i, nothing}
function startNaming() {
  W.n = {order: W.cfg.runs.map(r => r.controller).filter(id => ctrlOf(id)), i: 0, nothing: false};
}
async function toNamed(i) {
  const c = ctrlOf(W.n.order[W.n.i]);
  if (c) await stopTest(c);
  W.n.i = i; W.n.nothing = false;
  drawName(true);
}
function drawName(blink = false) {
  const n = W.n.order.length, c = ctrlOf(W.n.order[W.n.i]);
  const box = $("#n-one");
  if (!c) { box.replaceChildren(el("p", "muted", "No controllers yet: find them in step 1.")); return; }
  const r = runOf(c.id);
  $("#n-title").textContent = `Controller ${W.n.i + 1} of ${n}`;
  $("#n-sub").textContent = `${modelLabel(c.type, c.model)} · ${where(c)}` + (TIER_NOTE[tierOf(c)] ? ` · ${TIER_NOTE[tierOf(c)]}` : "");
  if (blink) runTest(c, "identify").then(() => drawName()).catch(e => err(e.message));
  const body = $("#n-body");
  body.innerHTML = "";
  const blinkBtn = button("Blink", async () => { await runTest(c, "identify"); blinkState(); }, "small");
  blinkBtn.id = "n-blink";
  body.append(answers(
    blinkBtn,
    button("Nothing blinked", () => { W.n.nothing = !W.n.nothing; drawName(); }, "small" + (W.n.nothing ? " on" : ""))));
  blinkState();
  if (W.n.nothing) {
    const ul = el("ul", "note help");
    for (const t of ["Is the controller powered on, and do its lights work in its own app?",
      ...(c.type === "govee" ? ["In the Govee Home app, open the device's settings and switch on LAN Control.",
        "Close the Govee app and stop any other program that drives these lights while you test."] : []),
      "Is this computer on the same network as the lights (not a guest network)?",
      "A firewall on this computer can block the messages: allow Python on private networks."])
      ul.appendChild(el("li", "", t));
    body.append(ul);
  }
  // name and short name
  const fields = el("div", "n-fields");
  fields.innerHTML = `<label class="fld"><span>What should we call these lights?</span><input type=text data-k=name maxlength=40 placeholder="Garage roofline"></label>
    <label class="fld"><span>Short name <small class="muted">on buttons, up to 12 letters</small></span><input type=text data-k=short maxlength=12 placeholder="Garage"></label>`;
  for (const inp of $$("input", fields)) {
    const k = inp.dataset.k;
    inp.value = r[k] ?? "";
    inp.onfocus = () => inp.select();       // a default like "Run 1": typing replaces it
    inp.oninput = () => {
      if (k === "name" && (!r.short || r.short === String(r.name || "").slice(0, 12))) { r.short = inp.value.slice(0, 12); $("[data-k=short]", fields).value = r.short; }
      r[k] = inp.value;
      if (k === "name") { syncNames(); drawSlots(); }
    };
  }
  body.append(fields);
  // place along the house
  body.append(q("Where is it on the house?"), el("p", "note", "Standing in front of the house, pick its place from left to right."));
  const slots = el("div", "slots");
  const drawSlots = () => {
    slots.innerHTML = "";
    W.cfg.runs.forEach((x, k) => {
      const mine = x === r;
      const b = button(mine ? (r.name || "This one") : (x.name || "not named yet"), () => {
        const a = W.cfg.runs, from = a.indexOf(r);
        a.splice(from, 1); a.splice(k, 0, r);
        drawSlots();
      }, "slot" + (mine ? " on" : x.name ? " named" : ""));
      b.title = `Place ${k + 1} from the left`;
      slots.appendChild(b);
    });
  };
  drawSlots();
  body.append(slots, el("p", "note", "Used to draw your house, and so moving patterns travel from one end of the house to the other."));
  // navigation between controllers
  const nav = $("#n-nav");
  nav.innerHTML = "";
  if (W.n.i > 0) nav.appendChild(button("◀ Previous controller", () => toNamed(W.n.i - 1), "ghost small"));
  nav.appendChild(el("span", "spacer"));
  nav.appendChild(button("Remove it from the setup", () => {
    if (!confirm(`Leave ${where(c)} out of the setup?`)) return;
    stopTest(c); removeController(c.id); startNaming(); W.n.i = Math.min(W.n.i, W.n.order.length - 1); drawName(W.n.order.length > 0);
  }, "ghost small"));
  if (W.n.i < n - 1) nav.appendChild(button("Next controller ▶", () => {
    if (!String(r.name || "").trim()) throw new Error("Give these lights a name first.");
    return toNamed(W.n.i + 1);
  }, "primary"));
}

// --- step 3: Tally. Count each run, one at a time, in order along the house ---------------------
// W.t: {order: [controller ids], i, phase: count | check | done, only: id or null, ...answers}
function startTests(only = null, phase = "count") {
  const order = only ? [only] : W.cfg.runs.map(r => r.controller).filter(id => ctrlOf(id));
  W.t = {order, i: 0, only, phase};
  resetAnswers();
}
function resetAnswers() { Object.assign(W.t, {recount: false, cnt: 0, markers: null, last: null, blocks: null, segs: null, q1: null, q2: null, dir: false, typed: false, started: false}); }
const curCtrl = () => ctrlOf(W.t.order[W.t.i]);
function setPhase(phase) { W.t.phase = phase; resetAnswers(); drawTest(); }
async function toController(i) {
  const c = curCtrl();
  if (c) await stopTest(c);
  W.t.i = i; W.t.phase = "count"; resetAnswers();
  drawTest();
}
function drawTest() {
  const c = curCtrl();
  if (!c) { $("#t-one").replaceChildren(el("p", "muted", "No controllers to count: add one in step 1.")); return; }
  const r = runOf(c.id), n = W.t.order.length;
  $("#test-intro").textContent = W.info.live
    ? "Each test shows on that run's lights. Look at the lights and answer."
    : "Practice mode: nothing is sent to the lights. The strip shows what they would do.";
  $("#t-title").textContent = W.t.only ? `Counting ${r.name}` : `${r.name} · run ${W.t.i + 1} of ${n}`;
  $("#t-sub").textContent = `${modelLabel(c.type, c.model)} · ${where(c)}`;
  const steps = ["count", ...(canCheck(c) ? ["check"] : []), "done"];
  const label = {count: "Count", check: "Check the ends", done: "Done"};
  $("#t-phases").innerHTML = "";
  for (const s of steps) $("#t-phases").appendChild(el("li", s === W.t.phase ? "on" : steps.indexOf(s) < steps.indexOf(W.t.phase) ? "done" : "", label[s]));
  $("#t-restore").textContent = RESTORE_NOTE[capsOf(c).restore] || "";
  if (!W.testing[c.id]) {                  // between tests: an unlit strip as long as the run
    if (hasLights(r)) dots(r.lights);
    $("#t-dots").hidden = W.t.phase === "done" || !hasLights(r);
  } else $("#t-dots").hidden = W.t.phase === "done";
  const body = $("#t-body");
  body.innerHTML = "";
  ({count: drawCountPhase, check: drawCheck, done: drawDone})[W.t.phase](c, r, body);
  const nav = $("#t-nav");
  nav.innerHTML = "";
  if (!W.t.only && W.t.i > 0) nav.appendChild(button("◀ Previous run", () => toController(W.t.i - 1), "ghost small"));
  nav.appendChild(el("span", "spacer"));
  if (W.t.phase !== "done") nav.appendChild(button(W.t.i < n - 1 ? "Skip this run" : "Skip", () => nextController(), "ghost small"));
  drawMore(c);
}
async function nextController() {
  if (W.t.i < W.t.order.length - 1) return toController(W.t.i + 1);
  await stopTest(curCtrl());
  return go(W.t.only ? 4 : 3);
}
const q = (text, cls = "tq") => el("p", cls, text);
const answers = (...btns) => { const row = el("div", "row answers"); row.append(...btns.filter(Boolean)); return row; };

// A. Count. Govee: segment colours, then the last segment red. Others: markers, or type it.
function drawCountPhase(c, r, body) {
  const lps = W.lps[c.id] || lpsOf(c) || 5, max = maxLights(c);
  if (hasLights(r) && !W.t.recount) {
    body.append(q(`${r.name} is set to ${r.lights} lights. Is that right?`), answers(
      button(canCheck(c) ? "Yes, check it" : "Yes", () => setPhase(canCheck(c) ? "check" : "done"), "primary"),
      button(canCount(c) ? "No, count them" : "No, change it", () => { W.t.recount = true; drawTest(); })));
    return;
  }
  const typed = () => {
    const inp = el("input"); inp.type = "number"; inp.min = 1; inp.max = max; inp.style.width = "6em";
    if (hasLights(r)) inp.value = r.lights;
    return answers(el("span", "lbl", "Number of lights"), inp, button("Use this number", () => {
      const v = Number(inp.value);
      if (!(v >= 1 && v <= max)) throw new Error(`Type a number from 1 to ${max}.`);
      r.lights = v; setPhase(canCheck(c) ? "check" : "done");
    }, "primary"));
  };
  if (!canCount(c) || W.t.typed) {
    body.append(q(W.t.typed ? "Type the number of lights from the Govee Home app." : `How many lights does ${r.name} have?`), typed());
    if (W.t.typed) body.append(answers(button("Count them instead", () => { W.t.typed = false; drawTest(); }, "ghost small")));
    return;
  }
  if (segCount(c)) return drawCountSegments(c, r, body, lps);
  // markers, then the red lights of the last segment
  body.append(q("Step 1: count the markers."),
    answers(button(W.t.cnt ? "Show the markers again" : "Show markers", async () => { await runTest(c, "markers"); W.t.cnt = Math.max(W.t.cnt, 1); drawTest(); }, "live")));
  if (W.t.cnt >= 1) {
    const m = el("input"); m.type = "number"; m.min = 1; m.max = Math.ceil(max / lps); m.style.width = "5em";
    if (W.t.markers) m.value = W.t.markers;
    body.append(el("p", "note", `Every ${lps} lights, one light is red or green; every 10th marker is blue. Count the markers along the whole run.`),
      answers(el("span", "lbl", "How many markers do you see?"), m, button("Next", async () => {
        const v = Number(m.value);
        if (!(v >= 1 && v <= Math.ceil(max / lps))) throw new Error(`Type a number from 1 to ${Math.ceil(max / lps)}.`);
        W.t.markers = v;
        await runTest(c, "tail", {markers: v}); W.t.cnt = 2; drawTest();
      }, "primary")));
  }
  if (W.t.cnt >= 2) body.append(...lastGroup(c, r, lps, W.t.markers, "Step 2: now the last group is red."));
  body.append(answers(button("Type the number instead", () => { W.t.typed = true; drawTest(); }, "ghost small")));
}
// "How many red lights at the end?" -> lps x (groups - 1) + red
function lastGroup(c, r, lps, groups, title) {
  const red = el("input"); red.type = "number"; red.min = 1; red.max = lps; red.style.width = "4em";
  const sum = el("p", "tsum");
  const use = button("Use this count", () => {
    const v = Number(red.value), n = lps * (groups - 1) + v;
    if (!(v >= 1 && v <= lps)) throw new Error(`Type a number from 1 to ${lps}.`);
    if (!(n >= 1 && n <= maxLights(c))) throw new Error(`That makes ${n}: count again.`);
    r.lights = n; setPhase(canCheck(c) ? "check" : "done");
  }, "primary");
  red.oninput = () => {
    const v = Number(red.value), ok = v >= 1 && v <= lps;
    sum.textContent = ok ? `${lps} × ${groups - 1} + ${v} = ${lps * (groups - 1) + v} lights` : "";
    use.textContent = ok ? `Use ${lps * (groups - 1) + v} lights` : "Use this count";
  };
  return [q(title), answers(el("span", "lbl", "How many red lights at the end?"), red), sum, answers(use)];
}
// Govee: A) every group of lps lights a colour in turn: green, white, red, yellow. The last
// colour and how many blocks of it give the groups. B) all white, the last group red.
const SEG_COLOURS = [["green", "#3a3"], ["white", "#ddd"], ["red", "#e33"], ["yellow", "#fb0"]];
function drawCountSegments(c, r, body, lps) {
  const maxGroups = Math.ceil(maxLights(c) / lps);
  if (!W.t.started) { W.t.started = true; runTest(c, "seg4").then(drawTest).catch(e => err(e.message)); }
  body.append(q(`A · Every ${lps} lights change colour: green, white, red, yellow, then again.`),
    answers(button("Show the colours again", () => runTest(c, "seg4"), "live small")),
    el("p", "note", "What colour is the last block at the far end? A single light past it that never changes isn't driven by the controller: leave it out."));
  body.append(answers(...SEG_COLOURS.map(([name, hex], k) => {
    const b = button(name[0].toUpperCase() + name.slice(1), () => { W.t.last = k; drawTest(); }, "swatch" + (W.t.last === k ? " on" : ""));
    b.style.setProperty("--sw", hex);
    return b;
  })));
  if (W.t.last != null) {
    const name = SEG_COLOURS[W.t.last][0];
    const m = el("input"); m.type = "number"; m.min = 1; m.max = Math.ceil(maxGroups / 4); m.style.width = "5em";
    if (W.t.blocks) m.value = W.t.blocks;
    const sum = el("span", "tsum");
    const groups = () => 4 * (Number(m.value) - 1) + W.t.last + 1;
    m.oninput = () => { sum.textContent = Number(m.value) >= 1 ? `= ${groups()} groups of ${lps}` : ""; };
    m.oninput();
    body.append(answers(el("span", "lbl", `How many ${name} blocks?`), m, sum, button("Next", async () => {
      const v = Number(m.value), g = groups();
      if (!(v >= 1 && g <= maxGroups)) throw new Error(`Count the ${name} blocks along the whole run.`);
      W.t.blocks = v; W.t.segs = g;
      await runTest(c, "seglast", {markers: g, lights: Math.min(maxLights(c), g * lps)}); W.t.cnt = 2; drawTest();
      const qs = $$("#t-body .tq");
      if (qs.length) qs[qs.length - 1].scrollIntoView({block: "center", behavior: "smooth"});
    }, "primary")));
  }
  if (W.t.cnt >= 2 && W.t.segs) {
    body.append(...lastGroup(c, r, lps, W.t.segs, "B · Now every group is white and only the last one is red."),
      el("p", "note", "Blue after the red? Then the colours were miscounted."),
      answers(button("Count the colours again", async () => { W.t.cnt = 1; W.t.segs = null; await runTest(c, "seg4"); drawTest(); }, "ghost small")));
  }
  body.append(answers(button("Type the number from the Govee app", () => { W.t.typed = true; drawTest(); }, "ghost small")));
}

// B. Check the ends: which end is light 1 (and, on WLED, nothing past the last light)
function drawCheck(c, r, body) {
  if (!hasLights(r)) { setPhase("count"); return; }
  if (testsOf(c).includes("ends")) return drawEnds(c, r, body);
  const shown = W.testing[c.id] === "check" || W.testing[c.id] === "chase";
  if (!W.t.started) { W.t.started = true; runTest(c, "check").then(drawTest).catch(e => err(e.message)); }
  body.append(q(`Light 1 should be red, light ${r.lights} (the last one) blue, the ones between dim white.`),
    answers(button(shown ? "Show it again" : "Show it", async () => { await runTest(c, "check"); W.t.dir = false; drawTest(); }, "live")));
  const set1 = v => { r.light1 = v; r.reverse = v === "right"; W.t.q1 = v || "unsure"; W.t.dir = false; drawTest(); };
  body.append(q("Where is the red light?"), answers(
    button("Yes, red is on the left", () => set1("left"), W.t.q1 === "left" ? "on" : ""),
    button("Yes, red is on the right", () => set1("right"), W.t.q1 === "right" ? "on" : ""),
    button("No / can't tell", async () => { W.t.q1 = "dot"; W.t.dir = true; await runTest(c, "chase"); drawTest(); }, W.t.q1 === "dot" || W.t.q1 === "unsure" ? "on" : "")));
  if (W.t.dir) {
    body.append(el("p", "note", "A white dot now runs from light 1 to the last light. Where does it start?"), answers(
      button("At the left end", () => set1("left")), button("At the right end", () => set1("right")),
      button("Still can't tell", () => set1(""))));
  }
  if (!W.t.q1 || W.t.q1 === "dot") return;
  body.append(q("Do you see any other colour, like orange, after the blue?"), answers(
    button("No, blue is the last light", () => setPhase("done"), "primary"),
    button("Yes, orange after the blue", () => { W.t.q2 = "orange"; drawTest(); }, W.t.q2 === "orange" ? "on" : ""),
    button("I don't see blue at all", () => { W.t.q2 = "noblue"; drawTest(); }, W.t.q2 === "noblue" ? "on" : "")));
  if (W.t.q2 === "orange") {
    const o = el("input"); o.type = "number"; o.min = 1; o.max = 20; o.style.width = "4em";
    body.append(answers(el("span", "lbl", "How many orange lights?"), o, button("Add them and check again", async () => {
      const v = Number(o.value);
      if (!(v >= 1 && v <= 20)) throw new Error("Type a number from 1 to 20.");
      if (r.lights + v > maxLights(c)) throw new Error(`That makes more than ${maxLights(c)} lights, the most this controller takes.`);
      r.lights += v; W.t.q2 = null;
      await runTest(c, "check"); drawTest();
    }, "primary")), el("p", "note", "If all 20 are orange, add them: the next check shows 20 more."));
  }
  if (W.t.q2 === "noblue") {
    body.append(el("p", "note", "Then the count is too high: the blue light is past the end of the run."),
      answers(button(canCount(c) ? "Count again" : "Change the number", () => { setPhase("count"); W.t.recount = true; drawTest(); }, "primary")));
  }
}
// Govee: a frame of exactly the count, light 1 blue and the last light red. Each is a single
// light only when the count is right (the controller spreads a frame over the whole run).
function drawEnds(c, r, body) {
  if (!W.t.started) { W.t.started = true; runTest(c, "ends").then(drawTest).catch(e => err(e.message)); }
  body.append(q(`C · Light 1 is blue and light ${r.lights}, the last one, is red. The rest are white.`),
    answers(button("Show it again", () => runTest(c, "ends"), "live small")),
    el("p", "note", "Are blue and red each a single light? Which end is blue?"));
  const set1 = v => { r.light1 = v; r.reverse = v === "right"; setPhase("done"); };
  body.append(answers(
    button("Blue is on the left", () => set1("left"), "primary"),
    button("Blue is on the right", () => set1("right"), "primary"),
    button("Not single lights", () => { W.t.q1 = "off"; drawTest(); }, W.t.q1 === "off" ? "on" : "")));
  if (W.t.q1 === "off") {
    body.append(el("p", "note", `Then ${r.lights} isn't quite right: the colours are spread over more or fewer lights.`),
      answers(button("Count again", () => { setPhase("count"); W.t.recount = true; drawTest(); }, "primary")));
  }
}

// C. Done: summary for this run, with a sweep in the chosen direction
function drawDone(c, r, body) {
  stopTest(c);
  const lights = hasLights(r) ? `${r.lights} lights` : "light count not set";
  body.append(el("p", "tsum", `${r.name}: ${lights}, ${light1Text(r)}.`));
  if (!canCheck(c)) {                        // can't show light 1: ask
    const sel = el("select");
    for (const [v, t] of Object.entries(LIGHT1)) sel.appendChild(new Option(t, v));
    sel.value = r.light1 || "";
    sel.onchange = () => { r.light1 = sel.value; r.reverse = sel.value === "right"; drawTest(); };
    body.append(answers(el("span", "lbl", "Light 1 is at the"), sel, el("span", "note", "as you face the lights")));
  }
  if (hasLights(r)) body.append(sweep(r));
  const last = W.t.i >= W.t.order.length - 1;
  body.append(answers(
    button(last ? (W.t.only ? "Done: check and save" : "Done: time and place") : "Next run ▶", () => nextController(), "primary"),
    button("Count it again", () => { setPhase("count"); W.t.recount = true; drawTest(); }, "ghost")));
}
function sweep(r) {
  const n = Math.min(r.lights, 60), wrap = el("div", "sweep"), strip = el("div", "sweep-dots");
  strip.style.gridTemplateColumns = `repeat(${n}, minmax(0, 1fr))`;
  strip.innerHTML = "<i></i>".repeat(n);
  const ends = el("div", "sweep-ends");
  const fromRight = r.light1 === "right";
  ends.append(el("span", "", fromRight ? "last light" : r.light1 ? "light 1" : "light 1?"), el("span", "", fromRight ? "light 1" : "last light"));
  wrap.append(strip, ends, el("p", "note", r.light1 ? "The dot runs from light 1, the way this controller counts its lights. The dashboard turns runs round as needed, so patterns run the same way along the house." : "Light 1 not checked yet: patterns may run the wrong way round on this run."));
  const dots = [...strip.children];
  let k = 0;
  clearInterval(W.sweepT);
  W.sweepT = setInterval(() => {
    if (!strip.isConnected) return clearInterval(W.sweepT);
    const p = k % (n + 10);
    dots.forEach((d, i) => {
      const j = fromRight ? n - 1 - i : i, dist = p - j;
      const on = dist >= 0 && dist < 6;
      d.style.background = j === 0 ? "#ff3b30" : on ? `rgba(255, 190, 92, ${1 - dist / 6})` : "";
    });
    k++;
  }, 60);
  return wrap;
}

// More tests: the extra patterns (colours, segment groups, ruler, dot from light 1)
const COUNT_TESTS = ["markers", "tail", "seg4", "seglast", "ends", "check"];
function drawMore(c) {
  const box = $("#t-more-btns");
  box.innerHTML = "";
  for (const name of testsOf(c)) {
    if (COUNT_TESTS.includes(name)) continue;
    box.appendChild(button(W.info.tests[name], () => runTest(c, name), "live small" + (W.testing[c.id] === name ? " on" : "")));
  }
  box.appendChild(button("Stop", () => stopTest(c), "danger small"));
}

const ui = s => $(`#${W.step === 1 ? "n" : "t"}-${s}`);
function dots(n) {
  const d = ui("dots");
  n = Math.max(1, Math.min(3000, Number(n) || 1));
  if (d.children.length !== n) {
    d.style.gridTemplateColumns = `repeat(${Math.min(n, 60)}, minmax(0, 1fr))`;
    d.innerHTML = "<i></i>".repeat(n);
  }
  return [...d.children];
}
async function runTest(c, name, extra = {}) {
  const r = runOf(c.id);
  const body = {controller: controllerBody(c), lights: hasLights(r) ? r.lights : Math.min(maxLights(c), 50),
                reverse: false, test: name, ...extra};       // tests show where light 1 really is
  const res = await api("/api/setup/test", body);
  W.testing[c.id] = name;
  W.lps[c.id] = res.lights_per_segment;
  ui("status").textContent = (res.live ? "On the lights now." : "Practice mode: logged only.")
    + (TEST_HELP[name] && !["identify", "chase"].includes(name) ? " " + TEST_HELP[name] : "")
    + (res.slow ? " (This controller changes about once a second.)" : "")
    + (res.stream_untested && name === "check" ? " This model hasn't been seen playing light by light yet: if the lights show red, dim white and blue as on the strip, it can play light-by-light themes; if they don't change, it can't (please report what you see)." : "")
    + (name === "check" && res.frame_lights > body.lights ? ` The strip shows what is sent: the ${res.frame_lights - body.lights} orange lights are past the count, so real lights only show them if the count is too low.` : "");
  const pv = await api("/api/setup/preview", body);
  ui("dots").hidden = false;
  animate(c.id, pv, res.stays ? Infinity : res.seconds);
  if (res.stays) ui("status").textContent += " It stays on the lights until the next test.";
  return res;
}
async function stopTest(c) {
  if (!c) return;
  clearInterval(W.anim);
  if (W.testing[c.id]) {
    delete W.testing[c.id];
    try { await api("/api/setup/test/stop", {ip: c.ip, zone: c.zone || ""}); } catch (e) { err(e.message); }
  }
  if (ui("dots")) for (const i of ui("dots").children) { i.style.background = ""; i.style.boxShadow = ""; }
  if (ui("status")) ui("status").textContent = "";
  blinkState();
}
// Spotlight's Blink button stays lit (like Next controller) while the controller blinks.
function blinkState() {
  const b = $("#n-blink"), c = W.n && ctrlOf(W.n.order[W.n.i]);
  if (!b || !c) return;
  const on = W.testing[c.id] === "identify";
  b.className = on ? "primary small" : "live small";
  b.textContent = on ? "● Blinking: press to blink again" : "Blink again";
}
function animate(cid, pv, seconds) {
  clearInterval(W.anim);
  const els = dots(pv.frames[0].length), t0 = performance.now();
  let k = 0;
  const paint = () => {
    const f = pv.frames[k % pv.frames.length];
    f.forEach((c, i) => { const on = c !== "#000000"; els[i].style.background = on ? c : ""; els[i].style.boxShadow = on ? `0 0 5px ${c}` : ""; });
    k++;
    if (performance.now() - t0 > seconds * 1000) {
      clearInterval(W.anim); delete W.testing[cid];
      ui("status").textContent = "The test ended by itself.";
      blinkState();
    }
  };
  paint();
  if (pv.animated) W.anim = setInterval(paint, 1000 / pv.fps);
}
async function stopAllTests() {
  if (Object.keys(W.testing).length) { try { await api("/api/setup/test/stop", {}); } catch (e) { /* server may be restarting */ } }
  clearInterval(W.anim); clearInterval(W.sweepT);
  W.testing = {};
}

// --- step 4: time and place --------------------------------------------------------------------------
const browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "";
function drawPlace() {
  const tz = $("#tz");
  if (!tz.value) tz.value = W.cfg.timezone && W.cfg.timezone !== "UTC" ? W.cfg.timezone : (browserTz() || "UTC");
  if (!$("#tz-list").children.length && Intl.supportedValuesOf)
    $("#tz-list").innerHTML = Intl.supportedValuesOf("timeZone").map(z => `<option value="${z}">`).join("");
  showTz();
  const loc = W.cfg.location || {};
  if ($("#lat").value === "" && loc.lat != null) $("#lat").value = loc.lat;
  if ($("#lon").value === "" && loc.lon != null) $("#lon").value = loc.lon;
  if ($("#zip").value === "" && loc.zip) $("#zip").value = loc.zip;
  W.place = W.place || (loc.zip || loc.place ? {zip: loc.zip, place: loc.place, lat: loc.lat, lon: loc.lon} : null);
  if (loc.lat != null && !loc.zip) $("#ll").hidden = false;
  for (const r of $$("input[name=mode]")) r.checked = r.value === (W.cfg.mode || "live");
  if (W.info.forced_dry && !$("#modes .forced")) $("#modes").insertAdjacentHTML("beforeend", '<span class="muted forced">The server was started with --dry, so it stays in practice mode for now.</span>');
  sunLine();
}
function showTz() {
  const v = $("#tz").value.trim();
  $("#tz-show").textContent = v || "UTC";
  $("#tz-src").textContent = v && v === browserTz() ? "(from this device)" : "";
}
function readPlace() {
  W.cfg.timezone = $("#tz").value.trim() || "UTC";
  const lat = $("#lat").value, lon = $("#lon").value;
  W.cfg.location = lat === "" && lon === "" ? null : {lat: Number(lat), lon: Number(lon)};
  if (W.cfg.location && W.place && Number(W.place.lat) === Number(lat) && Number(W.place.lon) === Number(lon)) {
    if (W.place.zip) W.cfg.location.zip = W.place.zip;
    if (W.place.place) W.cfg.location.place = W.place.place;
  }
  const m = $$("input[name=mode]").find(r => r.checked);
  W.cfg.mode = m ? m.value : "live";
}
const clock = hm => { const [h, m] = hm.split(":").map(Number); return new Date(2000, 0, 1, h, m).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}); };
let sunSeq = 0;
async function sunLine() {
  const lat = $("#lat").value, lon = $("#lon").value, tz = $("#tz").value.trim() || "UTC", msg = $("#sun-msg"), seq = ++sunSeq;
  if (lat === "" || lon === "") { msg.textContent = ""; msg.className = "note"; return; }
  try {
    const s = await api(`/api/setup/sun?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&tz=${encodeURIComponent(tz)}`);
    if (seq !== sunSeq) return;
    const here = W.place && W.place.place && Number(W.place.lat) === Number(lat) ? W.place.place + ": sunrise" : "Sunrise";
    const zip = W.place && W.place.zip && Number(W.place.lat) === Number(lat) ? `ZIP ${W.place.zip}` : "this location";
    if (!s.tz_ok) {
      msg.className = "note warn";
      msg.textContent = `That time zone doesn't look right for ${zip}: ${s.sunset ? `sunset would be at ${clock(s.sunset)}` : `noon would be at ${clock(s.noon)}`}. Pick a different one?`;
      $("#tz-edit").hidden = false;
    } else {
      msg.className = "note ok-line";
      msg.textContent = s.sunrise && s.sunset ? `${here} ${clock(s.sunrise)}, sunset ${clock(s.sunset)} today.`
        : "The sun doesn't rise or set there today.";
    }
  } catch (e) { if (seq === sunSeq) { msg.className = "note warn"; msg.textContent = e.message; } }
}
async function zipLookup() {
  const code = $("#zip").value.trim();
  if (!code) return err("Type a ZIP code.");
  $("#zip-go").disabled = true;
  try {
    const r = await api(`/api/setup/zip?code=${encodeURIComponent(code)}&country=${encodeURIComponent($("#country").value)}`);
    W.place = r;
    $("#lat").value = r.lat; $("#lon").value = r.lon;
    await sunLine();
  } catch (e) {
    $("#sun-msg").className = "note warn"; $("#sun-msg").textContent = e.message;
    if (/latitude/.test(e.message)) $("#ll").hidden = false;
  } finally { $("#zip-go").disabled = false; }
}
function geolocate() {
  const msg = $("#geo-msg");
  if (!navigator.geolocation) { msg.textContent = "This browser can't share its location."; return; }
  msg.textContent = "Asking…";
  navigator.geolocation.getCurrentPosition(p => {
    $("#lat").value = p.coords.latitude.toFixed(2); $("#lon").value = p.coords.longitude.toFixed(2); msg.textContent = "";
    W.place = null; $("#ll").hidden = false; sunLine();
  }, () => { msg.textContent = "Not available here (browsers only share location on https or localhost). Use the ZIP code instead."; });
}

// --- step 5: save ------------------------------------------------------------------------------------
function drawSummary() {
  syncNames();
  const t = document.createElement("table");
  t.innerHTML = "<thead><tr><th></th><th>Run</th><th># Lights</th><th>Light 1 is at</th><th>Controller</th><th></th></tr></thead><tbody></tbody>";
  W.cfg.runs.forEach((r, i) => {
    const c = ctrlOf(r.controller);
    if (!c) return;
    const tr = t.tBodies[0].insertRow();
    tr.insertCell().textContent = `${i + 1}.`;
    tr.insertCell().textContent = r.name + (c.enabled === false ? " (disabled)" : "");
    const lc = tr.insertCell();
    lc.textContent = hasLights(r) ? r.lights : "not set";
    if (!hasLights(r)) lc.className = "err";
    tr.insertCell().textContent = r.light1 === "left" ? "Left" : r.light1 === "right" ? "Right" : "Not checked";
    tr.insertCell().textContent = `${modelLabel(c.type, c.model)} · ${where(c)}`;
    const links = tr.insertCell();
    links.className = "links";
    const a = (text, fn) => { const x = el("a", "", text); x.href = "#"; x.onclick = e => { e.preventDefault(); fn(); }; return x; };
    links.append(a("Rename", () => go(1)), " · ", a("Count it", () => { startTests(c.id); go(2, true); }));
  });
  const loc = W.cfg.location;
  const p = el("p", "", `Mode: ${W.cfg.mode === "live" ? "Live" : "Practice"} · Time zone: ${W.cfg.timezone} · Location: ${
    loc ? (loc.place ? `${loc.place}${loc.zip ? " " + loc.zip : ""}` : `${loc.lat}, ${loc.lon}`) : "not set"}`);
  $("#summary").replaceChildren(t, el("p", "note", "Runs are listed left to right along the house."), p);
  $("#save-where").textContent = `Saved to ${inHome(W.info.home, "config.json")} (keys such as Tuya's go to secrets.json, readable only by you). The server restarts with it.`;
}
async function save() {
  const msg = check(0) || check(1) || check(4);
  if (msg) return err(msg);
  err(""); $("#next").disabled = true; $("#prev").disabled = true;
  await stopAllTests();
  syncNames();
  for (const r of W.cfg.runs) r.reverse = r.light1 === "right";
  try {
    await api("/api/setup/save", {config: W.cfg});
    $("#save-msg").innerHTML = '<span class="ok">Saved.</span> Restarting the server…';
    await waitForRestart();
  } catch (e) { err(e.message); $("#next").disabled = false; $("#prev").disabled = false; }
}
async function waitForRestart() {
  await new Promise(r => setTimeout(r, 2500));
  for (let k = 0; k < 40; k++) {
    try { const c = await api("/api/config"); if (c.configured) { location.href = "./"; return; } } catch (e) { /* not up yet */ }
    await new Promise(r => setTimeout(r, 750));
  }
  $("#save-msg").innerHTML = '<span class="ok">Saved.</span> The server didn\'t come back by itself: start it again, then open the dashboard.';
}

// --- navigation ----------------------------------------------------------------------------------
function check(step) {
  if (step === 0) {
    if (!W.cfg.controllers.length) return "Tick at least one controller, or add one by address.";
    const noId = W.cfg.controllers.find(c => c.type === "tuya" && !/^[A-Za-z0-9]{8,40}$/.test(c.device_id || ""));
    if (noId) return `Type the device id for the Tuya device at ${noId.ip}.`;
    const noKey = W.cfg.controllers.find(c => c.type === "tuya" && !c.has_secret && !(c.local_key && c.local_key.length === 16));
    if (noKey) return `Type the 16-character local key for the Tuya device at ${noKey.ip}.`;
  }
  if (step === 1) {
    const r = W.cfg.runs.find(r => !String(r.name || "").trim());
    if (r) return `Give every run a name: the one at ${where(ctrlOf(r.controller))} has none yet.`;
    const names = W.cfg.runs.map(r => String(r.name).trim().toLowerCase());
    if (new Set(names).size !== names.length) return "Give each run a different name.";
  }
  if (step === 4) {
    const r = W.cfg.runs.find(r => !hasLights(r));
    if (r) return `${r.name}: how many lights? Count it in step 3.`;
  }
  return "";
}
// keepTests: step 3 (Tally) was set up by the caller (a deep link or a "Count it" link).
async function go(step, keepTests = false) {
  if (step > W.step) for (let s = W.step; s < step; s++) { const msg = check(s); if (msg) { if (s !== W.step) await go(s); return err(msg); } }
  err("");
  if ((W.step === 1 || W.step === 2) && step !== W.step) await stopAllTests();
  if (W.step === 3) readPlace();
  if (W.step === 1) syncNames();
  W.step = step;
  $$("[data-page]").forEach(p => { p.hidden = Number(p.dataset.page) !== step; });
  $$("#steps li").forEach(li => {
    const s = Number(li.dataset.step);
    li.className = (s === step ? "on" : s < step ? "done" : "") + (W.jump ? " jump" : "");
  });
  $("#prev").hidden = step === 0;
  $("#next").textContent = step === STEPS - 1 ? "Save and start" : "Next";
  if (step === 0) { drawTiles(); drawFound(); drawKinds(); }
  if (step === 1) { startNaming(); drawName(true); }
  if (step === 2) { if (!keepTests || !W.t) startTests(); drawTest(); }
  if (step === 3) drawPlace();
  if (step === 4) drawSummary();
  scrollTo(0, 0);
}

// --- light / dark (the same choice as on the dashboard: saved in this browser) -------------------
function curTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
function paintTheme() {
  $("#th-light").classList.toggle("on", curTheme() === "light");
  $("#th-dark").classList.toggle("on", curTheme() === "dark");
}
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("hl-theme", t); } catch (e) { /* private window: this page only */ }
  paintTheme();
}

async function init() {
  $("#th-light").onclick = () => setTheme("light");
  $("#th-dark").onclick = () => setTheme("dark");
  paintTheme();
  W.info = await api("/api/setup");
  W.cfg = JSON.parse(JSON.stringify(W.info.config));
  W.cfg.controllers = Array.isArray(W.cfg.controllers) ? W.cfg.controllers : [];
  W.cfg.runs = Array.isArray(W.cfg.runs) ? W.cfg.runs : [];
  for (const r of W.cfg.runs) if (r.light1 == null) r.light1 = r.reverse ? "right" : "";
  const ips = {};
  for (const c of W.cfg.controllers) (ips[c.type] ||= new Set()).add(c.ip);
  for (const [t, s] of Object.entries(ips)) W.counts[t] = Math.min(s.size, MAX_COUNT);  // running the wizard again
  for (const c of W.cfg.controllers) {
    if (!W.cfg.runs.some(r => r.controller === c.id)) W.cfg.runs.push(newRun(c, c.name || c.ip, null));
  }
  // Editing a saved setup: newly found controllers aren't ticked by themselves.
  W.autoTick = !W.cfg.controllers.length;
  const pill = $("#mode");
  pill.textContent = W.info.live ? "Live" : "Practice";
  pill.className = "pill " + (W.info.live ? "live" : "dry");
  const b = $("#banner");
  if (W.info.error) { b.hidden = false; b.textContent = `Your settings file has a problem: ${W.info.error}. Go through the steps to fix it.`; }
  else if (W.info.configured) $("#back").hidden = false;
  else { b.hidden = false; b.textContent = "Welcome! No settings yet: this wizard sets up your lights. It takes a few minutes."; }
  $("#scan").onclick = () => findAll(false).catch(e => err(e.message));
  $("#targets").onkeydown = e => { if (e.key === "Enter") $("#scan").click(); };
  $("#deep").onclick = () => findAll(true).catch(e => err(e.message));
  const addIp = async () => {
    $("#add").disabled = true;
    try { if (await addByAddress($("#add-ip").value, $("#add-msg"))) $("#add-ip").value = ""; }
    catch (e) { $("#add-msg").textContent = e.message; }
    $("#add").disabled = false;
  };
  $("#add").onclick = addIp;
  $("#add-ip").onkeydown = e => { if (e.key === "Enter") addIp(); };
  $("#geo").onclick = e => { e.preventDefault(); geolocate(); };
  $("#ll-show").onclick = e => { e.preventDefault(); $("#ll").hidden = !$("#ll").hidden; };
  $("#tz-change").onclick = e => { e.preventDefault(); $("#tz-edit").hidden = !$("#tz-edit").hidden; if (!$("#tz-edit").hidden) $("#tz").focus(); };
  $("#tz").oninput = () => { showTz(); };
  $("#tz").onchange = () => { showTz(); sunLine(); };
  $("#zip-go").onclick = zipLookup;
  $("#zip").onkeydown = e => { if (e.key === "Enter") zipLookup(); };
  for (const id of ["#lat", "#lon"]) $(id).onchange = () => sunLine();
  $("#prev").onclick = () => go(W.step - 1);
  $("#next").onclick = () => (W.step === STEPS - 1 ? save() : go(W.step + 1));
  addEventListener("pagehide", () => { if (Object.keys(W.testing).length) navigator.sendBeacon && navigator.sendBeacon("/api/setup/test/stop", new Blob(["{}"], {type: "application/json"})); });
  // With a saved config every step can be opened from the list at the top.
  W.jump = !W.info.error && W.cfg.runs.length > 0 && W.cfg.controllers.length > 0;
  for (const li of $$("#steps li")) li.onclick = () => { if (W.jump && Number(li.dataset.step) !== W.step) go(Number(li.dataset.step)); };
  // Deep links: ?step=count&controller=<id> (or test), ?step=place (or the step's number, 1 to 5)
  const qs = new URLSearchParams(location.search), sv0 = String(qs.get("step") || "").toLowerCase(), sv = STEP_ALIAS[sv0] || sv0;
  const want = STEP_NAMES.includes(sv) ? STEP_NAMES.indexOf(sv) : /^[1-9]$/.test(sv) ? Number(sv) - 1 : -1;
  if (W.jump && want >= 0 && want < STEPS) {
    const cid = qs.get("controller");
    if (want === 2 && cid && ctrlOf(cid)) { startTests(cid); return go(2, true); }
    return go(want);
  }
  go(0);
}

init().catch(e => err(e.message));
