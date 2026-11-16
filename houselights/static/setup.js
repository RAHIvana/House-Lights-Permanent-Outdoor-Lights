"use strict";
// Setup wizard: pick the kinds of lights, find controllers, name and count the runs, test them
// one controller at a time, set the time zone and location, then save config.json (the server
// restarts with it).
// Deep links: setup.html?step=4&controller=<id> tests only that controller; ?step=5 opens at
// "Time and place". With a saved config, every step at the top can be clicked.
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

const W = {step: 0, info: null, cfg: null, found: [], types: new Set(), counts: {}, testing: {}, anim: null, lps: {},
           t: null, jump: false};
const MAX_COUNT = 12;                      // "How many controllers?" choices; 0 = not sure
const STEPS = 6;
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
const modelLabel = (type, model) => drv(type).models[model] || model;
const maxLights = c => drv(c.type).max_lights?.[c.model] || 3000;
const ctrlOf = cid => W.cfg.controllers.find(c => c.id === cid);
const runOf = cid => W.cfg.runs.find(r => r.controller === cid);
const where = c => c.ip + (c.zone ? ` · ${c.zone}` : "");
const sameSpot = (a, b) => a.ip === b.ip && (a.zone || "") === (b.zone || "");
const hasLights = r => Number(r.lights) >= 1;
const canCount = c => drv(c.type).tests.includes("markers");       // Govee: count with markers
const canCheck = c => drv(c.type).tests.includes("check");         // Govee, WLED: red / blue / orange
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
  if (row.device_id) { c.device_id = row.device_id; c.version = row.version || "3.3"; }
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
// One run per controller: the controller takes the run's name (names are typed in step 3).
function syncNames() {
  for (const r of W.cfg.runs) { const c = ctrlOf(r.controller); if (c) c.name = String(r.name || "").slice(0, 40); }
}
const light1Text = r => r.light1 === "left" ? "light 1 at the left end" : r.light1 === "right" ? "light 1 at the right end" : "light 1 not checked yet";

// --- step 1: kinds of lights -------------------------------------------------------------------
function drawDrivers() {
  $("#drivers").innerHTML = "";
  for (const d of W.info.drivers) {
    const l = document.createElement("label");
    if (!d.available) l.className = "off";
    l.innerHTML = `<input type="checkbox"><span><b></b><small class="m"></small><small class="n"></small></span>`;
    $("b", l).textContent = d.label;
    $(".m", l).textContent = d.available ? Object.values(d.models).join(", ") : d.reason;
    $(".n", l).textContent = d.note;
    const r = $("input", l);
    r.value = d.type; r.disabled = !d.available; r.checked = W.types.has(d.type);
    if (d.available) {                     // how many: the scan then knows when it has found them all
      const row = document.createElement("small");
      row.className = "count";
      row.innerHTML = `How many controllers? <select>${["Not sure", ...Array.from({length: MAX_COUNT}, (_, i) => i + 1)]
        .map((v, i) => `<option value="${i}">${v}</option>`).join("")}</select>`;
      const sel = $("select", row);
      sel.value = String(W.counts[d.type] || 0);
      sel.onchange = () => {
        W.counts[d.type] = Number(sel.value);
        if (W.counts[d.type] && !r.checked) { r.checked = true; W.types.add(d.type); }
      };
      $("span", l).appendChild(row);
    }
    r.onchange = () => { r.checked ? W.types.add(d.type) : W.types.delete(d.type); };
    $("#drivers").appendChild(l);
  }
}

