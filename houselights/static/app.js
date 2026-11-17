"use strict";
// House Lights page. One shared state drives every panel: the kits' status (refresh),
// an on-screen preview (PREVIEW) and the frames of what is playing live (LIVEF).
// A single paint loop draws the Visualization strips and each run's strip from it.
const $ = (sel, el = document) => el.querySelector(sel);
// A file in the settings folder, written with the server's separator (backslashes on Windows).
const inHome = (home, name) => home + (home.includes("\\") ? "\\" : "/") + name;
let CONFIG = null;
const CARDS = {};             // section id -> card
const SEC = {};               // section id -> section config
let STATUS = {};              // section id -> {lan, assumed, stream}
let PREVIEW = null;           // {source: "viz"|"card"|"scene", card, pattern, label, runs: {sid: data}}
const LIVEF = {};             // section id -> frames of what it streams, for the pictures
let TARGETS = new Set();      // Quick Settings "Lights" picker
let ZOOM = 0;
const ZOOMS = [0, 8, 12, 18, 26];                      // 0 = fit, else px per light

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 6000 : 2500);
}

const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } },
};

// Same mapping as the backend: fixed-size segments from the start of the run (5 lights on
// Govee H806A); -1 = no segment reaches this light.
const segmentOf = (i, sec) => {
  const lps = sec.lights_per_segment;
  if (!lps) return Math.floor(i * sec.segments / sec.lights);
  const s = Math.floor(i / lps);
  return s < sec.segments ? s : -1;
};
const perSegment = (sec, segs) => Array.from({length: sec.lights}, (_, i) => {
  const s = segmentOf(i, sec);
  return s >= 0 ? (segs[s] || null) : null;
});

function kelvinToHex(k) {                                // rough, for display only
  const t = k / 100;
  const r = t <= 66 ? 255 : 329.7 * Math.pow(t - 60, -0.1332);
  const g = t <= 66 ? 99.47 * Math.log(t) - 161.12 : 288.12 * Math.pow(t - 60, -0.0755);
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.52 * Math.log(t - 10) - 305.04;
  const h = v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
  return "#" + h(r) + h(g) + h(b);
}
const lanHex = lan => lan.colorTemInKelvin ? kelvinToHex(lan.colorTemInKelvin)
  : "#" + [lan.color.r, lan.color.g, lan.color.b].map(v => v.toString(16).padStart(2, "0")).join("");

// A theme that isn't in the list (an unsaved one from the Themes tab, or one deleted since)
// still gets a usable entry, so nothing breaks on it.
const patternById = id => CONFIG.patterns.find(p => p.id === id)
  || {id, label: id === "_draft" ? "Unsaved theme" : `${id} (deleted)`, animated: true, params: {}, categories: [],
      group: "", face: "", describe: id === "_draft" ? "A theme being edited in the Themes tab." : "This theme no longer exists."};
const labelOf = id => id === "warm" ? "Warm white" : patternById(id).label;
const shortName = sid => SEC[sid] ? SEC[sid].short || SEC[sid].name : sid;
const capsOf = sec => sec.caps || {stream: true, pick: true, status: true};
// "50 lights / 10 segments × 5", or what the controller does instead
function runSize(sec) {
  const c = capsOf(sec);
  if (!c.pick && c.stream && c.stream_untested) return `${sec.lights} lights · still themes in one color · Play live untested on this model`;
  if (!c.pick && c.static === "segments") return `${sec.lights} lights · one color at a time`;
  if (sec.lights_per_segment === 1) return `${sec.lights} lights, each its own color` + (c.static === "palette" ? " (up to 30 colors)" : "");
  return `${sec.lights} lights / ${sec.segments} segments × ${sec.lights_per_segment}`;
}
// Which end of the run light 1 is at, as installed: "left", "right" or "" (not checked yet).
// Older settings only have `reverse`. A run whose light 1 is at the right is drawn from the right.
const light1Of = sec => sec.light1 || (sec.reverse ? "right" : "");
const fromRight = sec => light1Of(sec) === "right";
const enabledIds = () => CONFIG.sections.filter(s => s.enabled).map(s => s.id);
const targetIds = () => enabledIds().filter(id => TARGETS.has(id));
const names = ids => ids.map(shortName).join(", ");

// Fill a <select> with themes grouped by their main category ("My themes" first, then
// Everyday, Diwali, ...). Every filled select is remembered so refillPatterns() can bring it
// up to date when themes are saved or deleted (its other options are kept).
const FILLED = new Set();
function fillPatterns(sel, value) {
  const order = CONFIG.categories || [], groups = {};
  for (const og of [...sel.querySelectorAll("optgroup")]) og.remove();
  for (const p of CONFIG.patterns) (groups[p.group] = groups[p.group] || []).push(p);
  for (const g of Object.keys(groups).sort((a, b) => order.indexOf(a) - order.indexOf(b))) {
    const og = document.createElement("optgroup");
    og.label = g;
    for (const p of groups[g]) og.appendChild(new Option(p.label + (p.animated ? "" : " (static)"), p.id));
    sel.appendChild(og);
  }
  sel.value = value;
  FILLED.add(sel);
}
function refillPatterns() {
  for (const sel of FILLED) {
    const v = sel.value;
    fillPatterns(sel, v);
    if (sel.value !== v) sel.dispatchEvent(new Event("change"));        // its theme was deleted
  }
}

// Inputs for a pattern's parameters; readParams() turns them back into a dict.
function buildParams(box, pat) {
  box.innerHTML = "";
  for (const [name, {type, default: def}] of Object.entries(pat.params)) {
    const label = document.createElement("label");
    label.textContent = name.replace("_", " ");
    const inp = document.createElement("input");
    inp.dataset.param = name;
    if (type === "color") { inp.type = "color"; inp.value = def; }
    else if (type === "int" || type === "float") {
      inp.type = "number"; inp.min = 0; inp.value = def; inp.step = type === "float" ? "0.1" : "1";
      if (name === "width") inp.title = "Band width in lights; 0 = one segment";
    } else if (type === "bool") { inp.type = "checkbox"; inp.checked = def; }
    else { inp.type = "text"; inp.value = def; inp.size = 22; inp.title = "Comma-separated #rrggbb colors"; }
    label.appendChild(inp);
    box.appendChild(label);
  }
}
function readParams(box) {
  const params = {};
  for (const inp of box.querySelectorAll("[data-param]"))
    params[inp.dataset.param] = inp.type === "checkbox" ? inp.checked
      : inp.type === "number" ? Number(inp.value) : inp.value;
  return params;
}

