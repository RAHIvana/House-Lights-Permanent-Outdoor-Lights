"""Themes you make: storage, validation, the engine (layers, shape, sequences, whole-house
span) and schedules using them. No lights, no network.

    python tests/test_themes.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from houselights import patterns as P  # noqa: E402
from houselights import schedule as SC  # noqa: E402
from houselights import themes  # noqa: E402


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        check.failed = True


check.failed = False


def raises(fn, text=""):
    try:
        fn()
    except ValueError as e:
        return text.lower() in str(e).lower()
    return False


def theme(**kw):
    d = {"name": "Test", "layers": [{"movement": "bands", "params": {"colors": "#ff0000,#00ff00,#0000ff", "width": 1}}]}
    d.update(kw)
    return d


R, G, B, K = (255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 0, 0)

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "themes.json")

    # --- storage round trip ---------------------------------------------------------------
    st = themes.Store(path)
    a = st.save(theme(name="Diwali Night ✨", group="Diwali"))
    check("new theme gets a my_ id", a["id"] == "my_diwali_night")
    b = st.save(theme(name="Diwali Night ✨"))
    check("same name: unique id", b["id"] == "my_diwali_night_2")
    a2 = st.save(dict(a, direction="rtl"))
    check("saving with its id updates it", a2["id"] == a["id"] and len(st.themes) == 2 and st.get(a["id"])["direction"] == "rtl")
    c = st.save(dict(a, name="Copy"), as_new=True)
    check("save as new makes a copy", c["id"] != a["id"] and len(st.themes) == 3)
    cp = st.save({"id": "diya_glow", "name": "My diya", "layers": [{"movement": "builtin:diya_glow", "params": {"speed": 2}}]})
    check("saving a built-in makes a copy (built-in unchanged)", cp["id"].startswith("my_") and "diya_glow" in P.PATTERNS)
    st.set_prefs(favourites=[a["id"], "diya_glow", "nope"], hidden_groups=["Halloween", "Nope"])
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    check("file is UTF-8 JSON with version", raw["version"] == 1 and raw["themes"][0]["name"] == "Diwali Night ✨")
    st2 = themes.Store(path)
    check("round trip", st2.themes == st.themes and st2.favourites == [a["id"], "diya_glow"]
          and st2.hidden_groups == ["Halloween"])
    check("custom themes in the catalogue", any(p["id"] == a["id"] and p["custom"] and p["group"] == P.MY_GROUP
                                                 and "Diwali" in p["categories"] for p in P.catalogue()))
    st2.delete(b["id"])
    check("delete", st2.get(b["id"]) is None and len(st2.themes) == 3)
    check("deleted theme fails clearly", raises(lambda: P.frame(b["id"], 10, {}), "no longer exists"))

    # --- validation -------------------------------------------------------------------------
    check("name required", raises(lambda: P.clean_theme(theme(name=" ")), "name"))
    check("name max 40", raises(lambda: P.clean_theme(theme(name="x" * 41)), "40"))
    check("max 3 layers", raises(lambda: P.clean_theme(theme(layers=[{"movement": "solid"}] * 4)), "layers"))
    check("unknown movement", raises(lambda: P.clean_theme(theme(layers=[{"movement": "zap"}])), "movement"))
    check("max 12 colours", raises(lambda: P.clean_theme(theme(layers=[{"movement": "bands", "params": {
        "colors": ",".join(["#ffffff"] * 13)}}])), "12"))
    check("bad colour", raises(lambda: P.clean_theme(theme(layers=[{"movement": "bands", "params": {"colors": "#ff"}}]))))
    check("speed out of range", raises(lambda: P.clean_theme(theme(layers=[{"movement": "chase", "params": {"speed": 500}}])), "speed"))
    check("not a number", raises(lambda: P.clean_theme(theme(layers=[{"movement": "chase", "params": {"speed": "fast"}}])), "number"))
    check("bad direction", raises(lambda: P.clean_theme(theme(direction="up")), "direction"))
    check("bad blend", raises(lambda: P.clean_theme(theme(layers=[{"movement": "solid"}, {"movement": "sparkle", "blend": "x"}])), "blend"))
    check("bad flicker style", raises(lambda: P.clean_theme(theme(layers=[{"movement": "flicker", "params": {"style": "x"}}])), "style"))
    check("max 8 steps", raises(lambda: P.clean_theme(theme(sequence=[{"theme": "solid", "seconds": 5}] * 9)), "8"))
    check("step must exist", raises(lambda: P.clean_theme(theme(sequence=[{"theme": "my_nope", "seconds": 5}])), "unknown"))
    check("unknown settings are dropped", "zzz" not in P.clean_theme(theme(layers=[{"movement": "solid", "params": {"zzz": 1}}]))["layers"][0]["params"])
    check("draft fails on bad theme", raises(lambda: P.frame("_draft", 10, {"theme": theme(name="")}), "name"))

    # --- every movement renders through frame() as a saved theme ----------------------------
    bad = []
    for mv in P.MOVEMENTS:
        th = st2.save(theme(name=f"mv {mv}", layers=[{"movement": mv}]))
        for t in (0.0, 1.7, 33.3):
            out = P.frame(th["id"], 73, {}, t)
            if len(out) != 73 or not all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in out):
                bad.append(mv)
        if P.is_animated(th["id"]) != (P.MOVEMENTS[mv]["kind"] != "still"):
            bad.append(mv + " animated flag")
    check(f"all {len(P.MOVEMENTS)} movements render", not bad)
    check("a built-in as a layer renders like the built-in",
          P.frame("_draft", 50, {"theme": theme(layers=[{"movement": "builtin:rangoli_chase"}])}, 2.0)
          == P.frame("rangoli_chase", 50, {}, 2.0))

    # --- layers, direction, mirror (deterministic) -------------------------------------------
    rgb = {"movement": "bands", "params": {"colors": "#ff0000,#00ff00,#0000ff", "width": 1}}
    d = lambda **kw: P.frame("_draft", 6, {"theme": theme(layers=[rgb], **kw)})       # noqa: E731
    check("left to right", d() == [R, G, B, R, G, B])
    check("right to left", d(direction="rtl") == [B, G, R, B, G, R])
    check("mirror", d(mirror=True) == [R, G, B, B, G, R])
    check("from the middle outward", d(direction="out") == [B, G, R, R, G, B])
    blue = {"movement": "solid", "params": {"colors": "#0000ff"}}
    red_g = {"movement": "bands", "params": {"colors": "#ff0000,#000000", "width": 1}}
    lay = lambda how: P.frame("_draft", 4, {"theme": theme(layers=[blue, dict(red_g, blend=how)])})  # noqa: E731
    check("layer over: black is see-through", lay("over") == [R, B, R, B])
    check("layer add", lay("add") == [(255, 0, 255), B, (255, 0, 255), B])
    check("layer max", lay("max") == [(255, 0, 255), B, (255, 0, 255), B])
    chase = theme(layers=[{"movement": "chase", "params": {"colors": "#ff0000,#0000ff", "width": 3, "speed": 2}}],
                  direction="bounce")
    f = lambda t: P.frame("_draft", 30, {"theme": chase}, t)      # noqa: E731
    check("bounce: time runs back", f(P.BOUNCE_S + 3) == f(P.BOUNCE_S - 3) and f(1) != f(2))
    check("still theme is not animated", not P.is_animated("_draft", {"theme": theme()}))

    # --- sequence -----------------------------------------------------------------------------
    red = st2.save(theme(name="Red", layers=[{"movement": "solid", "params": {"colors": "#ff0000"}}]))
    grn = st2.save(theme(name="Green", layers=[{"movement": "solid", "params": {"colors": "#00ff00"}}]))
    seq = st2.save({"name": "Seq", "sequence": [{"theme": red["id"], "seconds": 10}, {"theme": grn["id"], "seconds": 5}],
                    "fade": 2})
    s = lambda t: P.frame(seq["id"], 3, {}, t)[0]                 # noqa: E731
    check("sequence step 1", s(1) == R and s(7.9) == R)
    check("sequence cross-fade", s(9) == (128, 128, 0) or s(9) == (127, 128, 0))
    check("sequence step 2, then repeats", s(11) == G and s(15.5) == R)
    check("sequence is animated", P.is_animated(seq["id"]))
    check("sequence can't contain a sequence",
          raises(lambda: st2.save({"name": "S2", "sequence": [{"theme": seq["id"], "seconds": 5}]}), "sequence"))

    # --- whole-house span: one strip across the runs, sliced; a reversed run back to front ---
    house = theme(layers=[{"movement": "gradient", "params": {"colors": "#000000,#ffffff"}}], span="house")
    runs = [("left", 3, False), ("mid", 4, True), ("right", 3, False)]
    hf = P.house_frames("_draft", {"theme": house}, 0.0, runs)
    full = P.frame("_draft", 10, {"theme": house})
    check("span recorded", P.span_of("_draft", {"theme": house}) == "house" and P.span_of("solid") == "run")
    check("house slices", hf["left"] == full[0:3] and hf["right"] == full[7:10])
    check("reversed run gets its slice back to front", hf["mid"] == full[3:7][::-1])
    check("continuous across runs", hf["left"][-1][0] < full[3][0] < hf["right"][0][0])

    # --- schedules accept a theme of your own; a deleted one fails clearly -------------------
    check_theme = lambda p, q: P.frame(p, 10, q)                 # what app._check_theme does  # noqa: E731
    sd = {"name": "t", "sections": ["run_a"], "days": [0], "on": {"type": "time", "time": "20:00"},
          "off": {"type": "time", "time": "22:00"}, "theme": {"pattern": red["id"], "level": 80}}
    check("schedule accepts a custom theme", SC.clean(sd, ["run_a"], None, check_theme)["theme"]["pattern"] == red["id"])
    st2.delete(red["id"])
    check("schedule with a deleted theme: clear error",
          raises(lambda: SC.clean(sd, ["run_a"], None, check_theme), "deleted"))
    check("sequence with a deleted step: clear error", raises(lambda: P.frame(seq["id"], 3, {}, 1), "deleted"))

    # --- export / import -----------------------------------------------------------------------
    exp = st2.export()
    st3 = themes.Store(os.path.join(tmp, "other.json"))
    added, errors = st3.import_(json.loads(json.dumps(exp)))
    check("import adds every valid theme", len(added) == len([t for t in exp["themes"] if not t.get("sequence")]))
    check("import reports the broken sequence", list(errors) == ["Seq"])
    added, errors = st3.import_({"themes": [theme(name="Again"), {"name": ""}]})
    check("import: good one added, bad one reported", added == ["Again"] and len(errors) == 1)
    check("import: not a themes file", raises(lambda: st3.import_({"x": 1}), "themes"))
    P.set_custom([])

sys.exit(1 if check.failed else 0)
