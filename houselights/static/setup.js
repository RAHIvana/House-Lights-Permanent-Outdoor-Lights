"use strict";
// Setup wizard: pick the kind of lights, find controllers, name the runs, test them, set the
// time zone and location, then save config.json (the server restarts with it).
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const W = {step: 0, info: null, cfg: null, found: [], type: "govee", testing: {}, anim: {}};
const STEPS = 6;
const TEST_HELP = {
  markers: "Every segment starts with a red or green light; every 10th marker is blue. Count the markers along the whole run and type the number.",
  tail: "The last segment is red. Count the red lights at the end of the run and type the number.",
  identify: "The whole run blinks white. Is it the run you expect?",
  ruler: "Light 1 is red, the last light blue, every 10th light white. If the blue light isn't the very last light, the count is wrong.",
  chase: "A white dot runs from light 1 (red) to the last light (blue). Note where light 1 is. Tick Reverse if themes should run the other way.",
  rgb: "Red, green and blue thirds. If the colors look wrong, this model may need a fix: please report it.",
  segments: "Orange and blue groups: each group is one segment. Static themes are sent one color per segment.",
};

function err(msg) { $("#err").textContent = msg || ""; }

// --- data helpers --------------------------------------------------------------------------
const drv = type => W.info.drivers.find(d => d.type === type);
const modelLabel = (type, model) => (drv(type) && drv(type).models[model]) || model;
const runOf = cid => W.cfg.runs.find(r => r.controller === cid);
function ctrlId(ip) {
  const base = `${W.type}-${ip.replace(/[^0-9a-f]/gi, "-")}`.toLowerCase().slice(0, 32);
  let id = base, k = 2;
  while (W.cfg.controllers.some(c => c.id === id)) id = `${base.slice(0, 29)}-${k++}`;
  return id;
}
function addController(ip, model, type = W.type) {
  if (W.cfg.controllers.some(c => c.ip === ip)) return;
  const c = {id: ctrlId(ip), type, model, ip, name: "", enabled: true};
  W.cfg.controllers.push(c);
  const n = W.cfg.runs.length + 1;
  W.cfg.runs.push({name: `Run ${n}`, short: `Run ${n}`, subtitle: "", start: "", controller: c.id,
                   lights: 60, reverse: false, baseline: {brightness: 50, kelvin: 2200}});
}
function removeController(id) {
  W.cfg.controllers = W.cfg.controllers.filter(c => c.id !== id);
  W.cfg.runs = W.cfg.runs.filter(r => r.controller !== id);
}

const validIp = ip => /^\d{1,3}(\.\d{1,3}){3}$/.test(ip) && ip.split(".").every(n => Number(n) <= 255);

// --- step 1: kind of lights -------------------------------------------------------------------
function drawDrivers() {
  $("#drivers").innerHTML = "";
  for (const d of W.info.drivers) {
    const l = document.createElement("label");
    if (!d.available) l.className = "off";
    l.innerHTML = `<input type="radio" name="driver"${d.available ? "" : " disabled"}><span><b></b><small></small></span>`;
    $("b", l).textContent = d.label;
    $("small", l).textContent = d.available ? "Supported: " + Object.values(d.models).join(", ") : d.note;
    const r = $("input", l);
    r.value = d.type; r.checked = d.type === W.type;
    r.onchange = () => { W.type = d.type; };
    $("#drivers").appendChild(l);
  }
  $("#driver-note").textContent = "Other models of the same make may work but aren't tested; the wizard only offers tested ones.";
}

// --- step 2: controllers ----------------------------------------------------------------------
function drawFound() {
  const tb = $("#found tbody");
  tb.innerHTML = "";
  if (!W.found.length) { tb.innerHTML = '<tr><td colspan="5" class="muted">Nothing scanned yet.</td></tr>'; return; }
  for (const d of W.found) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td><input type=checkbox></td><td></td><td></td><td></td><td class=muted></td>";
    const cb = $("input", tr), used = W.cfg.controllers.some(c => c.ip === d.ip);
    cb.checked = used; cb.disabled = !d.supported;
    cb.onchange = () => {
      if (cb.checked) addController(d.ip, d.model, d.type);
      else { const c = W.cfg.controllers.find(x => x.ip === d.ip); if (c) removeController(c.id); }
      drawChosen();
    };
    tr.cells[1].textContent = d.ip; tr.cells[2].textContent = d.label;
    tr.cells[3].textContent = d.device_tail ? "…" + d.device_tail : "";
    tr.cells[4].textContent = d.supported ? "" : "not supported yet";
    tb.appendChild(tr);
  }
}
function drawChosen() {
  const tb = $("#chosen tbody");
  tb.innerHTML = "";
  if (!W.cfg.controllers.length) { tb.innerHTML = '<tr><td colspan="5" class="muted">None yet: scan, or add one by address.</td></tr>'; return; }
  for (const c of W.cfg.controllers) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td></td><td></td><td><input type=text maxlength=40></td><td><input type=checkbox></td><td><button class='small danger'>Remove</button></td>";
    tr.cells[0].textContent = c.ip; tr.cells[1].textContent = modelLabel(c.type, c.model);
    const name = $("input[type=text]", tr), en = $("input[type=checkbox]", tr);
    name.value = c.name || ""; name.oninput = () => { c.name = name.value; };
    en.checked = c.enabled !== false; en.onchange = () => { c.enabled = en.checked; };
    $("button", tr).onclick = () => { removeController(c.id); drawChosen(); drawFound(); };
    tb.appendChild(tr);
  }
}
async function scan() {
  err(""); $("#scan").disabled = true; $("#scan-msg").textContent = "Scanning…";
  try {
    const r = await api("/api/setup/discover", {type: W.type, targets: $("#targets").value});
    W.found = r.devices;
    $("#scan-msg").textContent = r.devices.length ? `Found ${r.devices.length}.` : "Nothing answered. Check LAN Control is on, or type the lights' network.";
    if (!W.cfg.controllers.length) for (const d of r.devices) if (d.supported) addController(d.ip, d.model, d.type);
  } catch (e) { $("#scan-msg").textContent = ""; err(e.message); }
  $("#scan").disabled = false;
  drawFound(); drawChosen();
}