// One run's preview from the server. Static themes are shown the way Apply sends them:
// one color per 5-light segment.
async function previewData(sid, pattern, params, seconds = 8, fps = 12) {
  const sec = SEC[sid];
  const p = await api(`/api/sections/${sid}/preview?seconds=${seconds}&fps=${fps}`, {pattern, params});
  return {animated: p.animated, frames: p.frames || null, fps: p.fps || 12,
          lights: p.animated ? p.lights : perSegment(sec, p.segments),
          designed: p.lights, mixed: p.mixed, raw: p, t0: performance.now() / 1000};
}

function setPreview(pv) { PREVIEW = pv; repaintAll(); sync(); }
function clearPreview() { if (PREVIEW) setPreview(null); }

// --- what each run shows ---------------------------------------------------------------------
const streamKey = s => JSON.stringify([s.pattern, s.params, s.since]);

// What the kit shows now, as far as we know: {pattern, live} or null (off / unknown).
function showing(sid) {
  const st = STATUS[sid];
  if (!st) return null;
  if (st.stream) return {pattern: st.stream.pattern, params: st.stream.params, live: true};
  const lan = st.lan, a = st.assumed || {};
  if (lan ? lan.onOff === 0 : a.power === false) return null;
  if (a.pattern === "baseline" || (a.kelvin === 2200 && !a.pattern)) return {pattern: "warm"};
  if (a.pattern && a.segments) return {pattern: a.pattern, params: a.params};
  return null;
}

function stateColors(sid) {
  const sec = SEC[sid], st = STATUS[sid];
  if (!st || !sec.enabled) return null;
  const lan = st.lan, a = st.assumed || {};
  if (lan ? lan.onOff === 0 : a.power === false) return null;
  if (a.segments && a.segments.some(Boolean)) return perSegment(sec, a.segments);
  if (a.kelvin) return Array(sec.lights).fill(kelvinToHex(a.kelvin));
  if (lan) return Array(sec.lights).fill(lanHex(lan));
  return null;
}

const STATIC = {};            // section id -> colors from status, recomputed on refresh
function frameOf(d, now) {
  if (!d.frames) return d.lights;
  return d.frames[Math.floor((now - d.t0) * d.fps) % d.frames.length];
}
function runColors(sid, now) {
  const p = PREVIEW && PREVIEW.runs[sid];
  if (p) return frameOf(p, now);
  const st = STATUS[sid];
  if (st && st.stream) {
    const f = LIVEF[sid];
    return f && f.key === streamKey(st.stream) ? frameOf(f, now) : STATIC[sid];
  }
  return STATIC[sid];
}

// While a kit plays live, fetch the same theme's frames so the pictures can show it.
async function loadLive(sid) {
  const s = STATUS[sid].stream, key = streamKey(s);
  if (LIVEF[sid] && LIVEF[sid].key === key) return;
  LIVEF[sid] = {key, lights: STATIC[sid], frames: null, fps: 12, t0: 0};
  try {
    const d = await previewData(sid, s.pattern, s.params || {});
    if (LIVEF[sid].key === key) LIVEF[sid] = {...d, key};
  } catch (e) { /* the status still works without the picture */ }
}

// --- painting: Visualization strips, each run's strip -------------------------------------
const VDOTS = {}, LAST = {};
function paintDots(els, cols) {
  for (let i = 0; i < els.length; i++) {
    const c = cols && cols[i];
    els[i].style.background = c || "";
    els[i].style.boxShadow = c ? `0 0 6px 1px ${c}` : "none";
  }
}
function repaintAll() { for (const k of Object.keys(LAST)) delete LAST[k]; }
let lastTick = 0;
function paintLoop(ms) {
  if (ms - lastTick > 70 && !document.hidden) {
    lastTick = ms;
    const now = ms / 1000;
    for (const sec of CONFIG.sections) {
      const sid = sec.id, cols = runColors(sid, now);
      if (LAST[sid] === cols) continue;
      LAST[sid] = cols;
      paintDots(VDOTS[sid], cols);
      paintDots(CARDS[sid].lightEls, cols);
    }
  }
  requestAnimationFrame(paintLoop);
}

// --- the theme as text (e.g. for an app's AI mode) ----------------------------------------------------------------------------
const NAMED = [["red", "#ff0000"], ["saffron", "#ff6a00"], ["orange", "#ff8c00"], ["amber", "#ffb000"],
  ["gold", "#ffc800"], ["yellow", "#ffe600"], ["green", "#00a000"], ["lime", "#7cfc00"], ["cyan", "#00ffff"],
  ["sky blue", "#87ceeb"], ["blue", "#0000ff"], ["purple", "#8000ff"], ["magenta", "#ff00ff"],
  ["deep pink", "#d0007a"], ["pink", "#ff69b4"], ["white", "#ffffff"], ["warm white", "#ffd8a8"]];
const rgbOf = h => [1, 3, 5].map(k => parseInt(h.slice(k, k + 2), 16));
function colorName(hex) {
  const [r, g, b] = rgbOf(hex);
  let best = NAMED[0], bd = Infinity;
  for (const n of NAMED) {
    const [R, G, B] = rgbOf(n[1]), d = (r - R) ** 2 + (g - G) ** 2 + (b - B) ** 2;
    if (d < bd) { bd = d; best = n; }
  }
  return best[0];
}
function runsOf(arr) {
  const out = [];
  for (const c of arr) {
    if (out.length && out[out.length - 1].hex === c) out[out.length - 1].count++;
    else out.push({hex: c, count: 1});
  }
  return out;
}
function aiText(card, lights) {
  const {sec, el} = card, n = lights.length;
  const pat = patternById($('[data-act="pattern"]', el).value);
  const bright = $('[data-act="brightness"]', el).value || 100;
  const lines = [`${sec.name}${sec.subtitle ? " (" + sec.subtitle + ")" : ""}: ${n} lights, light 1 at the ${sec.start || "start of the run"}.`,
    `Pattern: ${pat.label}. ${pat.animated ? "Dynamic" : "Static"}, brightness ${bright}%.`];
  if (pat.animated) { lines.push(pat.describe); return lines.join("\n"); }
  const named = r => `${r.count} ${colorName(r.hex)} (${r.hex})`;
  let period = 0;
  for (let p = 1; p <= n / 2 && !period; p++)
    if (lights.every((c, i) => i < p || c === lights[i - p])) period = p;
  const runs = runsOf(lights);
  if (period) lines.push(`Repeat this sequence along the whole strip: ${runsOf(lights.slice(0, period)).map(named).join(", ")}.`);
  else if (runs.length > 12) lines.push(`Smooth gradient from ${colorName(lights[0])} (${lights[0]}) at light 1 to `
      + `${colorName(lights[n - 1])} (${lights[n - 1]}) at light ${n}.`);
  else lines.push("From light 1 to light " + n + ": " + runs.map(r =>
      `${colorName(r.hex)} (${r.hex}) ${Math.round(r.count * 100 / n)}% = ${r.count} lights`).join(", ") + ".");
  return lines.join("\n");
}
function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea");          // plain http on the LAN: no Clipboard API
  ta.value = text; document.body.appendChild(ta); ta.select();
  const ok = document.execCommand("copy"); ta.remove();
  return ok ? Promise.resolve() : Promise.reject(new Error("Copy failed; select the text instead"));
}