// How many controllers of each kind are known so far: scanned or chosen, one per address.
function foundCounts() {
  const ips = {};
  for (const x of [...W.found.filter(d => d.supported), ...W.cfg.controllers]) (ips[x.type] ||= new Set()).add(x.ip);
  return Object.fromEntries(Object.entries(ips).map(([t, s]) => [t, s.size]));
}
const missingTypes = () => { const have = foundCounts(); return [...W.types].filter(t => W.counts[t] && (have[t] || 0) < W.counts[t]); };
function countNote(afterDeep = false) {
  const have = foundCounts();
  return [...W.types].filter(t => W.counts[t]).map(t => {
    const n = have[t] || 0, want = W.counts[t], name = drv(t).label.split(" (")[0], miss = want - n === 1 ? "one" : "ones";
    return n >= want ? `${name}: found all ${want}.`
      : afterDeep ? `${name}: found ${n} of ${want}, even with a deep scan. Add the missing ${miss} by address below.`
      : `${name}: found ${n} of ${want}. Run a deep scan, or add the missing ${miss} by address below.`;
  }).join(" ");
}
function showCount() { const n = countNote(); if (n) $("#scan-msg").textContent = n; }

// --- step 2: controllers ----------------------------------------------------------------------
function drawFound() {
  const tb = $("#found tbody");
  tb.innerHTML = "";
  if (!W.found.length) { tb.innerHTML = '<tr><td colspan="6" class="muted">Nothing scanned yet.</td></tr>'; return; }
  for (const d of W.found) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td><input type=checkbox></td><td></td><td></td><td></td><td></td><td class=muted></td>";
    const cb = $("input", tr), used = W.cfg.controllers.some(c => sameSpot(c, d));
    cb.checked = used; cb.disabled = !d.supported;
    cb.onchange = () => {
      if (cb.checked) addController(d);
      else { const c = W.cfg.controllers.find(x => sameSpot(x, d)); if (c) removeController(c.id); }
      drawChosen();
    };
    tr.cells[1].textContent = d.ip; tr.cells[2].textContent = d.label;
    tr.cells[3].textContent = d.zone || (d.device_tail ? "…" + d.device_tail : "");
    tr.cells[4].textContent = d.lights || "";
    tr.cells[5].textContent = !d.supported ? "not supported yet" : d.needs_key ? "needs its local key" : "";
    tb.appendChild(tr);
  }
}
function drawChosen() {
  const tb = $("#chosen tbody");
  tb.innerHTML = "";
  if (!W.cfg.controllers.length) { tb.innerHTML = '<tr><td colspan="5" class="muted">None yet: scan, or add one by address.</td></tr>'; return; }
  for (const c of W.cfg.controllers) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td></td><td></td><td class=extra></td><td><input type=checkbox class=en></td><td><button class='small danger'>Remove</button></td>";
    tr.cells[0].textContent = where(c); tr.cells[1].textContent = modelLabel(c.type, c.model);
    const en = $(".en", tr);
    en.checked = c.enabled !== false; en.onchange = () => { c.enabled = en.checked; };
    if (c.type === "tuya") {
      const box = $(".extra", tr);
      box.innerHTML = `<input type=password class=key size=18 maxlength=16 autocomplete=off>
        <select class=ver>${["3.1", "3.2", "3.3", "3.4", "3.5"].map(v => `<option>${v}</option>`).join("")}</select>`;
      const key = $(".key", box), ver = $(".ver", box);
      key.placeholder = c.has_secret ? "key saved (type to change)" : "local key (16 characters)";
      key.value = c.local_key || ""; key.oninput = () => { c.local_key = key.value.trim(); };
      ver.value = c.version || "3.3"; ver.onchange = () => { c.version = ver.value; };
    }
    $("button", tr).onclick = () => { removeController(c.id); drawChosen(); drawFound(); showCount(); };
    tb.appendChild(tr);
  }
}
function drawAddRow() {
  const sel = $("#add-type");
  sel.innerHTML = "";
  for (const d of W.info.drivers.filter(d => d.available && W.types.has(d.type))) sel.appendChild(new Option(d.label, d.type));
  sel.hidden = sel.options.length === 1;   // one kind ticked: nothing to choose, just say which
  const extra = () => {
    const box = $("#add-extra"), models = Object.entries(drv(sel.value).models);
    box.innerHTML = "";
    let kind = sel.hidden ? drv(sel.value).label : "";
    if (sel.value === "govee") {
      box.innerHTML = "<select id=add-model></select>";
      for (const [m, label] of models) $("#add-model").appendChild(new Option(label, m));
      if (models.length === 1) { $("#add-model").hidden = true; kind = [kind, models[0][1]].filter(Boolean).join(" · "); }
    } else if (sel.value === "tuya") {
      box.innerHTML = `<input type=text id=add-dev size=22 placeholder="device id">
        <input type=password id=add-key size=18 maxlength=16 placeholder="local key" autocomplete=off>
        <select id=add-ver>${["3.1", "3.2", "3.3", "3.4", "3.5"].map(v => `<option${v === "3.3" ? " selected" : ""}>${v}</option>`).join("")}</select>`;
    }
    $("#add-kind").textContent = kind;
    $("#add-kind").hidden = !kind;
  };
  sel.onchange = extra;
  extra();
  $("#add-row").hidden = !sel.options.length;
}
function drawTypeNotes() {
  $("#type-notes").innerHTML = "";
  for (const d of W.info.drivers.filter(d => W.types.has(d.type))) {
    const li = document.createElement("li");
    li.textContent = `${d.label}: ${d.note}`;
    $("#type-notes").appendChild(li);
  }
}
// Quick scan first. If the user said how many controllers and some are missing, a deep scan
// follows by itself; otherwise "Missing lights? Run deep scan" offers one.
async function discover(types, deep, expect) {
  const body = {types, targets: $("#targets").value, deep};
  if (deep) {
    body.expect = expect ? Object.fromEntries(types.filter(t => W.counts[t]).map(t => [t, W.counts[t]])) : {};
    body.known = {};
    for (const x of [...W.found, ...W.cfg.controllers]) if (types.includes(x.type)) (body.known[x.type] ||= []).push(x.ip);
  }
  const r = await api("/api/setup/discover", body);
  for (const d of r.devices) if (!W.found.some(f => f.type === d.type && sameSpot(f, d))) W.found.push(d);
  return r.problems || {};
}
function countdown(text) {
  let left = W.info.deep_scan_seconds || 30;
  const show = () => { $("#scan-msg").textContent = `${text} About ${left} s left…`; };
  show();
  const t = setInterval(() => { left = Math.max(1, left - 1); show(); }, 1000);
  return () => clearInterval(t);
}
async function scan(forceDeep = false) {
  err(""); $("#scan").disabled = $("#deep").disabled = true;
  const autoAdd = !W.cfg.controllers.length;
  let probs = {}, deepRan = false, stop = () => {};
  try {
    if (!forceDeep) {
      W.found = [];
      $("#scan-msg").textContent = "Scanning…";
      probs = await discover([...W.types], false, true);
    }
    const short = missingTypes();
    if (forceDeep || short.length) {
      drawFound();
      stop = countdown(forceDeep ? "Deep scan: asking every address again, for longer."
                                 : "Didn't find all the controllers: running a deep scan.");
      probs = {...probs, ...(await discover(forceDeep ? [...W.types] : short, true, !forceDeep))};
      deepRan = true;
    }
    stop();
    const p = Object.entries(probs).map(([t, m]) => `${drv(t).label}: ${m}`);
    $("#scan-msg").textContent = (countNote(deepRan) || (W.found.length ? `Found ${W.found.length}${deepRan ? " after a deep scan" : ""}.`
      : `Nothing answered${deepRan ? ", even in a deep scan" : ""}.`)) + (p.length ? " " + p.join(" · ") : "");
    if (autoAdd) for (const d of W.found) if (d.supported && !d.needs_key) addController(d);
  } catch (e) { stop(); $("#scan-msg").textContent = ""; err(e.message); }
  $("#scan").disabled = $("#deep").disabled = false;
  $("#deep").hidden = false;
  drawFound(); drawChosen();
}
async function addByAddress() {
  const type = $("#add-type").value, ip = $("#add-ip").value.trim();
  if (!validIp(ip)) return err("Type an IPv4 address like 192.168.2.50.");
  const body = {type, ip};
  if (type === "govee") body.model = $("#add-model").value;
  if (type === "tuya") Object.assign(body, {device_id: $("#add-dev").value.trim(), local_key: $("#add-key").value.trim(), version: $("#add-ver").value});
  err(""); $("#add").disabled = true;
  try {
    const r = await api("/api/setup/probe", body);
    for (const row of r.devices) addController({...row, local_key: body.local_key});
    showCount();
    $("#add-ip").value = "";
    if ($("#add-key")) $("#add-key").value = "";
  } catch (e) { err(e.message); }
  $("#add").disabled = false;
  drawChosen(); drawFound();
}

