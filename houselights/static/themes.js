"use strict";
// Themes tab: a list of themes (yours first, then the built-ins by group) and an editor.
// A theme is plain data: layers of "movements" (Chase, Twinkle, ...) with colors and settings,
// a shape (direction, mirror, whole-house span) or a sequence of other themes. Every preview
// is rendered by the server (the same code that drives the lights), shown two ways:
//  - Strip: the lights as they'd look right now, animated.
//  - Time strip: every moment stacked top to bottom (x = light, y = time), so a chase shows as
//    diagonal stripes, a flicker as speckle, a burst as a V.
// Unsaved edits are previewed and played as pattern "_draft" with params {theme: {...}}.
// Color tools, variations and "Surprise me" work in the browser; a photo never leaves it.
// Uses $, api, toast, CONFIG, STATUS, PREVIEW, SEC, patternById, labelOf, previewData,
// showInViz, setPreview, themesChanged, themePrefs, faceGradient, enabledIds, afterAction from app.js.
const Themes = (() => {
  const FPS = 12;
  let META = null;               // GET /api/themes: movements, builtin_params, directions, themes, prefs
  let cur = null;                // {id: saved id or null, builtin: built-in id or null, draft}
  let savedJson = "";            // the draft as last opened or saved: anything else is unsaved
  let data = null, t0 = 0, paused = false, pausedAt = 0, timer = null, seq = 0, ready = false;
  let toolBase = null;           // the palette before the warm/cool and brightness sliders moved
  let taps = [], cells = [], painting = false;
  const off = document.createElement("canvas");          // the time strip at 1 px per light x frame
  const clone = o => JSON.parse(JSON.stringify(o));
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

  // --- colors ----------------------------------------------------------------------------------
  const PALETTES = [
    ["Sunset", "#ff4e1f,#ff8a1c,#ffc850,#d0007a"], ["Ocean", "#003a8c,#0077b6,#00b4d8,#90e0ef"],
    ["Autumn", "#dc1e00,#ff7800,#ffbe1e,#aa3c00"], ["Marigold", "#ff8c00,#ffc800,#dc1400"],
    ["Ice", "#e8f4ff,#9fd8ff,#3fa9ff,#ffffff"], ["Neon", "#ff00ff,#00ffff,#39ff14,#ffff00"],
    ["Pastel", "#ff78aa,#ffe66e,#78ffaa,#be8cff,#78beff"], ["Candlelight", "#ff8a2a,#ffa04a,#ffb46b"],
    ["Warm whites", "#ff8a2a,#ffb46b,#ffdcb8"], ["Cool whites", "#ffeedd,#fff9fd,#e8f4ff"],
    ["Diwali", "#ffb000,#ff8c00,#ff4500,#d0007a"], ["Rangoli", "#e0007a,#ff7a00,#ffd000,#00b050,#0060ff,#8a2be2"],
    ["Holi", "#ff0096,#00dc3c,#ffdc00,#0078ff,#ff6e00,#9600ff"],
    ["Navratri", "#ff6400,#ffffff,#e60014,#1e3cff,#ffd200,#00be28,#9696af,#8c00dc,#00a08c"],
    ["Ganesh", "#ff8c00,#ffc800,#dc1400"], ["Onam", "#ffd200,#ff7800,#ffffff,#dc1400"],
    ["India", "#ff6a00,#ffffff,#00a000"], ["Christmas", "#ff0000,#00a000,#ffffff"],
    ["Retro bulbs", "#e60000,#00aa1e,#143cff,#ff6e00,#ffc800"], ["Hanukkah", "#0038b8,#ffffff,#9fd8ff"],
    ["Eid", "#00a86b,#ffd700,#ffffff"], ["Lunar New Year", "#e60000,#ffc800,#ff6a00"],
    ["Halloween", "#ff5a00,#7800c8,#28c800"], ["Thanksgiving", "#aa1400,#ff7800,#ffbe28,#c85000"],
    ["Valentine", "#ff4f9a,#ff0020,#ffffff"], ["St. Patrick's", "#00aa28,#00c85a,#ffc83c"],
    ["Easter", "#ff78aa,#ffe66e,#78ffaa,#be8cff,#78beff"], ["Fourth of July", "#dc0014,#ffffff,#1428c8"],
    ["Pride", "#e40303,#ff8c00,#ffed00,#008026,#004dff,#750787"], ["Peacock", "#0032c8,#00aa96,#6400b4,#00783c"],
    ["Forest", "#0b6b2e,#00b050,#7cfc00,#5a8c00"], ["Tropical", "#ff6f61,#ffc300,#00c9a7,#00a3ff"],
    ["Berry", "#8e2a8e,#dc143c,#ff3d7f,#4b00c8"], ["Citrus", "#ffe600,#ff8c00,#7cfc00"],
    ["Aurora", "#00ff9c,#00c8ff,#8a2be2,#ff00aa"], ["Fire", "#aa1400,#ff5000,#ffa014,#ffdc78"],
    ["Lavender", "#c49bff,#8a2be2,#ff7ab6"], ["Mint & rose", "#5cffb0,#ff7ab6,#ffffff"],
    ["Gold & silver", "#ffbe28,#c8d2e6,#ffdc78"], ["Royal", "#2a3fff,#ffc800,#8a2be2"],
    ["Candy", "#ff1493,#00e5ff,#ffe600,#ffffff"], ["Desert", "#e0662a,#ffb46b,#c8503c,#ffd36b"],
    ["Snow", "#ffffff,#c8e6ff"],
  ];
  const rgb = h => h ? [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)] : [26, 28, 32];
  const hex = c => "#" + c.map(v => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0")).join("");
  function toHsv([r, g, b]) {
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = 0;
    if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [((h / 6) + 1) % 1, mx ? d / mx : 0, mx];
  }
  function fromHsv(h, s, v) {
    h = ((h % 1) + 1) % 1;
    const i = Math.floor(h * 6), f = h * 6 - i, p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
    return hex([[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6].map(x => x * 255));
  }
  // LEDs show very dark colors as off: lift them (hue kept) unless switched off.
  const lift = h => { if (!$("#th-lift").checked) return h; const [H, S, V] = toHsv(rgb(h)); return V < 0.3 ? fromHsv(H, S, 0.3 + V / 3) : h; };
  function harmony(base, kind) {
    const [h, s, v] = toHsv(rgb(base)), S = Math.max(s, 0.5), V = Math.max(v, 0.6);
    const hs = {complementary: [0, 0.5], analogous: [-1 / 12, 0, 1 / 12], triadic: [0, 1 / 3, 2 / 3], split: [0, 5 / 12, 7 / 12]}[kind];
    if (hs) return hs.map(d => fromHsv(h + d, S, V));
    return [fromHsv(h, S, 1), fromHsv(h, S * 0.75, 0.75), fromHsv(h, S * 0.5, 0.55), fromHsv(h, 0.25, 1)];   // shades
  }
  async function photoColors(file, k) {
    const url = URL.createObjectURL(file);
    try {
      const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("Can't read that picture")); i.src = url; });
      const W = 64, H = Math.max(1, Math.round(64 * img.height / img.width)), c = document.createElement("canvas");
      c.width = W; c.height = H;
      const g = c.getContext("2d");
      g.drawImage(img, 0, 0, W, H);
      const px = g.getImageData(0, 0, W, H).data, pts = [];
      for (let i = 0; i < px.length; i += 4) if (px[i + 3] > 128 && Math.max(px[i], px[i + 1], px[i + 2]) > 30) pts.push([px[i], px[i + 1], px[i + 2]]);
      if (pts.length < k) throw new Error("The picture is too dark");
      const d2 = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
      const cs = [pts[Math.floor(pts.length / 2)]];                    // start far apart, then k-means
      while (cs.length < k) cs.push(pts.reduce((best, p) => Math.min(...cs.map(c => d2(c, p))) > Math.min(...cs.map(c => d2(c, best))) ? p : best, pts[0]));
      let count = [];
      for (let it = 0; it < 10; it++) {
        const sum = cs.map(() => [0, 0, 0]); count = cs.map(() => 0);
        for (const p of pts) {
          let bi = 0, bd = Infinity;
          cs.forEach((c, j) => { const d = d2(c, p); if (d < bd) { bd = d; bi = j; } });
          sum[bi][0] += p[0]; sum[bi][1] += p[1]; sum[bi][2] += p[2]; count[bi]++;
        }
        cs.forEach((c, j) => { if (count[j]) cs[j] = sum[j].map(x => x / count[j]); });
      }
      return cs.map((c, j) => [c, count[j]]).sort((a, b) => b[1] - a[1]).map(([c]) => {
        const [h, s, v] = toHsv(c);
        return fromHsv(h, Math.min(1, s * 1.25), Math.max(v, 0.45));     // a bit stronger: LEDs wash out
      });
    } finally { URL.revokeObjectURL(url); }
  }

  // --- the theme being edited -------------------------------------------------------------------
  const mvById = id => META.movements.find(m => m.id === id);
  const specOf = mv => mv.startsWith("builtin:") ? META.builtin_params[mv.slice(8)] || {} : (mvById(mv) || {params: {}}).params;
  const mvLabel = mv => mv.startsWith("builtin:") ? "Built-in: " + labelOf(mv.slice(8)) : (mvById(mv) || {label: mv}).label;
  const defaults = spec => Object.fromEntries(Object.entries(spec).map(([k, s]) => [k, s.default]));
  const layerAnimated = ly => ly.movement.startsWith("builtin:") ? patternById(ly.movement.slice(8)).animated : (mvById(ly.movement) || {}).kind !== "still";
  const draftAnimated = d => !!d.sequence || d.layers.some(layerAnimated);
  const dirty = () => JSON.stringify(cur.draft) !== savedJson;
  const secOf = () => SEC[$("#th-run").value];

  function toDraft(th) {
    const d = {name: th.name, group: th.group || "My themes", layers: clone(th.layers || []), direction: th.direction || "ltr",
               mirror: !!th.mirror, span: th.span || "run"};
    if (th.sequence && th.sequence.length) { d.sequence = clone(th.sequence); d.fade = th.fade; }
    return d;
  }
  function fromBuiltin(id) {
    const p = patternById(id);
    return {name: p.label, group: p.group, layers: [{movement: "builtin:" + id, params: defaults(META.builtin_params[id] || {}), blend: "over"}],
            direction: "ltr", mirror: false, span: "run"};
  }
  function blank() {
    const m = mvById("chase");
    return {name: "My theme", group: "My themes", layers: [{movement: "chase", params: defaults(m.params), blend: "over"}],
            direction: "ltr", mirror: false, span: "run"};
  }
  // What the server is sent: a saved theme by id, an untouched built-in by id, else the draft.
  function playable() {
    const d = cur.draft;
    if (cur.id && !dirty()) return {pattern: cur.id, params: {}};
    const l0 = d.layers[0];
    if (cur.builtin && !d.sequence && d.layers.length === 1 && l0.movement === "builtin:" + cur.builtin
        && d.direction === "ltr" && !d.mirror && d.span === "run") return {pattern: cur.builtin, params: l0.params};
    return {pattern: "_draft", params: {theme: d}};
  }

  function open(item) {
    if (cur && dirty() && !confirm("Discard the unsaved changes to this theme?")) return false;
    if (item.custom) {
      const th = META.themes.find(t => t.id === item.id);
      cur = {id: th.id, builtin: null, draft: toDraft(th)};
    } else if (item.builtin) cur = {id: null, builtin: item.builtin, draft: fromBuiltin(item.builtin)};
    else cur = {id: null, builtin: null, draft: item.draft || blank()};
    savedJson = item.draft ? "" : JSON.stringify(cur.draft);
    $("#th-vars").hidden = true;
    renderEditor(); renderList(); load();
    return true;
  }

  // Something in the draft changed: preview again, mark unsaved.
  function changed(keepTone) {
    if (!keepTone && toolBase) { toolBase = null; $("#th-warm").value = 0; $("#th-bright").value = 0; }
    renderState(); load(); sync();
  }

  // --- editor ----------------------------------------------------------------------------------
  function renderEditor() {
    const d = cur.draft;
    $("#th-name").value = d.name;
    $("#th-group").value = d.group;
    $("#th-dir").value = d.direction;
    $("#th-mirror").checked = d.mirror;
    $("#th-span").value = d.span;
    for (const b of document.querySelectorAll("#th-mode [data-mode]")) b.classList.toggle("on", (b.dataset.mode === "sequence") === !!d.sequence);
    $("#th-layers").hidden = !!d.sequence;
    $("#th-layer-add-row").hidden = !!d.sequence;
    $("#th-tools").hidden = !!d.sequence;
    $("#th-seq").hidden = !d.sequence;
    if (d.sequence) renderSeq(); else renderLayers();
    renderState();
  }

  function renderState() {
    const d = cur.draft, mine = !!cur.id;
    $("#th-kind").textContent = (mine ? "Your theme" : cur.builtin ? "Built-in (saving makes a copy)" : "New theme")
      + (dirty() ? " · unsaved changes" : "") + (draftAnimated(d) ? " · animated" : " · still");
    $("#th-save").disabled = !dirty() && mine;
    $("#th-save").textContent = mine || !cur.builtin ? "Save" : "Save as a copy";
    $("#th-delete").disabled = !mine;
    $("#th-add-layer").disabled = d.layers.length >= META.limits.layers;
    const sec = secOf(), tgt = $("#th-target").value, anim = draftAnimated(d);
    const where = tgt === "all" ? "the whole house" : SEC[tgt] ? SEC[tgt].name : "";
    $("#th-play").textContent = (anim ? "Play live on " : "Apply on ") + where;
    $("#th-stop").textContent = "Stop " + where;
    $("#th-nlab").textContent = `light ${sec ? sec.lights : ""}`;
    $("#th-t1").textContent = `${$("#th-len").value} s`;
    $("#th-describe").textContent = d.span === "house" ? "Whole house: this run shows its part of one long strip." : "";
  }

  function numInput(spec, name, value, onset) {
    const s = spec[name], lab = el("label", "th-num"), isInt = s.type === "int";
    const lo = s.min ?? 0, hi = s.max ?? 100, step = isInt ? 1 : Math.max(0.01, +((hi - lo) / 200).toPrecision(1));
    lab.append(el("span", "lbl", NICE[name] || name.replace(/_/g, " ")));
    const r = el("input"), n = el("input");
    r.type = "range"; n.type = "number";
    for (const x of [r, n]) { x.min = lo; x.max = hi; x.step = step; x.value = value; }
    r.oninput = () => { n.value = r.value; onset(isInt ? Math.round(+r.value) : +r.value); };
    n.onchange = () => { const v = clamp(+n.value || 0, lo, hi); n.value = r.value = v; onset(isInt ? Math.round(v) : v); };
    lab.append(r, n);
    return lab;
  }
  const NICE = {width: "Band width (0 = a segment)", speed: "Speed", density: "How many", level: "Base brightness", count: "How many",
    size: "Size", trail: "Trail", sway: "Sway", rate: "How often", spread: "Spread", life: "Lasts (s)", soft: "Soft edges",
    blink: "Flicker", hold: "Hold each (s)", bpm: "Beats per minute", age: "Candles (age)", seed: "Shuffle", style: "Style",
    bg: "Background", accents: "Accent colors", colors: "Colors", flash: "White flash", wavelength: "Wave length", color: "Color", beat: "Beat color",
    gap: "Lit every (lights)", both: "Both directions", bounce: "Back and forth"};

  function colorList(params, name, max, onchange) {
    const box = el("div", "th-colors"), get = () => params[name].split(",").filter(Boolean);
    const set = cs => { params[name] = cs.join(","); draw(); onchange(); };
    let dragFrom = -1;
    function draw() {
      box.innerHTML = "";
      box.append(el("span", "lbl", NICE[name] || name));
      get().forEach((c, i, cs) => {
        const chip = el("span", "th-chip");
        chip.draggable = true;
        const inp = el("input"); inp.type = "color"; inp.value = c; inp.title = "Change this color";
        inp.oninput = () => { const a = get(); a[i] = inp.value; params[name] = a.join(","); onchange(); };
        const mk = (t, title, fn, dis) => { const b = el("button", "th-mini", t); b.type = "button"; b.title = title; b.setAttribute("aria-label", title); b.disabled = dis; b.onclick = fn; return b; };
        chip.append(inp,
          mk("‹", "Move left", () => { const a = get(); [a[i - 1], a[i]] = [a[i], a[i - 1]]; set(a); }, i === 0),
          mk("›", "Move right", () => { const a = get(); [a[i + 1], a[i]] = [a[i], a[i + 1]]; set(a); }, i === cs.length - 1),
          mk("×", "Remove", () => { const a = get(); a.splice(i, 1); set(a); }, cs.length <= 1));
        chip.ondragstart = e => { dragFrom = i; e.dataTransfer.effectAllowed = "move"; };
        chip.ondragover = e => e.preventDefault();
        chip.ondrop = e => { e.preventDefault(); if (dragFrom < 0 || dragFrom === i) return; const a = get(), [m] = a.splice(dragFrom, 1); a.splice(i, 0, m); dragFrom = -1; set(a); };
        box.append(chip);
      });
      if (get().length < max) {
        const add = el("button", "small", "+ color"); add.type = "button";
        add.onclick = () => { const a = get(); set([...a, a[a.length - 1] || "#ffffff"]); };
        box.append(add);
      }
    }
    draw();
    return box;
  }

  function moveSelect(value, first) {
    const sel = el("select");
    sel.setAttribute("aria-label", "Movement");
    const groups = [["Still", "still"], ["Moving", "moving"], ["On top of another layer", "layer"]];
    for (const [lab, kind] of groups) {
      const og = el("optgroup"); og.label = lab;
      for (const m of META.movements) if (m.kind === kind && (m.id !== "painted" || value === "painted")) og.append(new Option(m.label, m.id));
      sel.append(og);
    }
    const og = el("optgroup"); og.label = "A built-in theme as it is";
    for (const p of CONFIG.patterns) if (!p.custom) og.append(new Option(p.label, "builtin:" + p.id));
    sel.append(og);
    sel.value = value;
    return sel;
  }

  function renderLayers() {
    const box = $("#th-layers"), d = cur.draft;
    box.innerHTML = "";
    d.layers.forEach((ly, k) => {
      const card = el("div", "th-card th-layer"), head = el("div", "th-card-head");
      head.append(el("b", "", k === 0 ? "Movement" : `Layer ${k + 1}`));
      const sel = moveSelect(ly.movement, k === 0);
      sel.onchange = () => { switchMovement(ly, sel.value); renderLayers(); changed(); };
      head.append(sel);
      if (k > 0) {
        const bl = el("select");
        bl.setAttribute("aria-label", "How it combines");
        for (const [v, t] of [["add", "adds light"], ["over", "covers (black = see-through)"], ["max", "brightest wins"]]) bl.append(new Option(t, v));
        bl.value = ly.blend;
        bl.onchange = () => { ly.blend = bl.value; changed(); };
        const rm = el("button", "small", "Remove layer");
        rm.onclick = () => { d.layers.splice(k, 1); renderLayers(); changed(); };
        head.append(bl, rm);
      }
      card.append(head);
      const m = mvById(ly.movement);
      card.append(el("p", "note", m ? m.describe : patternById(ly.movement.slice(8)).describe || "Built-in theme with its own settings."));
      const spec = specOf(ly.movement), ps = el("div", "th-params");
      for (const [name, s] of Object.entries(spec)) {
        const set = v => { ly.params[name] = v; changed(); };
        if (s.type === "colors" && name === "cells") {
          const w = el("div", "th-colors");
          w.append(el("span", "lbl", `Painted: ${ly.params.cells.split(",").length} segments`));
          const b = el("button", "small", "Open the paint strip"); b.onclick = openPaint;
          w.append(b); ps.append(w);
        } else if (s.type === "colors") ps.append(colorList(ly.params, name, META.limits.colors, () => changed()));
        else if (s.type === "color") {
          const lab = el("label", "th-num"), i = el("input");
          i.type = "color"; i.value = ly.params[name]; i.oninput = () => set(i.value);
          lab.append(el("span", "lbl", NICE[name] || name), i); ps.append(lab);
        } else if (s.type === "bool") {
          const lab = el("label", "th-num"), i = el("input");
          i.type = "checkbox"; i.checked = !!ly.params[name]; i.onchange = () => set(i.checked);
          lab.append(i, el("span", "lbl", NICE[name] || name)); ps.append(lab);
        } else if (s.type === "choice") {
          const lab = el("label", "th-num"), i = el("select");
          for (const o of s.options) i.append(new Option(o, o));
          i.value = ly.params[name]; i.onchange = () => set(i.value);
          lab.append(el("span", "lbl", NICE[name] || name), i); ps.append(lab);
        } else ps.append(numInput(spec, name, ly.params[name], set));
      }
      card.append(ps);
      box.append(card);
    });
  }

  // A new movement keeps the colors (and speed / width) where it can.
  function switchMovement(ly, mv) {
    const old = ly.params, spec = specOf(mv), p = defaults(spec);
    const cols = old.colors || old.cells || old.color || (ly.movement.startsWith("builtin:") ? patternById(ly.movement.slice(8)).face : "");
    if (cols && "colors" in p) p.colors = cols.split(",").slice(0, META.limits.colors).join(",");
    else if (cols && "color" in p) p.color = cols.split(",")[0];
    for (const k of ["speed", "width", "bpm"]) if (k in p && k in old && typeof old[k] === "number") p[k] = clamp(old[k], spec[k].min, spec[k].max);
    ly.movement = mv; ly.params = p;
  }

  // the first layer's color list, for the color tools
  function palette() {
    const ly = cur.draft.layers[0], p = ly && ly.params;
    if (!p) return null;
    if ("colors" in p) return {get: () => p.colors.split(","), set: cs => { p.colors = cs.slice(0, META.limits.colors).join(","); }};
    if ("color" in p) return {get: () => [p.color], set: cs => { p.color = cs[0]; }};
    return null;
  }
  function setPalette(cs, liftIt = true) {
    if (cur.draft.sequence) return toast("Colors apply to layered themes", true);
    const pal = palette();
    if (!pal) return toast("This movement has no color list", true);
    pal.set(liftIt ? cs.map(lift) : cs);
    renderLayers(); changed();
  }
  function tone() {
    const pal = palette();
    if (!pal || cur.draft.sequence) return;
    if (!toolBase) toolBase = pal.get();
    const w = $("#th-warm").value / 100, b = $("#th-bright").value / 100;
    pal.set(toolBase.map(h => {
      const [r, g, bb] = rgb(h), shifted = [r + w * 60, g + w * 12, bb - w * 60];
      const [H, S, V] = toHsv(shifted.map(x => clamp(x, 0, 255)));
      return lift(fromHsv(H, S, clamp(V * (1 + b), 0.02, 1)));
    }));
    renderLayers(); changed(true);
  }

  // --- sequence --------------------------------------------------------------------------------
  function themeOptions(sel, value) {
    const groups = {};
    for (const p of CONFIG.patterns) {
      if (p.custom && (META.themes.find(t => t.id === p.id) || {}).sequence) continue;   // no sequence in a sequence
      (groups[p.group] = groups[p.group] || []).push(p);
    }
    for (const g of CONFIG.categories.filter(c => groups[c])) {
      const og = el("optgroup"); og.label = g;
      for (const p of groups[g]) og.append(new Option(p.label, p.id));
      sel.append(og);
    }
    sel.value = value;
  }
  function renderSeq() {
    const d = cur.draft, box = $("#th-steps");
    box.innerHTML = "";
    $("#th-fade").value = d.fade ?? 2;
    d.sequence.forEach((st, k) => {
      const row = el("div", "row th-step");
      row.append(el("span", "lbl", `${k + 1}.`));
      const sel = el("select"); themeOptions(sel, st.theme);
      sel.onchange = () => { st.theme = sel.value; changed(); };
      const secs = el("input"); secs.type = "number"; secs.min = 1; secs.max = 3600; secs.value = st.seconds;
      secs.onchange = () => { st.seconds = clamp(+secs.value || 10, 1, 3600); secs.value = st.seconds; changed(); };
      const rm = el("button", "small", "Remove"); rm.disabled = d.sequence.length <= 1;
      rm.onclick = () => { d.sequence.splice(k, 1); renderSeq(); changed(); };
      row.append(sel, secs, el("span", "lbl", "s"), rm);
      box.append(row);
    });
    $("#th-add-step").disabled = d.sequence.length >= META.limits.steps;
  }
  function setMode(mode) {
    const d = cur.draft;
    if ((mode === "sequence") === !!d.sequence) return;
    if (mode === "sequence") {
      cur.layersAside = d.layers;
      d.sequence = cur.seqAside || [{theme: "diya_glow", seconds: 10}, {theme: "rangoli_chase", seconds: 10}];
      d.fade = d.fade ?? 2; d.layers = [];
    } else {
      cur.seqAside = d.sequence;
      delete d.sequence; delete d.fade;
      d.layers = cur.layersAside && cur.layersAside.length ? cur.layersAside : blank().layers;
    }
    renderEditor(); changed();
  }

  // --- variations and surprise ----------------------------------------------------------------
  function mutate(d) {
    const v = clone(d), ly = v.layers[0], spec = specOf(ly.movement), notes = [];
    const keys = ["speed", "width", "density", "count", "size", "hold", "bpm", "rate", "soft", "trail", "spread", "blink"]
      .filter(k => k in ly.params && spec[k] && typeof ly.params[k] === "number").sort(() => Math.random() - 0.5).slice(0, 2);
    for (const k of keys) {
      const s = spec[k], old = ly.params[k];
      let x = (old || (s.max - s.min) / 10) * (0.45 + Math.random() * 1.5);
      x = clamp(s.type === "int" ? Math.round(x) : +x.toFixed(2), s.min, s.max);
      if (x !== old) { ly.params[k] = x; notes.push(`${(NICE[k] || k).toLowerCase()} ${x > old ? "↑" : "↓"}`); }
    }
    if (ly.params.colors && ly.params.colors.includes(",") && Math.random() < 0.6) {
      const cs = ly.params.colors.split(",");
      ly.params.colors = (Math.random() < 0.5 ? cs.sort(() => Math.random() - 0.5) : [...cs.slice(1), cs[0]]).join(",");
      notes.push("color order");
    }
    if (Math.random() < 0.25) { v.direction = pick(Object.keys(META.directions).filter(x => x !== v.direction)); notes.push(META.directions[v.direction].toLowerCase()); }
    else if (Math.random() < 0.15) { v.mirror = !v.mirror; notes.push(v.mirror ? "mirrored" : "not mirrored"); }
    return {draft: v, note: notes.join(", ") || "a small change"};
  }
  async function variations() {
    if (cur.draft.sequence) return toast("Variations work on layered themes", true);
    const box = $("#th-vars"), sid = $("#th-run").value, base = cur.draft;
    box.hidden = false;
    box.innerHTML = '<p class="muted">Making variations…</p>';
    const vs = Array.from({length: 6}, () => mutate(base));
    const res = await Promise.all(vs.map(v => previewData(sid, "_draft", {theme: v.draft}, 4, 10).catch(e => ({error: e.message}))));
    if (cur.draft !== base) return;                    // something else was opened meanwhile
    box.innerHTML = "";
    vs.forEach((v, k) => {
      const r = res[k], b = el("button", "th-var");
      b.type = "button"; b.title = "Use this one";
      const c = el("canvas"); c.width = 200; c.height = 60;
      if (!r.error) drawThumb(c, r.frames || [r.lights]);
      b.append(c, el("span", "th-var-note", r.error || v.note));
      b.onclick = () => { cur.draft = v.draft; renderEditor(); changed(); variations(); };
      box.append(b);
    });
    const more = el("button", "small", "More variations"); more.onclick = variations;
    const close = el("button", "small", "Close"); close.onclick = () => { box.hidden = true; };
    const row = el("div", "row"); row.append(more, close, el("span", "muted", "Tap one to use it; you get six more around it."));
    box.append(row);
  }
  function drawThumb(c, frames) {
    const n = frames[0].length, F = frames.length, g = c.getContext("2d"), img = g.createImageData(n, F);
    frames.forEach((row, y) => row.forEach((h, x) => { const [r, gg, b] = rgb(h), k = (y * n + x) * 4; img.data.set([r, gg, b, 255], k); }));
    const o = document.createElement("canvas"); o.width = n; o.height = F;
    o.getContext("2d").putImageData(img, 0, 0);
    g.imageSmoothingEnabled = false;
    g.drawImage(o, 0, 0, c.width, c.height);
  }
  function surprise() {
    if (cur.draft.sequence) setMode("layers");
    const d = cur.draft, ly = d.layers[0], keepC = $("#th-lock-col").checked, keepM = $("#th-lock-mv").checked;
    const pal = palette(), oldCols = pal ? pal.get() : null;
    if (!keepM) {
      const m = pick(META.movements.filter(x => x.kind !== "layer" && x.id !== "painted"));
      ly.movement = m.id; ly.params = defaults(m.params);
      d.direction = Math.random() < 0.7 ? "ltr" : pick(Object.keys(META.directions));
      d.mirror = Math.random() < 0.2;
      d.layers = [ly];
      if (Math.random() < 0.3) d.layers.push({movement: pick(["sparkle", "comet"]), params: defaults(mvById(Math.random() < 0.5 ? "sparkle" : "comet").params), blend: "add"});
      d.layers.slice(1).forEach(l => { l.params = defaults(mvById(l.movement).params); });
    }
    const np = palette();
    if (np) {
      const cols = keepC && oldCols ? oldCols : Math.random() < 0.7 ? pick(PALETTES)[1].split(",")
        : harmony(fromHsv(Math.random(), 0.9, 1), pick(["complementary", "analogous", "triadic", "split"]));
      np.set(cols.map(lift));
    }
    $("#th-vars").hidden = true;
    renderEditor(); changed();
  }

  // --- paint by hand -------------------------------------------------------------------------
  function openPaint() {
    const box = $("#th-paint"), sec = secOf(), n = Math.ceil(sec.lights / 5), ly = cur.draft.layers[0];
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false;
    if (ly && ly.movement === "painted") cells = ly.params.cells.split(",");
    else if (data) cells = Array.from({length: n}, (_, s) => data.frames[0][Math.min(sec.lights - 1, s * 5 + 2)] || "#000000");
    cells = Array.from({length: n}, (_, s) => cells[s % Math.max(1, cells.length)] || "#ff8a1c");
    const br = $("#th-brushes");
    br.innerHTML = "";
    for (const c of new Set([...(palette() ? palette().get() : []), "#ffffff", "#000000"])) {
      const b = el("button", "th-brush"); b.type = "button"; b.style.background = c; b.title = c; b.setAttribute("aria-label", "Brush " + c);
      b.onclick = () => { $("#th-brush").value = c; };
      br.append(b);
    }
    drawCells();
    box.scrollIntoView({behavior: "smooth", block: "nearest"});
  }
  function drawCells() {
    const box = $("#th-cells");
    box.innerHTML = "";
    cells.forEach((c, i) => {
      const d = el("span", "th-cell"); d.style.background = c; d.title = `Segment ${i + 1}`;
      d.onpointerdown = e => { e.preventDefault(); painting = true; paintAt(i, d); };
      d.onpointerenter = () => { if (painting) paintAt(i, d); };
      box.append(d);
    });
  }
  function paintAt(i, d) { cells[i] = $("#th-brush").value; d.style.background = cells[i]; }
  function useCells() {
    const d = cur.draft;
    if (d.sequence) { delete d.sequence; delete d.fade; }
    d.layers = [{movement: "painted", params: {cells: cells.join(","), width: 5}, blend: "over"}];
    d.direction = "ltr"; d.mirror = false;
    renderEditor(); changed();
  }

  // --- list ----------------------------------------------------------------------------------
  function renderList() {
    const q = $("#th-search").value.trim().toLowerCase(), box = $("#th-items"), {favorites, hidden_groups} = themePrefs();
    box.innerHTML = "";
    const groups = {};
    for (const p of CONFIG.patterns) (groups[p.custom ? "My themes" : p.group] = groups[p.custom ? "My themes" : p.group] || []).push(p);
    for (const g of CONFIG.categories) {
      const items = (groups[g] || []).filter(p => !q || p.label.toLowerCase().includes(q) || g.toLowerCase().includes(q)
        || (p.describe || "").toLowerCase().includes(q));
      if (!items.length && !(g === "My themes" && !q)) continue;
      const h = el("div", "th-group", g + (hidden_groups.includes(g) ? " (hidden in Quick Settings)" : ""));
      box.append(h);
      if (!items.length) box.append(el("p", "note th-empty", "None yet: open any theme, change it and save, or press New theme."));
      for (const p of items) {
        const sel = cur && (p.id === cur.id || (!cur.id && p.id === cur.builtin));
        const it = el("div", "th-item" + (sel ? " on" : ""));
        it.setAttribute("role", "option"); it.setAttribute("aria-selected", String(!!sel)); it.tabIndex = 0;
        const face = el("span", "th-face"); face.style.background = faceGradient(p.face);
        const lab = el("span", "th-label", p.label);
        const fav = favorites.includes(p.id), star = el("button", "th-star" + (fav ? " on" : ""), fav ? "★" : "☆");
        star.type = "button"; star.title = fav ? "Remove from favorites" : "Favorite: first in Quick Settings";
        star.setAttribute("aria-pressed", String(fav)); star.setAttribute("aria-label", "Favorite " + p.label);
        star.onclick = e => { e.stopPropagation(); prefs({favorites: fav ? favorites.filter(x => x !== p.id) : [...favorites, p.id]}); };
        it.append(face, lab, el("span", "th-anim", p.animated ? "" : "still"), star);
        const go = () => open(p.custom ? {custom: true, id: p.id} : {builtin: p.id});
        it.onclick = go;
        it.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
        box.append(it);
      }
    }
    // built-in groups shown in Quick Settings
    const gb = $("#th-groups");
    gb.innerHTML = "";
    for (const g of CONFIG.categories.filter(c => c !== "My themes")) {
      const lab = el("label", "th-num"), i = el("input");
      i.type = "checkbox"; i.checked = !hidden_groups.includes(g);
      i.onchange = () => prefs({hidden_groups: i.checked ? hidden_groups.filter(x => x !== g) : [...hidden_groups, g]});
      lab.append(i, el("span", "", g)); gb.append(lab);
    }
    const gl = $("#th-group-list");
    gl.innerHTML = "";
    for (const g of CONFIG.categories) gl.append(new Option(g, g));
  }
  async function prefs(body) {
    try { got(await api("/api/themes/prefs", body)); } catch (e) { toast(e.message, true); }
  }
  // The server's answer after a change: new lists everywhere.
  function got(r) {
    META = {...META, ...r};
    themesChanged(r);
    renderList();
  }

  // --- save, delete, import / export -----------------------------------------------------------
  async function save(asNew) {
    const d = clone(cur.draft);
    d.name = $("#th-name").value.trim() || d.name;
    if (!asNew && !cur.id) {
      if (cur.builtin && d.name === patternById(cur.builtin).label) d.name = (d.name + " (copy)").slice(0, 40);
      asNew = true;
    } else if (asNew && cur.id && d.name === JSON.parse(savedJson).name) d.name = (d.name + " (copy)").slice(0, 40);
    if (!asNew) d.id = cur.id;
    try {
      const r = await api("/api/themes/save", {theme: d, as_new: asNew});
      got(r);
      cur = {id: r.theme.id, builtin: null, draft: toDraft(r.theme)};
      savedJson = JSON.stringify(cur.draft);
      renderEditor(); renderList(); load();
      toast(`Saved "${r.theme.name}". It's in My themes and in Quick Settings.`);
    } catch (e) { toast(e.message, true); }
  }
  async function del() {
    if (!cur.id || !confirm(`Delete "${cur.draft.name}"? This can't be undone.`)) return;
    try {
      const r = await api("/api/themes/delete", {id: cur.id});
      savedJson = JSON.stringify(cur.draft);           // no "discard changes?" question
      got(r);
      const used = [...r.used_by_schedules.map(n => `schedule "${n}"`), ...r.used_by_sequences.map(n => `sequence "${n}"`)];
      toast(`Deleted "${cur.draft.name}".` + (used.length ? ` Pick another theme for: ${used.join(", ")}.` : ""), used.length > 0);
      cur = null;
      open({builtin: "diya_glow"});
    } catch (e) { toast(e.message, true); }
  }
  async function exportThemes() {
    try {
      const r = await api("/api/themes/export");
      if (!r.themes.length) return toast("No themes of your own to export yet", true);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(r, null, 1)], {type: "application/json"}));
      a.download = "houselights-themes.json";
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) { toast(e.message, true); }
  }
  async function importThemes(file) {
    try {
      let raw;
      try { raw = JSON.parse(await file.text()); } catch (e) { throw new Error("That file isn't a themes .json file"); }
      const r = await api("/api/themes/import", raw);
      got(r);
      const errs = Object.entries(r.errors);
      toast(`Imported ${r.added.length} theme${r.added.length === 1 ? "" : "s"}` + (errs.length ? `; skipped ${errs.map(([n, e]) => `${n} (${e})`).join(", ")}` : ""), !r.added.length);
    } catch (e) { toast(e.message, true); }
  }

  // --- preview -------------------------------------------------------------------------------
  const now = () => (paused ? pausedAt : performance.now()) / 1000;
  const frameIndex = () => data ? Math.floor((now() - t0) * data.fps) % data.frames.length : 0;
  function load() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const my = ++seq, {pattern, params} = playable();
      $("#th-msg").textContent = "Updating…";
      try {
        const d = await previewData($("#th-run").value, pattern, params, Number($("#th-len").value), FPS);
        if (my !== seq) return;
        data = {...d, frames: d.frames || [d.lights], fps: d.frames ? d.fps : FPS};
        t0 = now();
        drawTimeImage();
        $("#th-msg").textContent = "";
      } catch (e) { if (my === seq) $("#th-msg").textContent = e.message; }
    }, 250);
  }
  function drawTimeImage() {
    const n = data.frames[0].length, F = data.frames.length;
    off.width = n; off.height = F;
    const g = off.getContext("2d"), img = g.createImageData(n, F);
    data.frames.forEach((row, y) => row.forEach((h, x) => {
      const [r, gg, b] = rgb(h), k = (y * n + x) * 4;
      img.data[k] = r; img.data[k + 1] = gg; img.data[k + 2] = b; img.data[k + 3] = 255;
    }));
    g.putImageData(img, 0, 0);
  }
  function fit(c) {
    const dpr = window.devicePixelRatio || 1, w = Math.round(c.clientWidth * dpr), h = Math.round(c.clientHeight * dpr);
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    return [w, h, dpr];
  }
  function drawStrip(row) {
    const c = $("#th-strip"), [w, h, dpr] = fit(c), g = c.getContext("2d");
    g.clearRect(0, 0, w, h);
    const n = row.length, step = w / n, r = Math.max(1.5 * dpr, Math.min(step * 0.36, 7 * dpr));
    for (let i = 0; i < n; i++) {
      g.shadowColor = row[i] || "transparent"; g.shadowBlur = row[i] ? 10 * dpr : 0;
      g.fillStyle = row[i] || "#41454c";
      g.beginPath(); g.arc(step * (i + 0.5), h / 2, r, 0, Math.PI * 2); g.fill();
    }
    g.shadowBlur = 0;
  }
  function drawTime(k) {
    const c = $("#th-time"), [w, h, dpr] = fit(c), g = c.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.clearRect(0, 0, w, h);
    g.drawImage(off, 0, 0, w, h);
    const y = (k + 0.5) / data.frames.length * h;
    g.fillStyle = "rgba(255,255,255,.85)"; g.fillRect(0, y - dpr, w, 2 * dpr);
  }
  function loop() {
    if (data && !document.hidden && !$("#tab-themes").hidden) {
      const k = frameIndex();
      drawStrip(data.frames[k]);
      drawTime(k);
      $("#th-clock").textContent = `${(k / data.fps).toFixed(1)} s`;
    }
    requestAnimationFrame(loop);
  }

  // --- live ------------------------------------------------------------------------------------
  const targets = () => $("#th-target").value === "all" ? enabledIds() : [$("#th-target").value];
  async function play() {
    const {pattern, params} = playable(), ids = targets(), anim = draftAnimated(cur.draft);
    if (PREVIEW) setPreview(null);
    try {
      let r;
      if (ids.length > 1) r = anim ? await api("/api/play-all", {pattern, params, level: 100, sections: ids})
                                  : await api("/api/apply-all", {pattern, params, sections: ids});
      else r = anim ? await api(`/api/sections/${ids[0]}/play`, {pattern, params, level: 100})
                    : await api(`/api/sections/${ids[0]}/pattern`, {pattern, params});
      const skipped = Object.keys(r.skipped || {});
      toast((r.mode === "dry" ? "Dry run: logged, nothing sent" : `Sent "${cur.draft.name}"`)
        + (skipped.length ? ` · skipped ${skipped.map(s => SEC[s] ? SEC[s].name : s).join(", ")}` : ""), skipped.length > 0);
    } catch (e) { toast(e.message, true); }
    afterAction();
  }
  async function stop() {
    const ids = targets().filter(id => STATUS[id] && STATUS[id].stream);
    try { await Promise.all(ids.map(id => api(`/api/sections/${id}/stop`, {}))); toast("Stopped. The lights stay on."); }
    catch (e) { toast(e.message, true); }
    afterAction();
  }
  async function showHouse() {
    if (!data) return;
    const {pattern, params} = playable(), sid = $("#th-run").value;
    const ids = cur.draft.span === "house" ? enabledIds() : [sid], runs = {};
    try {
      await Promise.all(ids.map(async id => { runs[id] = id === sid ? data : await previewData(id, pattern, params, Number($("#th-len").value), FPS); }));
      showInViz(runs, cur.draft.name);
    } catch (e) { toast(e.message, true); }
  }

  function sync() {
    if (!ready || !cur) return;
    const {pattern, params} = playable(), key = JSON.stringify(params || {});
    const ids = targets(), streams = ids.map(id => STATUS[id] && STATUS[id].stream);
    const on = ids.length && ids.every(id => {
      const st = STATUS[id], s = st && st.stream, a = st && st.assumed;
      return s ? s.pattern === pattern && JSON.stringify(s.params || {}) === key
        : !draftAnimated(cur.draft) && a && a.pattern === pattern && JSON.stringify(a.params || {}) === key;
    });
    $("#th-play").classList.toggle("on", !!on);
    $("#th-stop").disabled = !streams.some(Boolean);
    $("#th-house").classList.toggle("on", !!PREVIEW && PREVIEW.source === "scene");
  }

  // --- wiring ----------------------------------------------------------------------------------
  function wire() {
    const run = $("#th-run"), tgt = $("#th-target");
    tgt.append(new Option("Whole house", "all"));
    for (const s of CONFIG.sections) if (s.enabled) { run.append(new Option(`${s.name} (${s.lights})`, s.id)); tgt.append(new Option(s.name, s.id)); }
    for (const [v, t] of Object.entries(META.directions)) $("#th-dir").append(new Option(t, v));
    $("#th-pal").append(new Option("Pick a palette…", ""));
    for (const [n, cs] of PALETTES) $("#th-pal").append(new Option(n, cs));
    run.onchange = () => { renderState(); load(); sync(); if (!$("#th-paint").hidden) { $("#th-paint").hidden = true; openPaint(); } };
    tgt.onchange = () => { renderState(); sync(); };
    $("#th-len").onchange = () => { renderState(); load(); };
    $("#th-search").oninput = renderList;
    $("#th-name").oninput = () => { cur.draft.name = $("#th-name").value; renderState(); };
    $("#th-group").oninput = () => { cur.draft.group = $("#th-group").value; renderState(); };
    $("#th-dir").onchange = () => { cur.draft.direction = $("#th-dir").value; changed(); };
    $("#th-mirror").onchange = () => { cur.draft.mirror = $("#th-mirror").checked; changed(); };
    $("#th-span").onchange = () => { cur.draft.span = $("#th-span").value; changed(); };
    for (const b of document.querySelectorAll("#th-mode [data-mode]")) b.onclick = () => setMode(b.dataset.mode);
    $("#th-add-layer").onclick = () => {
      const m = mvById("sparkle");
      cur.draft.layers.push({movement: "sparkle", params: defaults(m.params), blend: "add"});
      renderLayers(); changed();
    };
    $("#th-add-step").onclick = () => { cur.draft.sequence.push({theme: "rangoli_chase", seconds: 10}); renderSeq(); changed(); };
    $("#th-fade").onchange = () => { cur.draft.fade = clamp(+$("#th-fade").value || 0, 0, 30); changed(); };
    $("#th-tap").onclick = () => {
      const t = performance.now();
      taps = [...taps.filter(x => t - x < 2500), t];
      if (taps.length < 2) { $("#th-tap-msg").textContent = "Keep tapping…"; return; }
      const bpm = clamp(Math.round(60000 * (taps.length - 1) / (t - taps[0])), 30, 240);
      let used = false;
      for (const ly of cur.draft.layers) {
        if ("bpm" in ly.params) { ly.params.bpm = bpm; used = true; }
        else if ("hold" in ly.params) { ly.params.hold = +(240 / bpm).toFixed(2); used = true; }      // one color per bar
      }
      $("#th-tap-msg").textContent = `${bpm} BPM` + (used ? "" : " (use Beat, Heartbeat or Steps to follow it)");
      if (used) { renderLayers(); changed(); }
    };
    $("#th-pal").onchange = () => { const v = $("#th-pal").value; if (v) setPalette(v.split(","), false); $("#th-pal").value = ""; };
    $("#th-h-go").onclick = () => setPalette(harmony($("#th-h-col").value, $("#th-h-kind").value));
    $("#th-photo").onchange = async e => {
      const f = e.target.files[0]; e.target.value = "";
      if (!f) return;
      try { setPalette(await photoColors(f, Number($("#th-photo-n").value))); toast("Colors taken from the photo (it stayed in this browser)"); }
      catch (err) { toast(err.message, true); }
    };
    $("#th-warm").oninput = tone;
    $("#th-bright").oninput = tone;
    $("#th-vary").onclick = variations;
    $("#th-surprise").onclick = surprise;
    $("#th-paint-btn").onclick = openPaint;
    $("#th-paint-fill").onclick = () => { const p = palette(); const cs = p ? p.get() : ["#ff8a1c"]; cells = cells.map((_, i) => cs[i % cs.length]); drawCells(); };
    $("#th-paint-use").onclick = useCells;
    window.addEventListener("pointerup", () => { painting = false; });
    $("#th-new").onclick = () => open({draft: blank()});
    $("#th-save").onclick = () => save(false);
    $("#th-saveas").onclick = () => save(true);
    $("#th-delete").onclick = del;
    $("#th-export").onclick = exportThemes;
    $("#th-import").onchange = e => { const f = e.target.files[0]; e.target.value = ""; if (f) importThemes(f); };
    $("#th-pause").onclick = () => {
      if (paused) { t0 += (performance.now() - pausedAt) / 1000; paused = false; }
      else { pausedAt = performance.now(); paused = true; }
      $("#th-pause").textContent = paused ? "Play" : "Pause";
    };
    $("#th-time").onclick = e => {
      if (!data) return;
      const r = e.currentTarget.getBoundingClientRect(), k = Math.floor((e.clientY - r.top) / r.height * data.frames.length);
      t0 = now() - (k + 0.01) / data.fps;
    };
    $("#th-house").onclick = showHouse;
    $("#th-play").onclick = play;
    $("#th-stop").onclick = stop;
    window.addEventListener("beforeunload", e => { if (cur && dirty()) { e.preventDefault(); e.returnValue = ""; } });
  }

  async function init() {
    try { META = await api("/api/themes"); }
    catch (e) { $("#th-msg").textContent = "Themes: " + e.message; return; }
    wire();
    ready = true;
    open({builtin: "diya_glow"});
    requestAnimationFrame(loop);
  }

  return {init, sync};
})();