// --- color presets ------------------------------------------------------------------------
const PRESETS = [
  ["Whites", [["Candle 2000 K", "#ff8a2a", 2000], ["Warm white 2200 K", "#ffa04a", 2200], ["Soft white 2700 K", "#ffb46b", 2700],
    ["Warm 3000 K", "#ffc285", 3000], ["Neutral 4000 K", "#ffdcb8", 4000], ["Daylight 5000 K", "#ffeedd", 5000],
    ["Cool 6500 K", "#fff9fd", 6500], ["Ice white", "#e8f4ff"]]],
  ["Festival golds", [["Diya orange", "#ff8a1c"], ["Saffron", "#ff6a00"], ["Marigold", "#ffa800"], ["Amber", "#ffb000"],
    ["Gold", "#ffc800"], ["Honey", "#ffd36b"], ["Copper", "#e0662a"], ["Pumpkin", "#ff7518"]]],
  ["Reds and pinks", [["Red", "#ff0000"], ["Crimson", "#dc143c"], ["Ruby", "#c8003c"], ["Rose", "#ff3d7f"],
    ["Rangoli magenta", "#e0007a"], ["Hot pink", "#ff1493"], ["Pink", "#ff7ab6"], ["Coral", "#ff6f61"]]],
  ["Greens", [["India green", "#138808"], ["Green", "#00b050"], ["Evergreen", "#0b6b2e"], ["Holly", "#0f7a3a"],
    ["Emerald", "#00c878"], ["Lime", "#7cfc00"], ["Mint", "#5cffb0"], ["Teal", "#00a3a3"]]],
  ["Blues and purples", [["Blue", "#0060ff"], ["Royal blue", "#2a3fff"], ["Sky", "#3fa9ff"], ["Cyan", "#00e5ff"],
    ["Navy", "#001f8a"], ["Indigo", "#4b00c8"], ["Purple", "#8a2be2"], ["Lavender", "#c49bff"]]],
  ["Specials", [["Sunset", "#ff4e1f"], ["Peacock", "#00897b"], ["Ocean", "#0077b6"], ["Orchid", "#da70d6"],
    ["Plum", "#8e2a8e"], ["Violet", "#a24bff"], ["Ice blue", "#9fd8ff"], ["Snow", "#ffffff"]]],
];

// --- light-run panels ----------------------------------------------------------------------------
function drawStatus(card) {
  const {el, sec} = card, status = STATUS[sec.id];
  const box = $(".status", el), st = status && status.stream;
  if (!sec.enabled) { box.textContent = "not enabled"; return; }
  const lan = status && status.lan;
  if (!lan) box.innerHTML = '<span class="dot"></span>' + (capsOf(sec).status === false ? "status not reported by this controller" : "no reply") + (st ? `<br><span class="live-tag">● Playing ${labelOf(st.pattern)}</span>` : "");
  else {
    const col = lan.colorTemInKelvin ? `${lan.colorTemInKelvin} K` : `rgb ${lan.color.r},${lan.color.g},${lan.color.b}`;
    box.innerHTML = `<span class="dot ${lan.onOff ? "on" : ""}"></span>${lan.onOff ? "On" : "Off"} · ${lan.brightness}%`
      + (st ? `<br><span class="live-tag">● Playing ${labelOf(st.pattern)}</span>`
            : `<br><span class="swatch" style="background:${lanHex(lan)}"></span> ${col}`);
    const slider = $('[data-act="brightness"]', el);
    if (document.activeElement !== slider) { slider.value = lan.brightness; slider.nextElementSibling.value = lan.brightness; }
  }
}

function buildStrip(card) {
  const {el, sec} = card, strip = $(".strip", el);
  strip.classList.toggle("rev", fromRight(sec));        // light 1 at the right end: drawn right to left
  card.lightEls = []; card.segEls = [];
  for (let s = 0; s < sec.segments; s++) {
    const seg = document.createElement("div");
    seg.className = "seg"; seg.tabIndex = 0; seg.setAttribute("role", "button");
    seg.title = `Segment ${s + 1}`;
    for (let i = 0; i < sec.lights; i++) {
      if (segmentOf(i, sec) !== s) continue;
      const d = document.createElement("span");
      d.className = "light";
      card.lightEls[i] = d;
      seg.appendChild(d);
    }
    const toggle = () => { if (!sec.enabled || !capsOf(sec).pick) return; card.selected.has(s) ? card.selected.delete(s) : card.selected.add(s); drawMeta(card); };
    seg.onclick = toggle;
    seg.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
    card.segEls.push(seg);
    strip.appendChild(seg);
  }
  if (sec.reachable < sec.lights) {
    const rest = document.createElement("div");
    rest.className = "seg unreach";
    rest.title = `Lights ${sec.reachable + 1}–${sec.lights}: no segment reaches these. Whole-kit color, brightness and Play live still apply.`;
    for (let i = sec.reachable; i < sec.lights; i++) {
      const d = document.createElement("span");
      d.className = "light"; card.lightEls[i] = d; rest.appendChild(d);
    }
    strip.appendChild(rest);
  }
  card.lightEls = Array.from({length: sec.lights}, (_, i) => card.lightEls[i] || document.createElement("span"));
}

