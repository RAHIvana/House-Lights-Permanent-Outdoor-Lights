"use strict";
// Setup wizard: pick the kinds of lights, find controllers, name the runs, test them, set the
// time zone and location, then save config.json (the server restarts with it).
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

const W = {step: 0, info: null, cfg: null, found: [], types: new Set(), testing: {}, anim: {}, lps: {}};
const STEPS = 6;
const TEST_HELP = {
  markers: "Every segment starts with a red or green light; every 10th marker is blue. Count the markers along the whole run and type the number.",
  tail: "The last segment is red. Count the red lights at the end of the run and type the number.",
  identify: "The whole run blinks. Is it the run you expect?",
  ruler: "Light 1 is red, the last light blue, every 10th light white. If the blue light isn't the very last light, the count is wrong.",
  chase: "A white dot runs from light 1 (red) to the last light (blue). Note where light 1 is. Tick Reverse if themes should run the other way.",
  rgb: "Red, green and blue thirds. If the colors look wrong, this controller may need a fix: please report it.",
  segments: "Orange and blue groups: each group is one segment. Static themes are sent one color per segment.",
};
const RESTORE_NOTE = {
  auto: "When a test stops, the lights go back to what they showed before.",
  snapshot: "The light's settings are saved before a test and put back afterwards.",
  none: "This controller can't report what it showed, so it can't be put back after a test: afterwards, pick a theme here or in its own app.",
};

function err(msg) { $("#err").textContent = msg || ""; }
const validIp = ip => /^\d{1,3}(\.\d{1,3}){3}$/.test(ip) && ip.split(".").every(n => Number(n) <= 255);

