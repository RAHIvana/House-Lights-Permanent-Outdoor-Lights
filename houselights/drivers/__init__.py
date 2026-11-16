"""Controller drivers. Each driver module provides:
  LABEL, NOTE, TESTED, MODELS          shown in the setup wizard
  available() -> (ok, reason)         e.g. an optional package is missing
  options(c, secret) -> (opts, secret) checks the controller's own settings
  discover(targets, deep, expect, known) -> [device rows]   find controllers on the network
                                       (deep: try harder; stop at `expect` with `known` addresses)
  probe(info) -> [device rows]         check one controller added by address
  read_status(kits) -> {id: status}    power, brightness, colour (or None)
  Kit                                  commands; Kit.CAPS says what it can do (see base.py)
Optional, when models of one driver differ (Govee):
  model_info(model) -> info or None    {model, label, tier, caps, max_lights, lights_per_segment, note}
  TIERS, MODELS_NOTE                   shown in the setup wizard
Use model_info(kind, model) / model_caps(kind, model) below for one controller.
"""
from . import govee, jellyfish, tuya, wled
from .base import NotAllowed

DRIVERS = {"govee": govee, "wled": wled, "jellyfish": jellyfish, "tuya": tuya}


def get(kind):
    return DRIVERS.get(kind)


def make_kit(controller, live):
    return DRIVERS[controller.type].Kit(controller, live)


def caps(kind):
    """Driver-level capabilities (the best model). For one controller use model_caps()."""
    return DRIVERS[kind].Kit.CAPS


def model_info(kind, model):
    """{model, label, tier, caps, max_lights, lights_per_segment, note} for one model of a
    driver, or None if the driver doesn't know or accept that model. Drivers without per-model
    tiers: their MODELS entry and Kit.CAPS, tier None."""
    drv = DRIVERS.get(kind)
    if not drv:
        return None
    if hasattr(drv, "model_info"):
        return drv.model_info(model)
    m = drv.MODELS.get(model)
    if m is None:
        return None
    return {"model": model, "label": m["label"], "tier": None, "caps": dict(drv.Kit.CAPS),
            "max_lights": m.get("max_lights", 3000), "lights_per_segment": m.get("lights_per_segment", 0),
            "note": ""}


def model_caps(kind, model):
    """What a controller of this model can do (falls back to the driver's Kit.CAPS)."""
    info = model_info(kind, model)
    return info["caps"] if info else dict(DRIVERS[kind].Kit.CAPS)


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
    """Per driver: a summary (caps of its best model), "models" (labels of its fully supported
    models), "model_info" for every model it knows by name, and for drivers with tiers
    (Govee) "tiers" {tier: {label, note, caps, max_lights, lights_per_segment}} and
    "models_note" (which models are in which tier; other SKUs are accepted as "basic")."""
    out = []
    for t, d in DRIVERS.items():
        ok, reason = d.available()
        infos = {m: model_info(t, m) for m in d.MODELS}
        out.append({"type": t, "label": d.LABEL, "note": d.NOTE, "tested": d.TESTED, "available": ok,
                    "reason": reason, "caps": d.Kit.CAPS,
                    "models": {m: i["label"] for m, i in infos.items() if i["tier"] in (None, "full")},
                    "model_info": infos,
                    "tiers": {k: {"label": v["label"], "note": v["note"], "caps": dict(v["caps"]),
                                  "max_lights": v["max_lights"], "lights_per_segment": v["lights_per_segment"]}
                              for k, v in getattr(d, "TIERS", {}).items()},
                    "models_note": getattr(d, "MODELS_NOTE", "")})
    return out


__all__ = ["DRIVERS", "NotAllowed", "get", "make_kit", "caps", "model_info", "model_caps", "read_status",
           "catalog"]