// Text under the strip, selection and the "rounded" marks.
function drawMeta(card) {
  const {el, sec} = card, status = STATUS[sec.id];
  const p = PREVIEW && PREVIEW.runs[sec.id], st = status && status.stream, a = status && status.assumed;
  let what;
  if (p) what = `Preview (on screen only): ${PREVIEW.label}` + (!p.animated && p.mixed && p.mixed.some(Boolean) ? " · dots mark segments rounded to one color" : "");
  else if (st) what = `Playing live: ${labelOf(st.pattern)} since ${st.since}`;
  else if (a && a.segments && a.segments.some(Boolean)) what = `Last applied: ${a.pattern ? labelOf(a.pattern) : "custom"} (${a.mode}, ${a.updated})`;
  else if (status && status.lan) what = "Whole-kit color from the kit";
  else what = sec.enabled ? "Status unknown" : "Disabled";
  $(".what", el).textContent = what;
  const mixed = p && !p.animated ? p.mixed : null;
  card.segEls.forEach((s, i) => {
    s.classList.toggle("selected", card.selected.has(i));
    s.classList.toggle("mixed", !!(mixed && mixed[i]));
  });
  $(".strip", el).classList.toggle("preview", !!p);
  const n = card.selected.size;
  const pick = capsOf(sec).pick, unit = sec.lights_per_segment === 1 ? "light" : "segment";
  $(".sel", el).textContent = !pick ? (capsOf(sec).static === "segments" ? "This controller shows one color at a time"
      : "Picking single lights isn't supported on this controller")
    : n ? `${n} ${unit}${n > 1 ? "s" : ""} selected` : `Tap ${unit}s to select`;
  $('[data-act="segments"]', el).disabled = !n || !pick;
}

function patternBody(card) {
  return {pattern: $('[data-act="pattern"]', card.el).value, params: readParams($(".params", card.el))};
}

function sentMsg(r) { return r.mode === "dry" ? "Dry run: logged, nothing sent" : "Sent"; }

async function pollJob(card, job) {
  const line = $(".job", card.el), cancel = $('[data-act="cancel"]', card.el);
  cancel.hidden = false;
  cancel.onclick = () => api(`/api/jobs/${job.id}/cancel`, {}).catch(e => toast(e.message, true));
  while (true) {
    const j = await api(`/api/jobs/${job.id}`).catch(() => null);
    if (!j) break;
    const dry = j.mode === "dry" ? " (dry run)" : "";
    const unit = "packet";
    line.textContent = `${j.label}: ${j.status} ${j.done}/${j.total} ${unit}${j.total > 1 ? "s" : ""}${dry}`
      + (j.error ? ` · ${j.error}` : "");
    if (!["queued", "running"].includes(j.status)) break;
    await new Promise(r => setTimeout(r, 500));
  }
  cancel.hidden = true;
  afterAction();
}

async function act(card, fn) {
  try { const r = await fn(); if (r && r.job) pollJob(card, r.job); else toast(sentMsg(r)); afterAction(); }
  catch (e) { toast(e.message, true); }
}

function onPatternChange(card) {
  const {el} = card, pat = patternById($('[data-act="pattern"]', el).value);
  buildParams($(".params", el), pat);
  $(".describe", el).textContent = pat.describe || "";
  $(".ai-box", el).hidden = true;
  if (PREVIEW && PREVIEW.source === "card" && PREVIEW.card === card.sec.id) clearPreview();
  sync();
}

function buildCard(sec) {
  const el = $("#section-tpl").content.firstElementChild.cloneNode(true);
  const card = CARDS[sec.id] = {el, sec, selected: new Set(), picked: {name: "Warm white 2200 K", hex: "#ffa04a", kelvin: 2200}, syncedKey: null};
  $(".name", el).textContent = sec.name;
  $(".sub", el).textContent = [sec.subtitle, sec.ip + (sec.zone ? ` · ${sec.zone}` : ""), runSize(sec)
      + (sec.reachable < sec.lights ? ` (last ${sec.lights - sec.reachable} not reachable by segment)` : ""),
    fromRight(sec) && "light 1 at the right"
  ].filter(Boolean).join(" · ");
  if (sec.tier && sec.tier !== "full" && sec.tier_note) $(".sub", el).title = `${sec.model_label || ""}: ${sec.tier_note}`;
  if (!sec.enabled) el.classList.add("disabled");
  el.classList.add("collapsed");
  $('[data-act="more"]', el).onclick = () => {
    const c = el.classList.toggle("collapsed");
    $('[data-act="more"]', el).textContent = c ? "More" : "Less";
  };
  buildStrip(card);
  const url = `/api/sections/${sec.id}`, pick = $('[data-act="color-pick"]', el);

  $('[data-act="on"]', el).onclick = () => act(card, () => api(`${url}/power`, {on: true}));
  $('[data-act="off"]', el).onclick = () => act(card, () => api(`${url}/power`, {on: false}));
  const slider = $('[data-act="brightness"]', el);
  slider.oninput = () => { slider.nextElementSibling.value = slider.value; };
  slider.onchange = () => act(card, () => api(`${url}/brightness`, {value: Number(slider.value)}));

  // color: presets, whole kit, selected segments
  const box = $(".presets", el);
  box.innerHTML = PRESETS.map(([g, cs]) => `<div class="pgroup"><span class="lbl">${g}</span><div class="sw">`
    + cs.map(([n, h, k]) => `<button type="button" style="background:${h}" title="${n}" aria-label="${n}" data-hex="${h}" data-k="${k || ""}"></button>`).join("")
    + "</div></div>").join("");
  box.onclick = e => {
    const b = e.target.closest("[data-hex]");
    if (!b) return;
    pick.value = b.dataset.hex;
    card.picked = {name: b.title, hex: b.dataset.hex, kelvin: Number(b.dataset.k) || null};
    $(".picked", el).textContent = `Picked: ${b.title}. Press Whole kit or Selected segments to send it.`;
    box.hidden = true;
  };
  $('[data-act="presets"]', el).onclick = () => { box.hidden = !box.hidden; };
  pick.oninput = () => { card.picked = {name: "your color", hex: pick.value, kelvin: null}; $(".picked", el).textContent = `Picked: ${pick.value}`; };
  $('[data-act="color"]', el).onclick = () => act(card, () => api(`${url}/color`,
    card.picked.kelvin && pick.value === card.picked.hex ? {kelvin: card.picked.kelvin} : {color: pick.value}));
  $('[data-act="segments"]', el).onclick = () => act(card, async () => {
    const r = await api(`${url}/segments`, {segments: [...card.selected], color: pick.value});
    card.selected.clear(); drawMeta(card);
    return r;
  });
  $('[data-act="restore"]', el).onclick = () => {
    const b = sec.baseline;
    if (confirm(`Restore ${sec.name} to on, ${b.kelvin} K, brightness ${b.brightness}?`)) act(card, () => api(`${url}/restore`, {}));
  };

  // theme
  const sel = $('[data-act="pattern"]', el);
  fillPatterns(sel, "diya_glow");
  sel.onchange = () => onPatternChange(card);
  $(".params", el).addEventListener("input", () => {
    if (PREVIEW && PREVIEW.source === "card" && PREVIEW.card === sec.id) card.doPreview(true);
  });
  card.doPreview = async (keep) => {
    const body = patternBody(card);
    if (!keep && PREVIEW && PREVIEW.source === "card" && PREVIEW.card === sec.id && PREVIEW.pattern === body.pattern) return clearPreview();
    try {
      const d = await previewData(sec.id, body.pattern, body.params);
      setPreview({source: "card", card: sec.id, pattern: body.pattern, label: labelOf(body.pattern), runs: {[sec.id]: d}});
      const p = d.raw;
      $(".job", el).textContent = p.animated ? "Animated theme: Play live streams it light by light"
        : p.path === "lan" && p.calls === 1 ? "One color: 1 command"
        : `${p.calls} packets, about ${p.estimate_s} s`
          + (p.reachable < sec.lights ? ` · last ${sec.lights - p.reachable} lights not reachable by segment` : "");
      if (!$(".ai-box", el).hidden) $(".ai", el).textContent = aiText(card, d.designed);
    } catch (e) { toast(e.message, true); }
  };
  $('[data-act="preview"]', el).onclick = () => card.doPreview(false);
  $('[data-act="ai"]', el).onclick = async () => {
    try {
      const body = patternBody(card), d = await previewData(sec.id, body.pattern, body.params, 1, 4);
      $(".ai", el).textContent = aiText(card, d.designed);
      $(".ai-box", el).hidden = false;
    } catch (e) { toast(e.message, true); }
  };
  $('[data-act="copy"]', el).onclick = () =>
    copyText($(".ai", el).textContent).then(() => toast("Copied")).catch(e => toast(e.message, true));
  $('[data-act="play"]', el).onclick = () => {
    const body = patternBody(card);
    clearPreview();
    if (patternById(body.pattern).animated) act(card, () => api(`${url}/play`, {...body, level: 100}));
    else act(card, () => api(`${url}/pattern`, body));
  };
  $('[data-act="stop"]', el).onclick = () => act(card, () => api(`${url}/stop`, {}));
  onPatternChange(card);
  return el;
}