// --- step 3: runs -------------------------------------------------------------------------------
function drawRuns() {
  const tb = $("#runs tbody");
  tb.innerHTML = "";
  for (const c of W.cfg.controllers) {
    const r = runOf(c.id), tr = document.createElement("tr");
    tr.innerHTML = `<td></td><td><input type=text data-k=name maxlength=40></td><td><input type=text data-k=short maxlength=12 style="min-width:6em"></td>
      <td><input type=number data-k=lights min=1 max=255></td><td><input type=text data-k=start maxlength=80></td>
      <td><input type=checkbox data-k=reverse></td>`;
    tr.cells[0].textContent = c.name || c.ip;
    for (const inp of $$("[data-k]", tr)) {
      const k = inp.dataset.k;
      if (inp.type === "checkbox") { inp.checked = !!r[k]; inp.onchange = () => { r[k] = inp.checked; }; }
      else {
        inp.value = r[k] ?? "";
        inp.oninput = () => {
          if (k === "name" && (!r.short || r.short === r.name.slice(0, 12))) { r.short = inp.value.slice(0, 12); $("[data-k=short]", tr).value = r.short; }
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
    ? "Each button sends a test pattern to that run's lights for up to a minute. Stop ends it, and the lights go back to what they showed before."
    : "Practice mode: test buttons are logged on the server and nothing is sent. The strip shows what the lights would do.")
    + " You can fix the light count and Reverse here too.";
  const box = $("#tests");
  box.innerHTML = "";
  for (const c of W.cfg.controllers) {
    const r = runOf(c.id), el = document.createElement("div");
    el.className = "testrun";
    el.innerHTML = `<div class="row"><b class="tn"></b><span class="muted tc"></span><span class="spacer"></span>
        <label class="lbl">Lights <input type=number class=tl min=1 max=255></label>
        <label class="lbl"><input type=checkbox class=tr> Reverse</label></div>
      <div class="testdots"></div>
      <div class="count">
        <span class="lbl">Count the lights:</span>
        <button class="live small" data-c="markers">1 Show segment markers</button>
        <label class="lbl">markers <input type=number class=cm min=1 max=255 style="width:4.5em"></label>
        <button class="live small" data-c="tail" disabled>2 Show the last segment</button>
        <label class="lbl">red lights <input type=number class=cr min=1 max=5 style="width:4em" disabled></label>
        <button class="small primary" data-c="use" disabled>Use this count</button>
      </div>
      <div class="row tb"></div>
      <p class="note th"></p>`;
    $(".tn", el).textContent = r.name; $(".tc", el).textContent = `${modelLabel(c.type, c.model)} · ${c.ip}`;
    const tl = $(".tl", el), trv = $(".tr", el);
    tl.value = r.lights; trv.checked = !!r.reverse;
    const again = () => { const t = W.testing[c.id]; if (t) runTest(c, el, t); else dots(el, r.lights); };
    tl.onchange = () => { r.lights = Number(tl.value); again(); };
    trv.onchange = () => { r.reverse = trv.checked; again(); };
    const cm = $(".cm", el), cr = $(".cr", el), bTail = $("[data-c=tail]", el), bUse = $("[data-c=use]", el);
    const lps = () => (W.lps && W.lps[c.id]) || 5;
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
    for (const [name, label] of Object.entries(W.info.tests)) {
      if (name === "markers" || name === "tail") continue;
      const b = document.createElement("button");
      b.className = "live small"; b.textContent = label; b.dataset.test = name;
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
  n = Math.max(1, Math.min(255, Number(n) || 1));
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
    const body = {controller: {type: c.type, model: c.model, ip: c.ip}, lights: r.lights, reverse: r.reverse, test: name, ...extra};
    const res = await api("/api/setup/test", body);
    W.testing[c.id] = name;
    (W.lps = W.lps || {})[c.id] = res.lights_per_segment;
    $(".th", el).textContent = (res.live ? "On the lights now. " : "Practice mode: logged only. ") + TEST_HELP[name];
    for (const b of $$("[data-test]", el)) b.classList.toggle("on", b.dataset.test === name);
    const pv = await api("/api/setup/preview", {...body});
    animate(c.id, el, pv, res.seconds);
  } catch (e) { err(e.message); }
}
async function stopTest(c, el) {
  try { await api("/api/setup/test/stop", {ip: c.ip}); } catch (e) { err(e.message); }
  delete W.testing[c.id];
  clearInterval(W.anim[c.id]);
  for (const b of $$("[data-test]", el)) b.classList.remove("on");
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
      for (const b of $$("[data-test]", el)) b.classList.remove("on");
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
  if (W.info.forced_dry) $("#modes").insertAdjacentHTML("beforeend", '<span class="muted">The server was started with --dry, so it stays in practice mode for now.</span>');
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
  const rows = W.cfg.controllers.map(c => { const r = runOf(c.id); return [r.name, r.short, r.lights, `${c.model} · ${c.ip}`, r.start, r.reverse ? "yes" : "", c.enabled === false ? "disabled" : ""]; });
  const t = document.createElement("table");
  t.innerHTML = "<thead><tr><th>Run</th><th>Short</th><th>Lights</th><th>Controller</th><th>Light 1 is at</th><th>Reversed</th><th></th></tr></thead><tbody></tbody>";
  for (const row of rows) { const tr = t.tBodies[0].insertRow(); for (const v of row) tr.insertCell().textContent = v; }
  const p = document.createElement("p");
  p.textContent = `Mode: ${W.cfg.mode === "live" ? "Live" : "Practice"} · Time zone: ${W.cfg.timezone} · Location: ${W.cfg.location ? `${W.cfg.location.lat}, ${W.cfg.location.lon}` : "not set"}`;
  $("#summary").replaceChildren(t, p);
  $("#save-where").textContent = `Saved to ${W.info.home}/config.json. The server restarts with it.`;
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
  if (step === 0 && !drv(W.type).available) return "Pick a kind of lights that is supported.";
  if (step === 1 && !W.cfg.controllers.length) return "Add at least one controller.";
  if (step === 2) {
    for (const r of W.cfg.runs) {
      if (!String(r.name).trim()) return "Every run needs a name.";
      if (!(r.lights >= 1 && r.lights <= 255)) return `${r.name}: lights must be 1 to 255.`;
    }
    const names = W.cfg.runs.map(r => r.name.trim().toLowerCase());
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
  if (step === 1) { drawFound(); drawChosen(); }
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
  for (const c of W.cfg.controllers) if (!W.cfg.runs.some(r => r.controller === c.id))
    W.cfg.runs.push({name: c.name || c.ip, short: "", subtitle: "", start: "", controller: c.id, lights: 60, reverse: false, baseline: {brightness: 50, kelvin: 2200}});
  if (W.cfg.controllers.length) W.type = W.cfg.controllers[0].type;
  const pill = $("#mode");
  pill.textContent = W.info.live ? "LIVE" : "PRACTICE";
  pill.className = "pill " + (W.info.live ? "live" : "dry");
  const b = $("#banner");
  if (W.info.error) { b.hidden = false; b.textContent = `Your settings file has a problem: ${W.info.error}. Go through the steps to fix it.`; }
  else if (W.info.configured) $("#back").hidden = false;
  else { b.hidden = false; b.textContent = "Welcome! No settings yet: this wizard sets up your lights. It takes a few minutes."; }
  drawDrivers();
  const sel = $("#add-model");
  for (const d of W.info.drivers.filter(d => d.available))
    for (const [m, label] of Object.entries(d.models)) sel.appendChild(new Option(label, `${d.type}|${m}`));
  $("#scan").onclick = scan;
  $("#add").onclick = () => {
    const ip = $("#add-ip").value.trim(), [type, model] = sel.value.split("|");
    if (!validIp(ip)) return err("Type an IPv4 address like 192.168.1.50.");
    err(""); addController(ip, model, type); $("#add-ip").value = ""; drawChosen(); drawFound();
  };
  $("#geo").onclick = geolocate;
  $("#prev").onclick = () => go(W.step - 1);
  $("#next").onclick = () => (W.step === STEPS - 1 ? save() : go(W.step + 1));
  addEventListener("pagehide", () => { if (Object.keys(W.testing).length) navigator.sendBeacon && navigator.sendBeacon("/api/setup/test/stop", new Blob(["{}"], {type: "application/json"})); });
  go(0);
}

init().catch(e => err(e.message));
