"""Controller drivers. Each driver module provides:
  LABEL, NOTE, TESTED, MODELS          shown in the setup wizard
  available() -> (ok, reason)         e.g. an optional package is missing
  options(c, secret) -> (opts, secret) checks the controller's own settings
  discover(targets, deep, expect, known) -> [device rows]   find controllers on the network
                                       (deep: try harder; stop at `expect` with `known` addresses)
  probe(info) -> [device rows]         check one controller added by address
  read_status(kits) -> {id: status}    power, brightness, colour (or None)
  Kit                                  commands; Kit.CAPS says what it can do (see base.py)
"""
from . import govee, jellyfish, tuya, wled
from .base import NotAllowed

DRIVERS = {"govee": govee, "wled": wled, "jellyfish": jellyfish, "tuya": tuya}


def get(kind):
    return DRIVERS.get(kind)


def make_kit(controller, live):
    return DRIVERS[controller.type].Kit(controller, live)


def caps(kind):
    return DRIVERS[kind].Kit.CAPS


def read_status(kits):
    """{controller id: status or None} for all kits, asked per driver."""
    out = {}
    by_type = {}
    for k in kits:
        by_type.setdefault(k.c.type, []).append(k)
    for kind, group in by_type.items():
        try:
            out.update(DRIVERS[kind].read_status(group))
        except Exception:                      # one kind of controller failing mustn't hide the rest
            out.update({k.c.id: None for k in group})
    return out


def catalog():
    out = []
    for t, d in DRIVERS.items():
        ok, reason = d.available()
        out.append({"type": t, "label": d.LABEL, "note": d.NOTE, "tested": d.TESTED, "available": ok,
                    "reason": reason, "caps": d.Kit.CAPS,
                    "models": {m: v["label"] for m, v in d.MODELS.items()}})
    return out


__all__ = ["DRIVERS", "NotAllowed", "get", "make_kit", "caps", "read_status", "catalog"]