// --- Quick Settings ---------------------------------------------------------------------------
// Tiles: every theme marked as a tile, in category order, plus plain warm white first.
const WARM_TILE = {id: "warm", label: "Warm white", animated: false, categories: ["Everyday"],
  face: "#ffd8a8,#ffb36b", describe: "Plain warm white, 2200 K."};
let CAT = "All";
// Favourites first (starred in the Themes tab), then your own themes, then the built-ins in
// category order. Built-in groups hidden in the Themes tab are left out (unless starred).
const themePrefs = () => CONFIG.theme_prefs || {favourites: [], hidden_groups: []};
function tileList() {
  const order = CONFIG.categories || [], {favourites, hidden_groups} = themePrefs();
  const fav = id => { const k = favourites.indexOf(id); return k < 0 ? 1e6 : k; };
  const list = CONFIG.patterns.filter(p => p.tile && (favourites.includes(p.id) || p.custom
    || !p.categories.some(c => hidden_groups.includes(c))));
  return [WARM_TILE, ...list.map(p => favourites.includes(p.id) ? {...p, categories: ["Favourites", ...p.categories]} : p)
    .sort((a, b) => fav(a.id) - fav(b.id) || order.indexOf(a.group) - order.indexOf(b.group))];
}
// Two stops at least: a one-color face would be an invalid gradient.
const faceGradient = face => { const c = (face || "#888888").split(","); return `linear-gradient(90deg, ${(c.length > 1 ? c : [c[0], c[0]]).join(",")})`; };

// The Quick Settings tiles and their category pull-down; rebuilt when themes change.
function buildTiles() {
  const box = $("#tiles"), tiles = tileList();
  box.innerHTML = "";
  for (const pat of tiles) {
    const b = document.createElement("button");
    b.className = "tile"; b.dataset.p = pat.id; b.dataset.cats = pat.categories.join("|");
    b.style.setProperty("--g", faceGradient(pat.face));
    b.innerHTML = `<span class="tile-face"></span><span class="tile-label"></span><span class="tile-st"></span>`;
    b.querySelector(".tile-label").textContent = (themePrefs().favourites.includes(pat.id) ? "★ " : "") + pat.label;
    b.title = pat.describe || pat.label;
    b.onclick = () => quickTheme(pat.id);
    box.appendChild(b);
  }
  // category pull-down: All, Favourites, then each category that has tiles
  const cat = $("#cat"), used = new Set(tiles.flatMap(t => t.categories));
  cat.innerHTML = "";
  cat.appendChild(new Option(`All (${tiles.length})`, "All"));
  for (const c of ["Favourites", ...(CONFIG.categories || [])]) if (used.has(c))
    cat.appendChild(new Option(`${c} (${tiles.filter(t => t.categories.includes(c)).length})`, c));
  const saved = store.get("hl-cat");
  CAT = [...cat.options].some(o => o.value === saved) ? saved : "All";
  cat.value = CAT;
  cat.onchange = () => { CAT = cat.value; store.set("hl-cat", CAT); applyCat(); };
  applyCat();
}

