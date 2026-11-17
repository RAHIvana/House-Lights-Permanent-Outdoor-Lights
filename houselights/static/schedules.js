"use strict";
// Schedules panel and its dialog. Uses $, api, toast, CONFIG, fillPatterns, patternById from app.js.
const Schedules = (() => {
  let OV = null, EDIT = null, previewTimer = null, SKEW = 0;
  const DAY_ORDER = [6, 0, 1, 2, 3, 4, 5];                 // Sun..Sat shown; Mon=0 like Python
  const DAY_SHORT = {6: "S", 0: "M", 1: "T", 2: "W", 3: "T", 4: "F", 5: "S"};
  const DAY_NAME = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"};
  const dlg = () => $("#sched-dialog");
  const f = k => $(`[data-k="${k}"]`, dlg());
  const num = k => Math.max(0, Number(f(k).value) || 0);

  // --- formatting (in the house's time zone, wherever the phone is) ----------------------
  const fmt = (iso, opts) => new Date(iso).toLocaleString([], {timeZone: OV.timezone, ...opts});
  const clock = iso => fmt(iso, {hour: "numeric", minute: "2-digit"});
  const dayClock = iso => fmt(iso, {weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
  const sameDay = (a, b) => fmt(a, {dateStyle: "short"}) === fmt(b, {dateStyle: "short"});
  const hm = mins => [Math.floor(mins / 60) && `${Math.floor(mins / 60)} h`, mins % 60 && `${mins % 60} m`]
    .filter(Boolean).join(" ") || "0 m";
  const cap = s => s[0].toUpperCase() + s.slice(1);

  function ruleText(r) {
    if (r.type === "time") {
      const [h, m] = r.time.split(":").map(Number);
      return new Date(2000, 0, 1, h, m).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
    }
    if (r.type === "after") return `${hm(r.minutes)} later`;
    return cap(r.type) + (r.offset ? ` ${r.offset > 0 ? "+" : "−"} ${hm(Math.abs(r.offset))}` : "");
  }

  function daysText(days) {
    const k = days.join(",");
    if (k === "0,1,2,3,4,5,6") return "Every day";
    if (k === "0,1,2,3,4") return "Weekdays";
    if (k === "5,6") return "Weekends";
    return DAY_ORDER.filter(d => days.includes(d)).map(d => DAY_NAME[d]).join(", ");
  }

  function themeText(t) {
    const label = OV.themes[t.pattern] || (patternById(t.pattern) || {label: t.pattern}).label;
    return t.pattern === "keep" ? label : `${label} ${t.level}%`;
  }

  function sectionsText(ids) {
    const enabled = CONFIG.sections.filter(s => s.enabled).map(s => s.id);
    if (enabled.every(id => ids.includes(id))) return "Whole house";
    return CONFIG.sections.filter(s => ids.includes(s.id)).map(s => s.name).join(", ");
  }

  function windowText(n) {
    return sameDay(n.start, n.end) ? `${dayClock(n.start)} → ${clock(n.end)}` : `${dayClock(n.start)} → ${dayClock(n.end)}`;
  }

  // --- list ------------------------------------------------------------------------------
  function render() {
    const paused = OV.paused_until;
    $("#sched-pause").textContent = paused ? "Resume schedules" : "Pause tonight";
    $("#sched-pause").hidden = !OV.schedules.length && !paused;
    $("#sched-state").textContent = (paused ? `Paused until ${dayClock(paused)}`
      : OV.sun ? `Today: sunrise ${clock(OV.sun.sunrise)}, sunset ${clock(OV.sun.sunset)}`
      : "Sunrise/sunset schedules need your location: Settings tab, Change setup")
      + (OV.now ? ` · Server time ${clock(new Date(Date.now() + SKEW).toISOString())}` : "");
    // The schedules run on the server's clock: say so if it and this browser's clock disagree.
    const off = Math.round(Math.abs(SKEW) / 60000), warn = $("#sched-clock");
    warn.hidden = !OV.now || off <= 2;
    warn.textContent = `This computer's clock is off by ${off < 60 ? off + " minutes" : hm(off)}; schedules may run `
      + "at the wrong time. Check the server's date and time settings.";
    const list = $("#sched-list");
    list.innerHTML = "";
    if (!OV.schedules.length) {
      const li = document.createElement("li");
      li.className = "sched-empty";
      li.textContent = "No schedules yet. Add one to switch the lights on and off by themselves.";
      list.appendChild(li);
    }
    OV.schedules.forEach((s, i) => {
      const li = document.createElement("li");
      li.className = "sched" + (s.enabled ? "" : " off");
      li.innerHTML = `<label class="switch"><input type="checkbox"></label>
        <div class="sched-main"><div class="sched-name"><span></span></div>
        <div class="sched-sub"></div><div class="sched-when"></div></div>
        <div class="sched-btns"><button class="ghost small" data-mv="-1" title="Move up (wins over lower ones)">↑</button>
        <button class="ghost small" data-mv="1" title="Move down">↓</button>
        <button class="small" data-edit>Edit</button></div>`;
      $(".sched-name span", li).textContent = s.name;
      if (s.active) {
        const b = document.createElement("span");
        b.className = "badge";
        b.textContent = "On now";
        $(".sched-name", li).appendChild(b);
      }
      const range = s.date_from || s.date_to
        ? ` · ${s.date_from ? fmtDate(s.date_from) : "…"} – ${s.date_to ? fmtDate(s.date_to) : "…"}` : "";
      $(".sched-sub", li).textContent = `${sectionsText(s.sections)} · ${daysText(s.days)}${range} · `
        + `${ruleText(s.on)} → ${ruleText(s.off)} · ${themeText(s.theme)}`;
      const errs = s.sections.map(id => OV.last[id]).filter(l => l && l.error);
      $(".sched-when", li).textContent = !s.enabled ? "Off"
        : s.active ? `Until ${clock(s.next.end)}` + (OV.override.some(id => s.sections.includes(id)) ? " · changed by hand" : "")
        : s.next ? `Next: ${windowText(s.next)}` : "No more dates in range";
      if (errs.length) {
        const e = document.createElement("div");
        e.className = "sched-err";
        e.textContent = "Last try failed: " + errs[0].error;
        $(".sched-main", li).appendChild(e);
      }
      const cb = $("input", li);
      cb.checked = s.enabled;
      cb.onchange = () => post("/api/schedules/enabled", {id: s.id, enabled: cb.checked});
      li.querySelector('[data-mv="-1"]').disabled = i === 0;
      li.querySelector('[data-mv="1"]').disabled = i === OV.schedules.length - 1;
      for (const b of li.querySelectorAll("[data-mv]")) b.onclick = () => {
        const ids = OV.schedules.map(x => x.id), j = i + Number(b.dataset.mv);
        [ids[i], ids[j]] = [ids[j], ids[i]];
        post("/api/schedules/order", {ids});
      };
      $("[data-edit]", li).onclick = () => open(s);
      list.appendChild(li);
    });
    fitList(list);
  }

  // Four schedules show at a time; the rest scroll inside the list.
  const SHOWN = 4;
  function fitList(list) {
    list.style.maxHeight = "";
    const items = list.children;
    if (items.length <= SHOWN || !list.offsetParent) return;
    const last = items[SHOWN - 1];
    list.style.maxHeight = `${last.offsetTop + last.offsetHeight - items[0].offsetTop + 1}px`;
  }

  const fmtDate = d => new Date(d + "T12:00").toLocaleDateString([], {month: "short", day: "numeric"});

  // Server clock minus this browser's clock, in ms, from the overview's "now".
  function got(ov) {
    OV = ov;
    if (OV.now) SKEW = new Date(OV.now).getTime() - Date.now();
    render();
  }

  async function post(path, body) {
    try { got(await api(path, body)); return true; }
    catch (e) { toast(e.message, true); load(); return false; }
  }

  async function load() {
    try { got(await api("/api/schedules")); } catch (e) { toast("Schedules: " + e.message, true); }
  }

  // --- dialog ----------------------------------------------------------------------------
  function setDays(days) {
    for (const b of $("#sd-days").children) b.classList.toggle("on", days.includes(Number(b.dataset.day)));
  }
  const getDays = () => [...$("#sd-days").children].filter(b => b.classList.contains("on")).map(b => Number(b.dataset.day));

  function setRule(p, r) {
    f(`${p}-type`).value = r.type;
    if (r.type === "time") f(`${p}-time`).value = r.time;
    else if (r.type === "after") { f("off-dh").value = Math.floor(r.minutes / 60); f("off-dm").value = r.minutes % 60; }
    else {
      const m = Math.abs(r.offset || 0);
      f(`${p}-h`).value = Math.floor(m / 60); f(`${p}-m`).value = m % 60;
      f(`${p}-sign`).value = (r.offset || 0) < 0 ? "-1" : "1";
    }
  }

  function getRule(p) {
    const type = f(`${p}-type`).value;
    if (type === "time") return {type, time: f(`${p}-time`).value};
    if (type === "after") return {type, minutes: num("off-dh") * 60 + num("off-dm")};
    return {type, offset: Number(f(`${p}-sign`).value) * (num(`${p}-h`) * 60 + num(`${p}-m`))};
  }

  function syncVisibility() {
    for (const p of ["on", "off"]) {
      const t = f(`${p}-type`).value;
      f(`${p}-time`).hidden = t !== "time";
      const off = $(`.offset[data-for="${p}"]`, dlg());
      off.hidden = t !== "sunrise" && t !== "sunset";
      $(".evt", off).textContent = t;
    }
    $(".duration", dlg()).hidden = f("off-type").value !== "after";
    const only = $('input[name="sd-range"]:checked', dlg()).value === "only";
    f("date_from").disabled = f("date_to").disabled = !only;
    const pat = f("pattern").value, p = patternById(pat);
    $("#sd-describe").textContent = pat === "keep" ? "Turns the kits on with whatever they showed last."
      : pat === "warm_white" ? "Plain warm white on every light."
      : p.animated ? `${p.describe || ""} Animated: the dashboard plays it light by light while the schedule is on.`
      : (p.describe || "Static theme, set as segment colours on each kit.");
    f("level").disabled = pat === "keep";
  }

  function readForm() {
    const only = $('input[name="sd-range"]:checked', dlg()).value === "only";
    return {
      id: EDIT && EDIT.id, name: f("name").value, enabled: f("enabled").checked,
      sections: [...$("#sd-sections").querySelectorAll("input:checked")].map(i => i.value),
      days: getDays(),
      date_from: only ? f("date_from").value || null : null,
      date_to: only ? f("date_to").value || null : null,
      on: getRule("on"), off: getRule("off"),
      theme: {pattern: f("pattern").value, params: {}, level: Number(f("level").value) || 100},
    };
  }

  function schedulePreview() {
    syncVisibility();
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      const line = $("#sd-next");
      try {
        const r = await api("/api/schedules/preview", readForm());
        line.classList.remove("err");
        line.textContent = r.next.length ? "Next: " + r.next.map(windowText).join(" · ")
          : "No dates left in this range.";
      } catch (e) { line.classList.add("err"); line.textContent = e.message; }
    }, 250);
  }

  function open(s) {
    EDIT = s || null;
    const enabled = CONFIG.sections.filter(x => x.enabled).map(x => x.id);
    s = s || {name: "", enabled: true, sections: enabled, days: [0, 1, 2, 3, 4, 5, 6],
              date_from: null, date_to: null,
              on: OV.location_set ? {type: "sunset", offset: 60} : {type: "time", time: "20:00"},
              off: OV.location_set ? {type: "after", minutes: 180} : {type: "time", time: "22:00"},
              theme: {pattern: "keep", params: {}, level: 100}};
    $("#sd-heading").textContent = EDIT ? "Edit schedule" : "New schedule";
    f("name").value = s.name;
    f("enabled").checked = s.enabled;
    for (const i of $("#sd-sections").querySelectorAll("input")) i.checked = s.sections.includes(i.value);
    setDays(s.days);
    $(`input[name="sd-range"][value="${s.date_from || s.date_to ? "only" : "all"}"]`, dlg()).checked = true;
    f("date_from").value = s.date_from || "";
    f("date_to").value = s.date_to || "";
    setRule("on", s.on);
    setRule("off", s.off);
    f("pattern").value = s.theme.pattern;
    f("level").value = s.theme.level;
    $("#sd-delete").hidden = !EDIT;
    for (const o of dlg().querySelectorAll('option[value="sunset"], option[value="sunrise"]'))
      o.disabled = !OV.location_set;
    $("#sd-next").textContent = "";
    dlg().showModal();
    schedulePreview();
  }

  function build() {
    const box = $("#sd-sections");
    for (const sec of CONFIG.sections) {
      const l = document.createElement("label");
      l.className = "chip";
      l.innerHTML = `<input type="checkbox"> <span></span>`;
      $("input", l).value = sec.id;
      $("input", l).disabled = !sec.enabled;
      $("span", l).textContent = sec.name + (sec.enabled ? "" : " (disabled)");
      box.appendChild(l);
    }
    const days = $("#sd-days");
    for (const d of DAY_ORDER) {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.day = d;
      b.textContent = DAY_SHORT[d];
      b.title = DAY_NAME[d];
      b.onclick = () => { b.classList.toggle("on"); schedulePreview(); };
      days.appendChild(b);
    }
    for (const b of dlg().querySelectorAll("[data-days]")) b.onclick = () => {
      setDays(b.dataset.days.split(",").map(Number)); schedulePreview();
    };
    const sel = f("pattern");
    const og = document.createElement("optgroup");
    og.label = "Simple";
    og.appendChild(new Option("Last used (just turn on)", "keep"));
    og.appendChild(new Option("Warm white 2200 K", "warm_white"));
    sel.appendChild(og);
    fillPatterns(sel, "keep");
    dlg().addEventListener("input", schedulePreview);
    dlg().addEventListener("change", schedulePreview);
    $("#sd-cancel").onclick = () => dlg().close();
    $("#sd-save").onclick = async () => {
      const body = readForm();
      if (await post("/api/schedules/save", body)) {
        dlg().close();
        toast(`Saved "${body.name}"` + (CONFIG.mode === "dry" ? " (dry run: the scheduler only logs)" : ""));
      }
    };
    $("#sd-delete").onclick = async () => {
      if (EDIT && confirm(`Delete "${EDIT.name}"?`) && await post("/api/schedules/delete", {id: EDIT.id})) dlg().close();
    };
    $("#sched-add").onclick = () => open(null);
    $("#sched-pause").onclick = () => post("/api/schedules/pause", {pause: !OV.paused_until});
  }

  async function init() {
    build();
    await load();
    setInterval(() => { if (!document.hidden && !dlg().open) load(); }, 60000);
  }

  return {init, load};
})();
