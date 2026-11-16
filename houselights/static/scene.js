"use strict";
// Scene editor: one theme on one run, shown two ways at once.
//  - Strip: the lights as they'd look right now, animated.
//  - Time strip: every moment of the effect stacked top to bottom (x = light, y = time), so a
//    chase shows as diagonal stripes, a flicker as speckle, a burst as a V.
// Settings are previewed from the server (same code that drives the lights); nothing is sent
// until Play live / Apply. "Show in Visualization" hands the same frames to the Visualization panel.
// Uses $, api, toast, CONFIG, STATUS, fillPatterns, patternById, labelOf, buildParams,
// readParams, previewData, showInViz, refresh from app.js.
const Scene = (() => {
  const FPS = 12;
  let data = null, t0 = 0, paused = false, pausedAt = 0, timer = null, seq = 0, ready = false;
  const off = document.createElement("canvas");          // the time strip at 1 px per light x frame

  const sid = () => $("#sc-run").value;
  const pattern = () => $("#sc-theme").value;
  const params = () => readParams($("#sc-params"));
  const secOf = () => CONFIG.sections.find(s => s.id === sid());
  const now = () => (paused ? pausedAt : performance.now()) / 1000;
  const frameIndex = () => data ? Math.floor((now() - t0) * data.fps) % data.frames.length : 0;

  function describe() {
    const p = patternById(pattern()), sec = secOf();
    $("#sc-describe").textContent = (p.describe || "Static theme.")
      + (p.animated ? "" : " Apply sends it as one color per 5-light segment, which is what you see here.");
    $("#sc-play").textContent = (p.animated ? "Play live on " : "Apply on ") + sec.name;
    $("#sc-stop").textContent = "Stop " + sec.name;
    $("#sc-nlab").textContent = `light ${sec.lights}`;
    $("#sc-t1").textContent = `${$("#sc-len").value} s`;
  }

  function load() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const my = ++seq;
      $("#sc-msg").textContent = "Updating…";
      try {
        const d = await previewData(sid(), pattern(), params(), Number($("#sc-len").value), FPS);
        if (my !== seq) return;
        data = {...d, frames: d.frames || [d.lights], fps: d.frames ? d.fps : FPS};
        t0 = now();
        drawTimeImage();
        $("#sc-msg").textContent = "";
      } catch (e) { if (my === seq) $("#sc-msg").textContent = e.message; }
    }, 250);
  }

  const rgb = h => h ? [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)] : [26, 28, 32];

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
    const c = $("#sc-strip"), [w, h, dpr] = fit(c), g = c.getContext("2d");
    g.clearRect(0, 0, w, h);
    const n = row.length, step = w / n, r = Math.max(1.5 * dpr, Math.min(step * 0.36, 7 * dpr));
    for (let i = 0; i < n; i++) {
      const col = row[i] || "#41454c";
      g.shadowColor = row[i] || "transparent"; g.shadowBlur = row[i] ? 10 * dpr : 0;
      g.fillStyle = col;
      g.beginPath(); g.arc(step * (i + 0.5), h / 2, r, 0, Math.PI * 2); g.fill();
    }
    g.shadowBlur = 0;
  }

  function drawTime(k) {
    const c = $("#sc-time"), [w, h, dpr] = fit(c), g = c.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.clearRect(0, 0, w, h);
    g.drawImage(off, 0, 0, w, h);
    const y = (k + 0.5) / data.frames.length * h;
    g.fillStyle = "rgba(255,255,255,.85)"; g.fillRect(0, y - dpr, w, 2 * dpr);
  }

  function loop() {
    if (data && !document.hidden && $("#scene").getBoundingClientRect().bottom > 0) {
      const k = frameIndex();
      drawStrip(data.frames[k]);
      drawTime(k);
      $("#sc-clock").textContent = `${(k / data.fps).toFixed(1)} s`;
    }
    requestAnimationFrame(loop);
  }

  function sync() {
    if (!ready) return;
    const st = STATUS[sid()], s = st && st.stream;
    const playingThis = s && s.pattern === pattern() && JSON.stringify(s.params || {}) === JSON.stringify(params());
    const a = st && st.assumed;
    const showsThis = !patternById(pattern()).animated && !s && a && a.pattern === pattern() && JSON.stringify(a.params || {}) === JSON.stringify(params());
    $("#sc-play").classList.toggle("on", !!(playingThis || showsThis));
    $("#sc-stop").disabled = !s;
    $("#sc-house").classList.toggle("on", !!PREVIEW && PREVIEW.source === "scene");
  }

  function onTheme() {
    buildParams($("#sc-params"), patternById(pattern()));
    describe(); load(); sync();
  }

  function init() {
    const run = $("#sc-run");
    for (const s of CONFIG.sections) if (s.enabled) run.appendChild(new Option(`${s.name} (${s.lights})`, s.id));
    fillPatterns($("#sc-theme"), "diya_glow");
    run.onchange = () => { describe(); load(); sync(); };
    $("#sc-theme").onchange = onTheme;
    $("#sc-len").onchange = () => { describe(); load(); };
    $("#sc-params").addEventListener("input", () => { load(); sync(); });
    $("#sc-pause").onclick = () => {
      if (paused) { t0 += (performance.now() - pausedAt) / 1000; paused = false; }
      else { pausedAt = performance.now(); paused = true; }
      $("#sc-pause").textContent = paused ? "Play" : "Pause";
    };
    $("#sc-time").onclick = e => {
      if (!data) return;
      const r = e.currentTarget.getBoundingClientRect(), k = Math.floor((e.clientY - r.top) / r.height * data.frames.length);
      t0 = now() - (k + 0.01) / data.fps;
    };
    $("#sc-house").onclick = () => { if (data) showInViz(sid(), data, pattern()); };
    $("#sc-play").onclick = async () => {
      const body = {pattern: pattern(), params: params()};
      if (PREVIEW) setPreview(null);
      try {
        const r = patternById(body.pattern).animated
          ? await api(`/api/sections/${sid()}/play`, {...body, level: 100})
          : await api(`/api/sections/${sid()}/pattern`, body);
        toast(r.mode === "dry" ? "Dry run: logged, nothing sent" : `Sent to ${secOf().name}`);
      } catch (e) { toast(e.message, true); }
      afterAction();
    };
    $("#sc-stop").onclick = async () => {
      try { await api(`/api/sections/${sid()}/stop`, {}); toast(`Stopped ${secOf().name}. The lights stay on.`); }
      catch (e) { toast(e.message, true); }
      afterAction();
    };
    ready = true;
    onTheme();
    requestAnimationFrame(loop);
  }

  return {init, sync};
})();