// After themes are saved, deleted, imported or starred (Themes tab): new lists everywhere.
function themesChanged(d) {
  CONFIG.patterns = d.patterns;
  CONFIG.categories = d.categories;
  CONFIG.theme_prefs = d.prefs;
  refillPatterns();
  buildTiles();
  if (typeof syncVizTheme === "function") syncVizTheme();
  sync();
}
const TILES_SHOWN = () => 12;      // visible at once: 4 x 3, phones 3 x 4 (style.css)
function applyCat() {
  let n = 0;
  for (const b of $("#tiles").children) {
    const show = CAT === "All" || b.dataset.cats.split("|").includes(CAT);
    b.hidden = !show;
    if (show) n++;
  }
  $("#tiles").scrollTop = 0;
  $("#tiles-more").textContent = n > TILES_SHOWN() ? `Showing ${TILES_SHOWN()} of ${n} themes. Scroll the tiles for the rest.` : `${n} theme${n === 1 ? "" : "s"}`;
}

async function quickTheme(id) {
  const ids = targetIds();
  if (!ids.length) return toast("Pick some lights first", true);
  clearPreview();
  if (id !== "warm") { $("#viz-theme").value = id; syncVizTheme(); }
  try {
    if (id === "warm") {
      await Promise.all(ids.map(s => api(`/api/sections/${s}/color`, {kelvin: 2200})));
      toast(CONFIG.mode === "dry" ? "Dry run: warm white logged" : "Warm white");
    } else if (patternById(id).animated) {
      const r = await api("/api/play-all", {pattern: id, params: {}, level: 100, sections: ids});
      toast((r.mode === "dry" ? "Dry run: " : "Playing ") + labelOf(id)
        + (r.still && r.still.length ? ` (a still picture on ${names(r.still)}: those controllers can't animate)` : "")
        + (Object.keys(r.skipped || {}).length ? ` · skipped ${names(Object.keys(r.skipped))}` : ""));
    } else {
      const r = await api("/api/apply-all", {pattern: id, params: {}, sections: ids});
      toast((r.mode === "dry" ? "Dry run: " : "Applied ") + labelOf(id));
    }
  } catch (e) { toast(e.message, true); }
  afterAction();
}

function buildQuick() {
  const tg = $("#targets");
  tg.innerHTML = `<button data-t="all">Whole house</button>`
    + CONFIG.sections.map(s => `<button data-t="${s.id}"${s.enabled ? "" : " disabled"}>${shortName(s.id)}</button>`).join("");
  tg.onclick = e => {
    const b = e.target.closest("[data-t]");
    if (!b) return;
    const all = enabledIds();
    if (b.dataset.t === "all") TARGETS = new Set(all.every(id => TARGETS.has(id)) ? [] : all);
    else TARGETS.has(b.dataset.t) ? TARGETS.delete(b.dataset.t) : TARGETS.add(b.dataset.t);
    store.set("hl-targets", [...TARGETS].join(","));
    sync();
  };
  buildTiles();
  const allPower = on => async () => {
    const ids = targetIds();
    if (!ids.length) return toast("Pick some lights first", true);
    try {
      const r = await api("/api/power-all", {on, sections: ids});
      toast((r.mode === "dry" ? "Dry run: " : "") + (on ? "On: " : "Off: ") + names(r.done));
    } catch (e) { toast(e.message, true); }
    afterAction();
  };
  $("#all-on").onclick = allPower(true);
  $("#all-off").onclick = $("#bar-off").onclick = allPower(false);
  $("#bar-stop").onclick = async () => {
    try { await api("/api/stop-all", {}); toast("Stopped. The lights stay on."); } catch (e) { toast(e.message, true); }
    afterAction();
  };
  $("#bar-top").onclick = () => { setTab("quick"); scrollTo(0, 0); };
}

// --- Visualization -----------------------------------------------------------------------------
function syncVizTheme() {
  const p = patternById($("#viz-theme").value);
  $("#viz-describe").textContent = p.describe || "Static theme: Apply sets it as segment colors on each kit.";
  $("#viz-play").textContent = p.animated ? "Play live" : "Apply";
}

function buildViz() {
  // flat strips, one row per run, with segment numbers underneath. Each run is drawn the way it's
  // installed (light 1 at the right end: right to left) and to scale (the longest run is full width).
  const longest = Math.max(1, ...CONFIG.sections.map(s => s.lights));
  $("#vruns").innerHTML = CONFIG.sections.map(s => {
    const lps = s.lights_per_segment >= 3 ? s.lights_per_segment : 10, segs = Math.ceil(s.lights / lps);
    const label = k => s.lights_per_segment >= 3 ? k + 1 : k * lps + 1;   // segment numbers, or light numbers
    const ticks = Array.from({length: segs}, (_, k) => `<span style="grid-column:span ${Math.min(lps, s.lights - k * lps)}">${label(k)}</span>`).join("");
    const rev = fromRight(s);
    return `<div class="vrun${rev ? " rev" : ""}"><div class="vl"><b>${esc(s.name)}</b><span>${s.lights} lights · light 1 ${rev ? "right" : "left"}</span><span data-vs="${s.id}"></span></div>
      <div class="dots" data-n="${s.lights}" data-v="${s.id}">${"<i></i>".repeat(s.lights)}</div>
      <div class="ticks" data-n="${s.lights}">${ticks}</div></div>`;
  }).join("");
  $("#strips").classList.toggle("few", CONFIG.sections.length <= 3);
  for (const s of CONFIG.sections) VDOTS[s.id] = [...document.querySelectorAll(`[data-v="${s.id}"] i`)];
  const setZoom = z => {
    ZOOM = Math.max(0, Math.min(ZOOMS.length - 1, z));
    const px = ZOOMS[ZOOM];
    $("#strips").classList.toggle("fit", !px);
    for (const el of document.querySelectorAll("#vruns .dots, #vruns .ticks")) {
      el.style.gridTemplateColumns = px ? `repeat(${el.dataset.n}, ${px}px)` : `repeat(${el.dataset.n}, minmax(0, 1fr))`;
      el.style.width = px ? "" : `${(100 * el.dataset.n / longest).toFixed(3)}%`;    // same spacing on every run
    }
    $("#z-lbl").textContent = px ? `${px} px per light: scroll sideways to see the rest` : "Fit: the longest run fills the width, the others to scale";
    $("#z-out").disabled = !ZOOM; $("#z-in").disabled = ZOOM === ZOOMS.length - 1;
    $("#z-fit").classList.toggle("on", !ZOOM);
  };
  $("#z-in").onclick = () => setZoom(ZOOM + 1);
  $("#z-out").onclick = () => setZoom(ZOOM - 1);
  $("#z-fit").onclick = () => setZoom(0);
  setZoom(0);

  fillPatterns($("#viz-theme"), "diya_glow");
  $("#viz-theme").onchange = () => { syncVizTheme(); if (PREVIEW && PREVIEW.source === "viz") vizPreview(true); else sync(); };
  syncVizTheme();
  $("#viz-preview").onclick = () => vizPreview(false);
  $("#viz-play").onclick = async () => {
    const ids = targetIds(), pattern = $("#viz-theme").value;
    if (!ids.length) return toast("Pick some lights in Quick Settings first", true);
    clearPreview();
    try {
      if (patternById(pattern).animated) {
        const r = await api("/api/play-all", {pattern, params: {}, level: Number($("#viz-level").value) || 100, sections: ids});
        const skipped = Object.keys(r.skipped || {});
        toast((r.mode === "dry" ? "Dry run: " : "Playing on ") + names(r.started) + (skipped.length ? ` (skipped ${names(skipped)})` : ""));
      } else {
        const r = await api("/api/apply-all", {pattern, params: {}, sections: ids});
        toast((r.mode === "dry" ? "Dry run: " : "Applied on ") + names(Object.keys(r.jobs || {})));
      }
    } catch (e) { toast(e.message, true); }
    afterAction();
  };
  $("#viz-stop").onclick = async () => {
    const ids = targetIds().filter(id => STATUS[id] && STATUS[id].stream);
    try { await Promise.all(ids.map(id => api(`/api/sections/${id}/stop`, {}))); toast(`Stopped ${names(ids)}. The lights stay on.`); }
    catch (e) { toast(e.message, true); }
    afterAction();
  };
}