// --- step 3: name and count (one card per run, in order along the house) --------------------------
function drawRuns() {
  const box = $("#runs");
  box.innerHTML = "";
  W.cfg.runs.forEach((r, i) => {
    const c = ctrlOf(r.controller);
    if (!c) return;
    const caps = drv(c.type).caps, card = el("div", "runcard");
    card.innerHTML = `<div class="row rc-head"><b class="rc-n"></b><span class="muted rc-c"></span><span class="spacer"></span>
        <button class="small rc-up" title="Move left (earlier along the house)">▲ Left</button>
        <button class="small rc-down" title="Move right (later along the house)">▼ Right</button></div>
      <div class="rc-grid">
        <label class="fld"><span>Name</span><input type=text data-k=name maxlength=40></label>
        <label class="fld"><span>Short name</span><input type=text data-k=short maxlength=12></label>
        <label class="fld"><span># Lights / LEDs</span><input type=number data-k=lights min=1 placeholder="?"><small class="note rc-hl"></small></label>
        <label class="fld"><span>Light 1 is at</span><select data-k=light1>${Object.entries(LIGHT1).map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select>
          <small class="note">as you face the lights</small></label>
      </div>`;
    $(".rc-n", card).textContent = `${i + 1}.`;
    $(".rc-c", card).textContent = `${modelLabel(c.type, c.model)} · ${where(c)}`;
    $(".rc-hl", card).textContent = caps.count === "display" ? "Used for drawing only." : caps.count === "reported" && hasLights(r)
      ? "Reported by the controller." : "Not sure? We'll help you count it in the Test step.";
    const up = $(".rc-up", card), down = $(".rc-down", card);
    up.disabled = i === 0; down.disabled = i === W.cfg.runs.length - 1;
    const move = d => { const a = W.cfg.runs; [a[i], a[i + d]] = [a[i + d], a[i]]; drawRuns(); };
    up.onclick = () => move(-1); down.onclick = () => move(1);
    for (const inp of $$("[data-k]", card)) {
      const k = inp.dataset.k;
      inp.value = r[k] ?? "";
      if (k === "lights") inp.max = maxLights(c);
      inp.oninput = inp.onchange = () => {
        if (k === "name" && (!r.short || r.short === String(r.name).slice(0, 12))) { r.short = inp.value.slice(0, 12); $("[data-k=short]", card).value = r.short; }
        if (k === "lights") r.lights = inp.value === "" ? null : Number(inp.value);
        else r[k] = inp.value;
        if (k === "light1") r.reverse = r.light1 === "right";
        if (k === "name") syncNames();
      };
    }
    box.appendChild(card);
  });
}

