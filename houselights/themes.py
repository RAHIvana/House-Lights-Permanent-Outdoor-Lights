"""Themes you make in the Themes tab, saved in themes.json in the settings folder.

    {"version": 1,
     "themes": [{id: "my_<slug>", name, group, layers: [...], direction, mirror, span,
                 sequence?: [{theme, seconds}], fade?}],
     "favourites": [theme ids],
     "hidden_groups": [built-in group names]}

What a theme is and how it is checked and drawn lives in patterns.py; this file only keeps
the list, gives new themes an id, and writes the file atomically (UTF-8). Built-in themes
never change: saving one makes a copy.
"""
import json
import logging
import os
import re
import threading

from . import patterns as P
from . import settings

log = logging.getLogger("houselights")
VERSION = 1
FILE = "themes.json"
_LOCK = threading.RLock()


class Store:
    def __init__(self, path=None):
        self.path = path or settings.path(FILE)
        self.themes, self.favourites, self.hidden_groups = [], [], []
        self.load()

    # file
    def load(self):
        try:
            with open(self.path, encoding="utf-8-sig") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as e:
            log.error("%s could not be read (%s); starting with no themes of your own", self.path, e)
            raw = {}
        themes = []
        known = set(P.PATTERNS) | {t.get("id") for t in raw.get("themes", []) if isinstance(t, dict)}
        for t in raw.get("themes", []) if isinstance(raw.get("themes"), list) else []:
            try:
                th = P.clean_theme(t, known)
                if not th["id"].startswith("my_"):
                    raise ValueError("bad id")
                themes.append(th)
            except ValueError as e:
                log.error("themes.json: skipped %r: %s", (t or {}).get("name") if isinstance(t, dict) else t, e)
        self.themes = themes
        self.favourites = [x for x in raw.get("favourites", []) if isinstance(x, str)]
        self.hidden_groups = [x for x in raw.get("hidden_groups", []) if x in P.CATEGORIES]
        P.set_custom(self.themes)

    def _write(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data(), f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.path)
        P.set_custom(self.themes)

    def data(self):
        return {"version": VERSION, "themes": self.themes, "favourites": self.favourites,
                "hidden_groups": self.hidden_groups}

    def get(self, tid):
        return next((t for t in self.themes if t["id"] == tid), None)

    def _new_id(self, name):
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "theme"
        tid, k = f"my_{slug}", 2
        while self.get(tid) or tid in P.PATTERNS:
            tid, k = f"my_{slug}_{k}", k + 1
        return tid

    # editing
    def save(self, d, as_new=False):
        """Save a theme; an id of a saved theme updates it, anything else makes a new one."""
        with _LOCK:
            th = P.clean_theme(d)
            old = None if as_new else self.get(th["id"])
            if old:
                if th.get("sequence") and th["id"] in {s["theme"] for s in th["sequence"]}:
                    raise ValueError("a sequence can't include itself")
                self.themes[self.themes.index(old)] = th
            else:
                if len(self.themes) >= P.MAX_THEMES:
                    raise ValueError(f"at most {P.MAX_THEMES} themes of your own")
                th["id"] = self._new_id(th["name"])
                self.themes.append(th)
            self._write()
            return th

    def delete(self, tid):
        with _LOCK:
            th = self.get(tid)
            if not th:
                raise KeyError(tid)
            self.themes.remove(th)
            self.favourites = [f for f in self.favourites if f != tid]
            self._write()
            return [t["name"] for t in self.themes if any(s["theme"] == tid for s in t.get("sequence") or [])]

    def set_prefs(self, favourites=None, hidden_groups=None):
        with _LOCK:
            if favourites is not None:
                ok = set(P.PATTERNS) | {t["id"] for t in self.themes}
                self.favourites = list(dict.fromkeys(f for f in favourites if f in ok))[:100]
            if hidden_groups is not None:
                self.hidden_groups = [g for g in dict.fromkeys(hidden_groups) if g in P.CATEGORIES]
            self._write()

    # moving themes between houses
    def export(self):
        return {"version": VERSION, "kind": "houselights-themes", "themes": self.themes}

    def import_(self, raw):
        """Add the themes in an exported file. Ids are renumbered when taken; a sequence's
        steps follow. Returns (added names, {name: error})."""
        if not isinstance(raw, dict) or not isinstance(raw.get("themes"), list):
            raise ValueError("not a themes file (expected {\"themes\": [...]})")
        if len(raw["themes"]) > P.MAX_THEMES:
            raise ValueError(f"at most {P.MAX_THEMES} themes in one file")
        with _LOCK:
            plain = [t for t in raw["themes"] if isinstance(t, dict) and not t.get("sequence")]
            seqs = [t for t in raw["themes"] if isinstance(t, dict) and t.get("sequence")]
            remap, added, errors = {}, [], {}
            for t in plain + seqs:
                name = str(t.get("name") or "?")[:P.MAX_NAME]
                try:
                    t = dict(t)
                    if t.get("sequence"):
                        t["sequence"] = [dict(s, theme=remap.get(s.get("theme"), s.get("theme")))
                                         for s in t["sequence"] if isinstance(s, dict)]
                    th = P.clean_theme(t)
                    if len(self.themes) >= P.MAX_THEMES:
                        raise ValueError(f"at most {P.MAX_THEMES} themes of your own")
                    old_id = str(t.get("id") or "")
                    th["id"] = self._new_id(th["name"])
                    if old_id:
                        remap[old_id] = th["id"]
                    self.themes.append(th)
                    P.set_custom(self.themes)       # later sequences may use it
                    added.append(th["name"])
                except ValueError as e:
                    errors[name] = str(e)
            self._write()
            return added, errors