async function vizPreview(keep) {
  const pattern = $("#viz-theme").value, ids = targetIds();
  if (!keep && PREVIEW && PREVIEW.source === "viz") return clearPreview();
  if (!ids.length) return toast("Pick some lights in Quick Settings first", true);
  try {
    const runs = {};
    await Promise.all(ids.map(async id => { runs[id] = await previewData(id, pattern, {}); }));
    const t0 = performance.now() / 1000;
    Object.values(runs).forEach(d => { d.t0 = t0; });
    setPreview({source: "viz", pattern, label: labelOf(pattern), runs});
  } catch (e) { toast(e.message, true); }
}

// --- tabs ---------------------------------------------------------------------------------
const TABS = ["quick", "ctrl", "themes", "settings"];
function setTab(t) {
  for (const b of document.querySelectorAll("[data-tab]")) b.setAttribute("aria-selected", String(b.dataset.tab === t));
  for (const id of TABS) $("#tab-" + id).hidden = id !== t;
  store.set("hl-tab", t);
  repaintAll();
}

// Called by the Themes tab's "Show on Your house": back to the first tab, preview there.
// runs: {section id: preview data} (several for a whole-house theme); label: the theme's name.
function showInViz(runs, label) {
  const t0 = performance.now() / 1000;
  setPreview({source: "scene", pattern: "", label: label + " (Themes tab)",
              runs: Object.fromEntries(Object.entries(runs).map(([sid, d]) => [sid, {...d, t0}]))});
  setTab("quick");
  $("#viz").scrollIntoView({behavior: "smooth"});
}

// --- keep every panel in step -----------------------------------------------------------------
function sync() {
  if (!CONFIG) return;
  const ids = targetIds(), all = enabledIds();
  for (const b of document.querySelectorAll("#targets [data-t]"))
    b.classList.toggle("on", b.dataset.t === "all" ? all.length > 0 && all.every(id => TARGETS.has(id)) : TARGETS.has(b.dataset.t));

  // tiles stay lit while a run plays (animated) or shows (static) that theme
  for (const t of document.querySelectorAll(".tile")) {
    const id = t.dataset.p, on = all.filter(sid => { const s = showing(sid); return s && s.pattern === id; });
    const anim = id !== "warm" && patternById(id).animated;
    t.classList.toggle("on", on.length > 0);
    $(".tile-st", t).textContent = on.length ? `${anim ? "● Playing on" : "● Showing on"} ${names(on)}` : anim ? "animated" : "static";
  }
  const live = all.filter(sid => STATUS[sid] && STATUS[sid].stream);
  $("#now-playing").innerHTML = live.length
    ? "Playing live: " + live.map(sid => `<b>${shortName(sid)} · ${labelOf(STATUS[sid].stream.pattern)}</b>`).join(", ")
    : `Nothing playing live. Tap a theme to play it on ${ids.length === all.length ? "the whole house" : names(ids) || "the lights you pick"}.`;
  $("#bar-stop").disabled = !live.length;

  // visualization
  const vk = $("#viz-theme").value;
  $("#viz-target").textContent = ids.length ? `Preview and Play live act on: ${names(ids)} (picked in Quick Settings)`
    : "No lights picked in Quick Settings";
  $("#viz-preview").classList.toggle("on", !!PREVIEW && PREVIEW.source === "viz");
  $("#viz-play").classList.toggle("on", ids.length > 0 && ids.every(id => { const s = showing(id); return s && s.pattern === vk; }));
  $("#viz-stop").disabled = !ids.some(id => STATUS[id] && STATUS[id].stream);
  const badge = $("#vbadge");
  if (PREVIEW) { badge.className = "vbadge preview"; badge.textContent = `PREVIEW · ON SCREEN ONLY · ${PREVIEW.label.toUpperCase()}`; }
  else if (live.length && CONFIG.mode === "dry") { badge.className = "vbadge dry"; badge.textContent = "DRY RUN · NOTHING SENT"; }
  else if (live.length) { badge.className = "vbadge live"; badge.textContent = "LIVE · ON THE LIGHTS"; }
  else { badge.className = "vbadge idle"; badge.textContent = "AS THE LIGHTS ARE NOW"; }
  const mixedRuns = PREVIEW ? Object.entries(PREVIEW.runs).filter(([, d]) => !d.animated && d.mixed && d.mixed.some(Boolean)) : [];
  $("#viz-note").textContent = mixedRuns.length
    ? `Static theme, shown the way Apply sends it: one color per 5-light segment (rounded on ${names(mixedRuns.map(([sid]) => sid))}).` : "";
  for (const s of CONFIG.sections) {
    const p = PREVIEW && PREVIEW.runs[s.id], st = STATUS[s.id], now = showing(s.id);
    $(`[data-vs="${s.id}"]`).textContent = p ? `Preview: ${PREVIEW.label}` : st && st.stream ? `Playing ${labelOf(st.stream.pattern)}`
      : now ? labelOf(now.pattern) : st && st.lan && st.lan.onOff === 0 ? "Off" : "";
  }

  // light-run panels
  for (const card of Object.values(CARDS)) {
    const {el, sec} = card, st = STATUS[sec.id], s = showing(sec.id), sel = $('[data-act="pattern"]', el);
    if (st && st.stream) {                       // follow what it plays, once per new stream
      const key = streamKey(st.stream);
      if (card.syncedKey !== key) { card.syncedKey = key; if (sel.value !== st.stream.pattern) { sel.value = st.stream.pattern; onPatternChange(card); return; } }
    }
    const pat = patternById(sel.value);
    const lanOn = st && st.lan ? st.lan.onOff === 1 : st && st.assumed ? st.assumed.power !== false : null;
    $('[data-act="on"]', el).classList.toggle("on", lanOn === true);
    $('[data-act="off"]', el).classList.toggle("on", lanOn === false);
    const play = $('[data-act="play"]', el);
    play.textContent = pat.animated ? (capsOf(sec).stream ? (capsOf(sec).stream_untested ? "Play live (try it)" : "Play live") : "Show still") : "Apply";
    play.classList.toggle("on", !!s && s.pattern === sel.value);
    $('[data-act="stop"]', el).disabled = !(st && st.stream);
    $('[data-act="preview"]', el).classList.toggle("on", !!PREVIEW && PREVIEW.source === "card" && PREVIEW.card === sec.id);
    drawMeta(card);
  }
  if (typeof Themes !== "undefined") Themes.sync();
}