// --- data helpers --------------------------------------------------------------------------
const drv = type => W.info.drivers.find(d => d.type === type) || {models: {}, caps: {}, tests: []};
const modelLabel = (type, model) => drv(type).models[model] || model;
const runOf = cid => W.cfg.runs.find(r => r.controller === cid);
const where = c => c.ip + (c.zone ? ` · ${c.zone}` : "");
const sameSpot = (a, b) => a.ip === b.ip && (a.zone || "") === (b.zone || "");
function ctrlId(row) {
  const base = `${row.type}-${row.ip}${row.zone ? "-" + row.zone : ""}`.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32);
  let id = base, k = 2;
  while (W.cfg.controllers.some(c => c.id === id)) id = `${base.slice(0, 29)}-${k++}`;
  return id;
}
function addController(row) {
  if (W.cfg.controllers.some(c => sameSpot(c, row))) return;
  const c = {id: ctrlId(row), type: row.type, model: row.model, ip: row.ip, name: "", enabled: true};
  if (row.zone) c.zone = row.zone;
  if (row.device_id) { c.device_id = row.device_id; c.version = row.version || "3.3"; }
  if (row.local_key) c.local_key = row.local_key;
  W.cfg.controllers.push(c);
  const n = W.cfg.runs.length + 1, name = row.zone || `Run ${n}`;
  W.cfg.runs.push({name, short: name.slice(0, 12), subtitle: "", start: "", controller: c.id,
                   lights: row.lights || 60, reverse: false, baseline: {brightness: 50, kelvin: 2200}});
}
function removeController(id) {
  W.cfg.controllers = W.cfg.controllers.filter(c => c.id !== id);
  W.cfg.runs = W.cfg.runs.filter(r => r.controller !== id);
}
const controllerBody = c => ({id: c.id, type: c.type, model: c.model, ip: c.ip, zone: c.zone, device_id: c.device_id,
                              version: c.version, local_key: c.local_key});

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
    r.onchange = () => { r.checked ? W.types.add(d.type) : W.types.delete(d.type); };
    $("#drivers").appendChild(l);
  }
}

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
  if (!W.cfg.controllers.length) { tb.innerHTML = '<tr><td colspan="6" class="muted">None yet: scan, or add one by address.</td></tr>'; return; }
  for (const c of W.cfg.controllers) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td></td><td></td><td><input type=text maxlength=40></td><td class=extra></td><td><input type=checkbox class=en></td><td><button class='small danger'>Remove</button></td>";
    tr.cells[0].textContent = where(c); tr.cells[1].textContent = modelLabel(c.type, c.model);
    const name = $("input[type=text]", tr), en = $(".en", tr);
    name.value = c.name || ""; name.oninput = () => { c.name = name.value; };
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
    $("button", tr).onclick = () => { removeController(c.id); drawChosen(); drawFound(); };
    tb.appendChild(tr);
  }
}
function drawAddRow() {
  const sel = $("#add-type");
  sel.innerHTML = "";
  for (const d of W.info.drivers.filter(d => d.available && W.types.has(d.type))) sel.appendChild(new Option(d.label, d.type));
  const extra = () => {
    const box = $("#add-extra");
    box.innerHTML = "";
    if (sel.value === "govee") {
      box.innerHTML = "<select id=add-model></select>";
      for (const [m, label] of Object.entries(drv("govee").models)) $("#add-model").appendChild(new Option(label, m));
    } else if (sel.value === "tuya") {
      box.innerHTML = `<input type=text id=add-dev size=22 placeholder="device id">
        <input type=password id=add-key size=18 maxlength=16 placeholder="local key" autocomplete=off>
        <select id=add-ver>${["3.1", "3.2", "3.3", "3.4", "3.5"].map(v => `<option${v === "3.3" ? " selected" : ""}>${v}</option>`).join("")}</select>`;
    }
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
async function scan() {
  err(""); $("#scan").disabled = true; $("#scan-msg").textContent = "Scanning… (a network scan can take up to 10 seconds)";
  try {
    const r = await api("/api/setup/discover", {types: [...W.types], targets: $("#targets").value});
    W.found = r.devices;
    const probs = Object.entries(r.problems || {}).map(([t, p]) => `${drv(t).label}: ${p}`);
    $("#scan-msg").textContent = (r.devices.length ? `Found ${r.devices.length}.` : "Nothing answered.") + (probs.length ? " " + probs.join(" · ") : "");
    if (!W.cfg.controllers.length) for (const d of r.devices) if (d.supported && !d.needs_key) addController(d);
  } catch (e) { $("#scan-msg").textContent = ""; err(e.message); }
  $("#scan").disabled = false;
  drawFound(); drawChosen();
}
async function addByAddress() {
  const type = $("#add-type").value, ip = $("#add-ip").value.trim();
  if (!validIp(ip)) return err("Type an IPv4 address like 192.168.1.50.");
  const body = {type, ip};
  if (type === "govee") body.model = $("#add-model").value;
  if (type === "tuya") Object.assign(body, {device_id: $("#add-dev").value.trim(), local_key: $("#add-key").value.trim(), version: $("#add-ver").value});
  err(""); $("#add").disabled = true;
  try {
    const r = await api("/api/setup/probe", body);
    for (const row of r.devices) addController({...row, local_key: body.local_key});
    $("#add-ip").value = "";
    if ($("#add-key")) $("#add-key").value = "";
  } catch (e) { err(e.message); }
  $("#add").disabled = false;
  drawChosen(); drawFound();
}

// --- step 3: runs -------------------------------------------------------------------------------
function drawRuns() {
  const tb = $("#runs tbody");
  tb.innerHTML = "";
  for (const c of W.cfg.controllers) {
    const r = runOf(c.id), tr = document.createElement("tr"), caps = drv(c.type).caps;
    tr.innerHTML = `<td></td><td><input type=text data-k=name maxlength=40></td><td><input type=text data-k=short maxlength=12 style="min-width:6em"></td>
      <td><input type=number data-k=lights min=1 max=3000><span class="muted note-l"></span></td><td><input type=text data-k=start maxlength=80></td>
      <td><input type=checkbox data-k=reverse></td>`;
    tr.cells[0].textContent = c.name || where(c);
    $(".note-l", tr).textContent = caps.count === "display" ? " for drawing only" : caps.count === "reported" ? " reported" : "";
    for (const inp of $$("[data-k]", tr)) {
      const k = inp.dataset.k;
      if (inp.type === "checkbox") { inp.checked = !!r[k]; inp.onchange = () => { r[k] = inp.checked; }; }
      else {
        inp.value = r[k] ?? "";
        inp.oninput = () => {
          if (k === "name" && (!r.short || r.short === String(r.name).slice(0, 12))) { r.short = inp.value.slice(0, 12); $("[data-k=short]", tr).value = r.short; }
          r[k] = inp.type === "number" ? Number(inp.value) : inp.value;
        };
      }
    }
    tb.appendChild(tr);
  }
}

// --- step 4: tests --------------------------------------------------------------------------------
function drawTests() {
  $("#test-intro").textContent = (W.info.live
    ? "Each button shows a test on that run's lights for up to a minute."
    : "Practice mode: test buttons are logged on the server and nothing is sent. The strip shows what the lights would do.")
    + " You can fix the light count and Reverse here too.";
  const box = $("#tests");
  box.innerHTML = "";
  for (const c of W.cfg.controllers) {
    const r = runOf(c.id), el = document.createElement("div"), d = drv(c.type), caps = d.caps;
    el.className = "testrun";
    el.innerHTML = `<div class="row"><b class="tn"></b><span class="muted tc"></span><span class="spacer"></span>
        <label class="lbl">Lights <input type=number class=tl min=1 max=3000></label>
        <label class="lbl"><input type=checkbox class=tr> Reverse</label></div>
      <div class="testdots"></div>
      <div class="count" hidden>
        <span class="lbl">Count the lights:</span>
        <button class="live small" data-c="markers">1 Show segment markers</button>
        <label class="lbl">markers <input type=number class=cm min=1 max=255 style="width:4.5em"></label>
        <button class="live small" data-c="tail" disabled>2 Show the last segment</button>
        <label class="lbl">red lights <input type=number class=cr min=1 max=5 style="width:4em" disabled></label>
        <button class="small primary" data-c="use" disabled>Use this count</button>
      </div>
      <div class="row tb"></div>
      <p class="note th"></p>
      <p class="note tx"></p>`;
    $(".tn", el).textContent = r.name; $(".tc", el).textContent = `${modelLabel(c.type, c.model)} · ${where(c)}`;
    $(".tx", el).textContent = RESTORE_NOTE[caps.restore] || "";
    const tl = $(".tl", el), trv = $(".tr", el);
    tl.value = r.lights; trv.checked = !!r.reverse;
    const again = () => { const t = W.testing[c.id]; if (t) runTest(c, el, t); else dots(el, r.lights); };
    tl.onchange = () => { r.lights = Number(tl.value); again(); };
    trv.onchange = () => { r.reverse = trv.checked; again(); };
    if (d.tests.includes("markers")) {
      $(".count", el).hidden = false;
      const cm = $(".cm", el), cr = $(".cr", el), bTail = $("[data-c=tail]", el), bUse = $("[data-c=use]", el);
      const lps = () => W.lps[c.id] || 5;
      const total = () => lps() * (Number(cm.value) - 1) + Number(cr.value);
      $("[data-c=markers]", el).onclick = () => runTest(c, el, "markers");
      cm.oninput = () => { bTail.disabled = !(Number(cm.value) >= 1); cr.disabled = true; bUse.disabled = true; };
      bTail.onclick = async () => { await runTest(c, el, "tail", {markers: Number(cm.value)}); cr.disabled = false; cr.max = lps(); };
      cr.oninput = () => { const v = Number(cr.value); bUse.disabled = !(v >= 1 && v <= lps()); bUse.textContent = bUse.disabled ? "Use this count" : `Use ${total()} lights`; };
      bUse.onclick = () => {
        const n = total();
        if (!(n >= 1 && n <= 255)) return err("That count is outside 1 to 255: count the markers again.");
        r.lights = n; tl.value = n;
        $(".th", el).textContent = `Light count set to ${n}. Press "Check the count": the last light should be blue.`;
        dots(el, n);
      };
    }
    for (const name of d.tests) {
      if (name === "markers" || name === "tail") continue;
      const b = document.createElement("button");
      b.className = "live small"; b.textContent = W.info.tests[name]; b.dataset.test = name;
      b.onclick = () => runTest(c, el, name);
      $(".tb", el).appendChild(b);
    }
    const stop = document.createElement("button");
    stop.className = "danger small"; stop.textContent = "Stop"; stop.onclick = () => stopTest(c, el);
    $(".tb", el).appendChild(stop);
    dots(el, r.lights);
    box.appendChild(el);
  }
}
function dots(el, n) {
  const d = $(".testdots", el);
  n = Math.max(1, Math.min(3000, Number(n) || 1));
  if (d.children.length !== n) {
    d.style.gridTemplateColumns = `repeat(${Math.min(n, 60)}, minmax(0, 1fr))`;
    d.innerHTML = "<i></i>".repeat(n);
  }
  return [...d.children];
}
async function runTest(c, el, name, extra = {}) {
  const r = runOf(c.id);
  err("");
  try {
    const body = {controller: controllerBody(c), lights: r.lights, reverse: r.reverse, test: name, ...extra};
    const res = await api("/api/setup/test", body);
    W.testing[c.id] = name;
    W.lps[c.id] = res.lights_per_segment;
    $(".th", el).textContent = (res.live ? "On the lights now. " : "Practice mode: logged only. ") + TEST_HELP[name]
      + (res.slow ? " (This controller changes about once a second.)" : "");
    for (const b of $$("[data-test], [data-c]", el)) b.classList.toggle("on", (b.dataset.test || b.dataset.c) === name);
    const pv = await api("/api/setup/preview", body);
    animate(c.id, el, pv, res.seconds);
  } catch (e) { err(e.message); }
}
async function stopTest(c, el) {
  try { await api("/api/setup/test/stop", {ip: c.ip, zone: c.zone || ""}); } catch (e) { err(e.message); }
  delete W.testing[c.id];
  clearInterval(W.anim[c.id]);
  for (const b of $$("[data-test], [data-c]", el)) b.classList.remove("on");
  $(".th", el).textContent = "Stopped.";
  for (const i of dots(el, runOf(c.id).lights)) { i.style.background = ""; i.style.boxShadow = ""; }
}
function animate(cid, el, pv, seconds) {
  clearInterval(W.anim[cid]);
  const els = dots(el, pv.frames[0].length), t0 = performance.now();
  let k = 0;
  const paint = () => {
    const f = pv.frames[k % pv.frames.length];
    f.forEach((c, i) => { const on = c !== "#000000"; els[i].style.background = on ? c : ""; els[i].style.boxShadow = on ? `0 0 5px ${c}` : ""; });
    k++;
    if (performance.now() - t0 > seconds * 1000) {
      clearInterval(W.anim[cid]); delete W.testing[cid];
      for (const b of $$("[data-test], [data-c]", el)) b.classList.remove("on");
      $(".th", el).textContent = "The test ended by itself.";
    }
  };
  paint();
  if (pv.animated) W.anim[cid] = setInterval(paint, 1000 / pv.fps);
}
async function stopAllTests() {
  if (Object.keys(W.testing).length) { try { await api("/api/setup/test/stop", {}); } catch (e) { /* server may be restarting */ } }
  for (const id of Object.keys(W.anim)) clearInterval(W.anim[id]);
  W.testing = {};
}

// --- step 5: time and place --------------------------------------------------------------------------
function drawPlace() {
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  const tz = $("#tz");
  if (!tz.value) tz.value = W.cfg.timezone && W.cfg.timezone !== "UTC" ? W.cfg.timezone : (browserTz || "UTC");
  $("#tz-hint").textContent = browserTz ? `This device: ${browserTz}` : "";
  if (!$("#tz-list").children.length && Intl.supportedValuesOf)
    $("#tz-list").innerHTML = Intl.supportedValuesOf("timeZone").map(z => `<option value="${z}">`).join("");
  const loc = W.cfg.location || {};
  if ($("#lat").value === "" && loc.lat != null) $("#lat").value = loc.lat;
  if ($("#lon").value === "" && loc.lon != null) $("#lon").value = loc.lon;
  for (const r of $$("input[name=mode]")) r.checked = r.value === (W.cfg.mode || "live");
  if (W.info.forced_dry && !$("#modes .forced")) $("#modes").insertAdjacentHTML("beforeend", '<span class="muted forced">The server was started with --dry, so it stays in practice mode for now.</span>');
}
function readPlace() {
  W.cfg.timezone = $("#tz").value.trim() || "UTC";
  const lat = $("#lat").value, lon = $("#lon").value;
  W.cfg.location = lat === "" && lon === "" ? null : {lat: Number(lat), lon: Number(lon)};
  const m = $$("input[name=mode]").find(r => r.checked);
  W.cfg.mode = m ? m.value : "live";
}
function geolocate() {
  const msg = $("#geo-msg");
  if (!navigator.geolocation) { msg.textContent = "This browser can't share its location."; return; }
  msg.textContent = "Asking…";
  navigator.geolocation.getCurrentPosition(p => {
    $("#lat").value = p.coords.latitude.toFixed(2); $("#lon").value = p.coords.longitude.toFixed(2); msg.textContent = "";
  }, () => { msg.textContent = "Not available here (browsers only share location on https or localhost). Type it instead."; });
}

// --- step 6: save ------------------------------------------------------------------------------------
function drawSummary() {
  const t = document.createElement("table");
  t.innerHTML = "<thead><tr><th>Run</th><th>Short</th><th>Lights</th><th>Controller</th><th>Light 1 is at</th><th>Reversed</th><th></th></tr></thead><tbody></tbody>";
  for (const c of W.cfg.controllers) {
    const r = runOf(c.id), tr = t.tBodies[0].insertRow();
    for (const v of [r.name, r.short, r.lights, `${modelLabel(c.type, c.model)} · ${where(c)}`, r.start, r.reverse ? "yes" : "", c.enabled === false ? "disabled" : ""])
      tr.insertCell().textContent = v;
  }
  const p = document.createElement("p");
  p.textContent = `Mode: ${W.cfg.mode === "live" ? "Live" : "Practice"} · Time zone: ${W.cfg.timezone} · Location: ${W.cfg.location ? `${W.cfg.location.lat}, ${W.cfg.location.lon}` : "not set"}`;
  $("#summary").replaceChildren(t, p);
  $("#save-where").textContent = `Saved to ${inHome(W.info.home, "config.json")} (keys such as Tuya's go to secrets.json, readable only by you). The server restarts with it.`;
}
async function save() {
  err(""); $("#next").disabled = true; $("#prev").disabled = true;
  await stopAllTests();
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
      if (!String(r.name).trim()) return "Every run needs a name.";
      if (!(r.lights >= 1 && r.lights <= 3000)) return `${r.name}: lights must be 1 to 3000.`;
    }
    const names = W.cfg.runs.map(r => String(r.name).trim().toLowerCase());
    if (new Set(names).size !== names.length) return "Give each run a different name.";
  }
  return "";
}
async function go(step) {
  const msg = step > W.step ? check(W.step) : "";
  if (msg) return err(msg);
  err("");
  if (W.step === 3 && step !== 3) await stopAllTests();
  if (W.step === 4) readPlace();
  W.step = step;
  $$("[data-page]").forEach(p => { p.hidden = Number(p.dataset.page) !== step; });
  $$("#steps li").forEach(li => { const s = Number(li.dataset.step); li.className = s === step ? "on" : s < step ? "done" : ""; });
  $("#prev").hidden = step === 0;
  $("#next").textContent = step === STEPS - 1 ? "Save and start" : "Next";
  if (step === 1) { drawTypeNotes(); drawAddRow(); drawFound(); drawChosen(); }
  if (step === 2) drawRuns();
  if (step === 3) drawTests();
  if (step === 4) drawPlace();
  if (step === 5) drawSummary();
  scrollTo(0, 0);
}

async function init() {
  W.info = await api("/api/setup");
  W.cfg = JSON.parse(JSON.stringify(W.info.config));
  W.cfg.controllers = Array.isArray(W.cfg.controllers) ? W.cfg.controllers : [];
  W.cfg.runs = Array.isArray(W.cfg.runs) ? W.cfg.runs : [];
  for (const c of W.cfg.controllers) {
    W.types.add(c.type);
    if (!W.cfg.runs.some(r => r.controller === c.id))
      W.cfg.runs.push({name: c.name || c.ip, short: "", subtitle: "", start: "", controller: c.id, lights: 60, reverse: false, baseline: {brightness: 50, kelvin: 2200}});
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
  $("#scan").onclick = scan;
  $("#add").onclick = addByAddress;
  $("#geo").onclick = geolocate;
  $("#prev").onclick = () => go(W.step - 1);
  $("#next").onclick = () => (W.step === STEPS - 1 ? save() : go(W.step + 1));
  addEventListener("pagehide", () => { if (Object.keys(W.testing).length) navigator.sendBeacon && navigator.sendBeacon("/api/setup/test/stop", new Blob(["{}"], {type: "application/json"})); });
  go(0);
}

init().catch(e => err(e.message));