// --- step 4: test, one controller at a time ---------------------------------------------------
// W.t: {order: [controller ids], i, phase: find | count | check | done, only: id or null, ...answers}
function startTests(only = null, phase = "find") {
  const order = only ? [only] : W.cfg.runs.map(r => r.controller).filter(id => ctrlOf(id));
  W.t = {order, i: 0, only, phase};
  resetAnswers();
}
function resetAnswers() { Object.assign(W.t, {blinked: false, other: false, nothing: false, recount: false, cnt: 0, markers: null, q1: null, q2: null, dir: false, typed: false, started: false}); }
const curCtrl = () => ctrlOf(W.t.order[W.t.i]);
function setPhase(phase) { W.t.phase = phase; resetAnswers(); drawTest(); }
async function toController(i) {
  const c = curCtrl();
  if (c) await stopTest(c);
  W.t.i = i; W.t.phase = "find"; resetAnswers();
  drawTest();
}
function afterFind() {
  const c = curCtrl(), r = runOf(c.id);
  setPhase(canCount(c) || (canCheck(c) && !hasLights(r)) ? "count" : canCheck(c) ? "check" : "done");
}
function drawTest() {
  const c = curCtrl();
  if (!c) { $("#t-one").replaceChildren(el("p", "muted", "No controllers to test: add one in step 2.")); return; }
  const r = runOf(c.id), d = drv(c.type), n = W.t.order.length;
  $("#test-intro").textContent = W.info.live
    ? "Each test shows on that controller's lights for up to a minute. Look at the lights and answer."
    : "Practice mode: nothing is sent to the lights. The strip shows what they would do.";
  $("#t-title").textContent = W.t.only ? `Testing ${r.name}` : `Controller ${W.t.i + 1} of ${n}: ${r.name}`;
  $("#t-sub").textContent = `${modelLabel(c.type, c.model)} · ${where(c)}`;
  const steps = ["find", ...(canCount(c) || canCheck(c) ? ["count"] : []), ...(canCheck(c) ? ["check"] : []), "done"];
  const label = {find: "Find it", count: "Count", check: "Check", done: "Done"};
  $("#t-phases").innerHTML = "";
  for (const s of steps) $("#t-phases").appendChild(el("li", s === W.t.phase ? "on" : steps.indexOf(s) < steps.indexOf(W.t.phase) ? "done" : "", label[s]));
  $("#t-restore").textContent = RESTORE_NOTE[d.caps.restore] || "";
  if (!W.testing[c.id]) {                  // between tests: an unlit strip as long as the run
    if (hasLights(r)) dots(r.lights);
    $("#t-dots").hidden = W.t.phase === "done" || !hasLights(r);
  } else $("#t-dots").hidden = W.t.phase === "done";
  const body = $("#t-body");
  body.innerHTML = "";
  ({find: drawFind, count: drawCountPhase, check: drawCheck, done: drawDone})[W.t.phase](c, r, body);
  // controller navigation
  const nav = $("#t-nav");
  nav.innerHTML = "";
  if (!W.t.only && W.t.i > 0) nav.appendChild(button("◀ Previous controller", () => toController(W.t.i - 1), "ghost small"));
  nav.appendChild(el("span", "spacer"));
  if (W.t.phase !== "done") nav.appendChild(button(W.t.i < n - 1 ? "Skip this controller" : "Skip", () => nextController(), "ghost small"));
  drawMore(c);
}
async function nextController() {
  if (W.t.i < W.t.order.length - 1) return toController(W.t.i + 1);
  await stopTest(curCtrl());
  return go(W.t.only ? 5 : 4);
}
const q = (text, cls = "tq") => el("p", cls, text);
const answers = (...btns) => { const row = el("div", "row answers"); row.append(...btns.filter(Boolean)); return row; };