// After a command: a fast read (no LAN round trip) at once, then a full one. A slower read
// that started before the command is dropped, so it can't show the old state.
let lastAction = 0;
function afterAction() {
  lastAction = performance.now();
  refresh(true);
  setTimeout(() => refresh(), 1500);
}

async function refresh(fast = false) {
  const started = performance.now();
  try {
    const st = await api(fast ? "/api/status?lan=false" : "/api/status");
    if (started < lastAction) return;
    STATUS = st.sections;
    for (const [sid, s] of Object.entries(STATUS)) {
      if (!SEC[sid]) continue;
      STATIC[sid] = stateColors(sid);
      if (s.stream) loadLive(sid); else delete LIVEF[sid];
      drawStatus(CARDS[sid]);
    }
    repaintAll();
    sync();
  } catch (e) { toast("Status: " + e.message, true); }
}

// --- Settings tab --------------------------------------------------------------------------------
const esc = t => String(t).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
const LIGHT1_TEXT = {left: "Left end", right: "Right end", "": "Not tested"};
function buildSettings() {
  // Runs in order along the house, left to right as you face it.
  const rows = CONFIG.sections.map(s => {
    const l1 = light1Of(s), size = s.lights;
    return `<tr${s.enabled ? "" : ' class="off"'}><td>${esc(s.name)}${s.enabled ? "" : ' <span class="muted">(disabled)</span>'}</td>
    <td>${esc(s.short)}</td><td>${size}</td>
    <td>${esc(s.model)} · ${esc(s.ip)}${s.zone ? " · " + esc(s.zone) : ""}</td>
    <td${l1 ? "" : ' class="muted"'}>${LIGHT1_TEXT[l1] || esc(l1)}</td>
    <td><a class="button small" href="setup.html?step=test&amp;controller=${encodeURIComponent(s.controller)}"
      title="Test ${esc(s.name)} in the setup wizard: count, direction and colors">Test</a></td></tr>`;
  }).join("");
  $("#settings-body").innerHTML = `
    <div class="tablewrap"><table class="settings-table"><thead><tr><th>Run</th><th>Short name</th><th># Lights / LEDs</th>
      <th>Controller</th><th>Light 1 is at</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted">Runs are listed in order along the house, left to right as you face it.</p>
    <p>Mode: <b>${CONFIG.mode === "live" ? "Live (sends to the lights)" : "Practice (nothing is sent)"}</b> ·
      Time zone: <b>${esc(CONFIG.timezone)}</b> ·
      Location: <b>${CONFIG.location ? "set (sunrise/sunset schedules work)" : "not set (clock-time schedules only)"}</b></p>
    <p class="muted">Settings file: ${esc(inHome(CONFIG.home, "config.json"))}</p>`;
}

// --- light / dark ------------------------------------------------------------------------------
function curTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
function paintTheme() {
  const t = curTheme();
  $("#th-light").classList.toggle("on", t === "light");
  $("#th-dark").classList.toggle("on", t === "dark");
}
function setTheme(t) { document.documentElement.dataset.theme = t; store.set("hl-theme", t); paintTheme(); }

async function init() {
  $("#th-light").onclick = () => setTheme("light");
  $("#th-dark").onclick = () => setTheme("dark");
  paintTheme();
  CONFIG = await api("/api/config");
  if (!CONFIG.configured) { location.replace("setup.html"); return; }
  for (const s of CONFIG.sections) SEC[s.id] = s;
  const saved = store.get("hl-targets");
  TARGETS = new Set(saved !== null ? saved.split(",").filter(id => SEC[id] && SEC[id].enabled) : enabledIds());
  const pill = $("#mode");
  pill.textContent = CONFIG.mode === "live" ? "Live" : "Practice";
  pill.className = "pill " + CONFIG.mode;
  if (CONFIG.mode === "dry") {
    const b = $("#banner");
    b.hidden = false;
    b.textContent = "Practice mode (dry run): commands are logged on the server and nothing is sent to the lights. "
      + "Status is still read from the controllers (read-only).";
  }
  buildQuick();
  buildViz();
  const main = $("#sections");
  for (const sec of CONFIG.sections) main.appendChild(buildCard(sec));
  $("#refresh").onclick = () => refresh();
  if (typeof Themes !== "undefined") Themes.init();
  buildSettings();
  for (const b of document.querySelectorAll("[data-tab]")) b.onclick = () => setTab(b.dataset.tab);
  setTab(TABS.includes(store.get("hl-tab")) ? store.get("hl-tab") : "quick");
  if (typeof Schedules !== "undefined") Schedules.init();
  sync();
  await refresh();
  requestAnimationFrame(paintLoop);
  setInterval(() => { if (!document.hidden) refresh(); }, 15000);
}

init().catch(e => toast(e.message, true));
