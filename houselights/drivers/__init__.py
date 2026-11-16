"""Controller drivers. Each driver module provides LABEL, MODELS, Kit, read_status(kits)
and discover(targets). Add a driver here to support another kind of controller."""
from . import govee
from .base import NotAllowed

DRIVERS = {"govee": govee}

# Shown in the setup wizard but not available yet.
PLANNED = [{"type": "wled", "label": "WLED (open source, ESP32/ESP8266)",
            "note": "Planned. Not supported yet."}]


def get(kind):
    return DRIVERS.get(kind)


def make_kit(controller, live):
    return DRIVERS[controller.type].Kit(controller, live)


def read_status(kits):
    """{controller id: status or None} for all kits, asked per driver."""
    out = {}
    by_type = {}
    for k in kits:
        by_type.setdefault(k.c.type, []).append(k)
    for kind, group in by_type.items():
        out.update(DRIVERS[kind].read_status(group))
    return out


def catalog():
    return ([{"type": t, "label": d.LABEL, "available": True,
              "models": {m: v["label"] for m, v in d.MODELS.items()}} for t, d in DRIVERS.items()]
            + [dict(p, available=False, models={}) for p in PLANNED])


__all__ = ["DRIVERS", "NotAllowed", "get", "make_kit", "read_status", "catalog"]