// A. Find it: blink, then which run blinked?
function drawFind(c, r, body) {
  body.append(q(`First, make sure this is the right run. Press Blink and look at your lights.`),
    answers(button(W.t.blinked ? "Blink again" : "Blink", async () => {
      await runTest(c, "identify"); W.t.blinked = true; W.t.nothing = false; drawTest();
    }, "live")));
  if (!W.t.blinked) return;
  const others = W.cfg.runs.filter(x => x !== r && ctrlOf(x.controller));
  body.append(q("What blinked?"), answers(
    button(`Yes, ${r.name} blinked`, () => afterFind(), "primary"),
    others.length ? button("Another run blinked…", () => { W.t.other = true; W.t.nothing = false; drawTest(); }) : null,
    button("Nothing blinked", () => { W.t.nothing = true; W.t.other = false; drawTest(); })));
  if (W.t.other) {
    const sel = el("select");
    for (const x of others) sel.appendChild(new Option(x.name, x.controller));
    body.append(answers(el("span", "lbl", "Which one?"), sel, button("That one blinked", () => {
      const o = runOf(sel.value);            // this controller drives that run: swap them
      [r.controller, o.controller] = [o.controller, r.controller];
      syncNames();
      afterFind();
    }, "primary")), el("p", "note", "The names swap: this controller gets that run's name, place along the house and count."));
  }
  if (W.t.nothing) {
    const ul = el("ul", "note help");
    for (const t of ["Is the controller powered on, and do its lights work in its own app?",
      ...(c.type === "govee" ? ["In the Govee Home app, open the device's settings and switch on LAN Control."] : []),
      "Is this computer on the same network as the lights (not a guest network)?",
      "A firewall on this computer can block the messages: allow Python on private networks."])
      ul.appendChild(el("li", "", t));
    body.append(q("Things to check:"), ul,
      answers(button("Blink again", () => runTest(c, "identify"), "live"), button("Skip this controller", () => nextController())));
  }
}

// B. Count (Govee: segment markers, then the red lights of the last segment)
function drawCountPhase(c, r, body) {
  const lps = W.lps[c.id] || drv(c.type).lights_per_segment?.[c.model] || 5, max = maxLights(c);
  if (hasLights(r) && !W.t.recount) {
    body.append(q(`${r.name} is set to ${r.lights} lights. Is that right?`), answers(
      button("Yes, check it", () => setPhase(canCheck(c) ? "check" : "done"), "primary"),
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
  // 1: markers
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
  // 2: the red lights of the last segment
  if (W.t.cnt >= 2) {
    const red = el("input"); red.type = "number"; red.min = 1; red.max = lps; red.style.width = "4em";
    const sum = el("p", "tsum");
    const use = button("Use this count", () => {
      const n = lps * (W.t.markers - 1) + Number(red.value);
      if (!(Number(red.value) >= 1 && Number(red.value) <= lps)) throw new Error(`Type a number from 1 to ${lps}.`);
      if (!(n >= 1 && n <= max)) throw new Error(`That makes ${n}: count the markers again.`);
      r.lights = n; setPhase("check");
    }, "primary");
    use.disabled = true;
    red.oninput = () => {
      const v = Number(red.value), ok = v >= 1 && v <= lps;
      use.disabled = !ok;
      sum.textContent = ok ? `${lps} × ${W.t.markers - 1} + ${v} = ${lps * (W.t.markers - 1) + v} lights` : "";
      use.textContent = ok ? `Use ${lps * (W.t.markers - 1) + v} lights` : "Use this count";
    };
    body.append(q("Step 2: now the last group is red."),
      answers(el("span", "lbl", "How many red lights at the end?"), red), sum, answers(use));
  }
  body.append(answers(button("Type the number from the Govee app", () => { W.t.typed = true; drawTest(); }, "ghost small")));
}

// C. Check: light 1 red, last light blue, orange past the end. Which end is red? Any orange?
function drawCheck(c, r, body) {
  if (!hasLights(r)) { setPhase("count"); return; }
  const shown = W.testing[c.id] === "check" || W.testing[c.id] === "chase";
  if (!W.t.started) { W.t.started = true; runTest(c, "check").then(drawTest).catch(e => err(e.message)); }
  body.append(q(`Light 1 should be red, light ${r.lights} (the last one) blue, the ones between dim white.`),
    answers(button(shown ? "Show it again" : "Show it", async () => { await runTest(c, "check"); W.t.dir = false; drawTest(); }, "live")));
  // Q1: where is red?
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
  // Q2: anything after the blue?
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
    }, "primary")), el("p", "note", v20note()));
  }
  if (W.t.q2 === "noblue") {
    body.append(el("p", "note", "Then the count is too high: the blue light is past the end of the run."),
      answers(button(canCount(c) ? "Count again" : "Change the number", () => { setPhase("count"); W.t.recount = true; drawTest(); }, "primary")));
  }
}
const v20note = () => "If all 20 are orange, add them: the next check shows 20 more.";

// D. Done: summary for this controller, with a sweep in the chosen direction
function drawDone(c, r, body) {
  stopTest(c);
  const lights = hasLights(r) ? `${r.lights} lights` : "light count not set";
  const checked = canCheck(c) ? light1Text(r) : `${light1Text(r)} (this controller can only blink)`;
  body.append(el("p", "tsum", `${r.name}: ${lights}, ${checked}.`));
  if (hasLights(r)) body.append(sweep(r));
  const last = W.t.i >= W.t.order.length - 1;
  body.append(answers(
    button(last ? (W.t.only ? "Done: check and save" : "Done: time and place") : "Next controller ▶", () => nextController(), "primary"),
    button("Test it again", () => setPhase("find"), "ghost")));
}
function sweep(r) {
  const n = Math.min(r.lights, 60), wrap = el("div", "sweep"), strip = el("div", "sweep-dots");
  strip.style.gridTemplateColumns = `repeat(${n}, minmax(0, 1fr))`;
  strip.innerHTML = "<i></i>".repeat(n);
  const ends = el("div", "sweep-ends");
  const fromRight = r.light1 === "right";
  ends.append(el("span", "", fromRight ? "last light" : r.light1 ? "light 1" : "light 1?"), el("span", "", fromRight ? "light 1" : "last light"));
  wrap.append(strip, ends, el("p", "note", r.light1 ? "The dot runs from light 1, the way this controller counts its lights. The dashboard turns runs round as needed, so themes run the same way along the house." : "Light 1 not checked yet: themes may run the wrong way round on this run."));
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
function drawMore(c) {
  const box = $("#t-more-btns");
  box.innerHTML = "";
  for (const name of drv(c.type).tests) {
    if (["markers", "tail", "check"].includes(name)) continue;
    box.appendChild(button(W.info.tests[name], () => runTest(c, name), "live small" + (W.testing[c.id] === name ? " on" : "")));
  }
  box.appendChild(button("Stop", () => stopTest(c), "danger small"));
}

function dots(n) {
  const d = $("#t-dots");
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
  $("#t-status").textContent = (res.live ? "On the lights now." : "Practice mode: logged only.")
    + (TEST_HELP[name] && !["identify", "chase"].includes(name) ? " " + TEST_HELP[name] : "")
    + (res.slow ? " (This controller changes about once a second.)" : "")
    + (name === "check" ? ` The strip shows what is sent: the ${res.frame_lights - body.lights} orange lights are past the count, so real lights only show them if the count is too low.` : "");
  const pv = await api("/api/setup/preview", body);
  $("#t-dots").hidden = false;
  animate(c.id, pv, res.seconds);
  return res;
}
async function stopTest(c) {
  if (!c) return;
  clearInterval(W.anim);
  if (W.testing[c.id]) {
    delete W.testing[c.id];
    try { await api("/api/setup/test/stop", {ip: c.ip, zone: c.zone || ""}); } catch (e) { err(e.message); }
  }
  if ($("#t-dots")) for (const i of $("#t-dots").children) { i.style.background = ""; i.style.boxShadow = ""; }
  if ($("#t-status")) $("#t-status").textContent = "";
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
      $("#t-status").textContent = "The test ended by itself.";
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

// --- step 5: time and place --------------------------------------------------------------------------
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

// --- step 6: save ------------------------------------------------------------------------------------
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
    links.append(a("Change", () => go(2)), " · ", a(canCount(c) || canCheck(c) ? "Count it" : "Test it", () => {
      startTests(c.id, canCount(c) || canCheck(c) ? "count" : "find"); go(3, true);
    }));
  });
  const loc = W.cfg.location;
  const p = el("p", "", `Mode: ${W.cfg.mode === "live" ? "Live" : "Practice"} · Time zone: ${W.cfg.timezone} · Location: ${
    loc ? (loc.place ? `${loc.place}${loc.zip ? " " + loc.zip : ""}` : `${loc.lat}, ${loc.lon}`) : "not set"}`);
  $("#summary").replaceChildren(t, el("p", "note", "Runs are listed left to right along the house."), p);
  $("#save-where").textContent = `Saved to ${inHome(W.info.home, "config.json")} (keys such as Tuya's go to secrets.json, readable only by you). The server restarts with it.`;
}
async function save() {
  const msg = check(2) || check(5);
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
  if (step === 0 && !W.types.size) return "Tick at least one kind of lights.";
  if (step === 1) {
    if (!W.cfg.controllers.length) return "Add at least one controller.";
    const noKey = W.cfg.controllers.find(c => c.type === "tuya" && !c.has_secret && !(c.local_key && c.local_key.length === 16));
    if (noKey) return `Type the 16-character local key for the Tuya device at ${noKey.ip}.`;
  }
  if (step === 2) {
    for (const r of W.cfg.runs) {
      const c = ctrlOf(r.controller);
      if (!String(r.name || "").trim()) return "Every run needs a name.";
      if (r.lights != null && r.lights !== "" && !(r.lights >= 1 && r.lights <= maxLights(c))) return `${r.name}: lights must be 1 to ${maxLights(c)}, or blank.`;
    }
    const names = W.cfg.runs.map(r => String(r.name).trim().toLowerCase());
    if (new Set(names).size !== names.length) return "Give each run a different name.";
  }
  if (step === 5) {
    const r = W.cfg.runs.find(r => !hasLights(r));
    if (r) return `${r.name}: how many lights? Type it in step 3, or count it in step 4.`;
  }
  return "";
}
// keepTests: step 4 was set up by the caller (a deep link or a "Count it" link).
async function go(step, keepTests = false) {
  if (step > W.step) for (let s = W.step; s < step; s++) { const msg = check(s); if (msg) { if (s !== W.step) await go(s); return err(msg); } }
  err("");
  if (W.step === 3 && step !== 3) await stopAllTests();
  if (W.step === 4) readPlace();
  if (W.step === 2) syncNames();
  W.step = step;
  $$("[data-page]").forEach(p => { p.hidden = Number(p.dataset.page) !== step; });
  $$("#steps li").forEach(li => {
    const s = Number(li.dataset.step);
    li.className = (s === step ? "on" : s < step ? "done" : "") + (W.jump ? " jump" : "");
  });
  $("#prev").hidden = step === 0;
  $("#next").textContent = step === STEPS - 1 ? "Save and start" : "Next";
  if (step === 1) { drawTypeNotes(); drawAddRow(); drawFound(); drawChosen(); if (W.cfg.controllers.length) showCount(); }
  if (step === 2) drawRuns();
  if (step === 3) { if (!keepTests || !W.t) startTests(); drawTest(); }
  if (step === 4) drawPlace();
  if (step === 5) drawSummary();
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
    W.types.add(c.type);
    if (!W.cfg.runs.some(r => r.controller === c.id)) W.cfg.runs.push(newRun(c, c.name || c.ip, null));
  }
  if (!W.types.size) { const g = W.info.drivers.find(d => d.type === "govee" && d.available); if (g) W.types.add("govee"); }
  const pill = $("#mode");
  pill.textContent = W.info.live ? "LIVE" : "PRACTICE";
  pill.className = "pill " + (W.info.live ? "live" : "dry");
  const b = $("#banner");
  if (W.info.error) { b.hidden = false; b.textContent = `Your settings file has a problem: ${W.info.error}. Go through the steps to fix it.`; }
  else if (W.info.configured) $("#back").hidden = false;
  else { b.hidden = false; b.textContent = "Welcome! No settings yet: this wizard sets up your lights. It takes a few minutes."; }
  drawDrivers();
  $("#scan").onclick = () => scan(false);
  $("#deep").onclick = () => scan(true);
  $("#add").onclick = addByAddress;
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
  // Deep links: ?step=4&controller=<id>, ?step=5
  const qs = new URLSearchParams(location.search), want = Number(qs.get("step")) - 1;
  if (W.jump && want >= 0 && want < STEPS) {
    const cid = qs.get("controller");
    if (want === 3 && cid && ctrlOf(cid)) { startTests(cid); return go(3, true); }
    return go(want);
  }
  go(0);
}

init().catch(e => err(e.message));
