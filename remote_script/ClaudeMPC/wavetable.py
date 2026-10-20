# -*- coding: utf-8 -*-
"""Wavetable's own API (Live 10.1 WavetableDevice): wavetables, mono/poly, unison, filter
routing, oscillator effect modes and the modulation matrix. None of these are device
parameters, so get_device_params can't see them.

Pure Python 2.7 / 3 compatible, no Live imports (like lom.py and ops.py).

settings = {
  "osc1": {"category": "Basics", "table": "Basic Shapes", "effect_mode": "Classic"},
  "osc2": {...},
  "mono": true, "poly_voices": 8,
  "unison": {"mode": "Classic", "voices": 4},
  "filter_routing": "Serial",
  "modulation": [{"target": "Osc 1 Transp", "source": "Env 2", "amount": -0.08}, ...]
}
"""
from __future__ import absolute_import

try:
    from . import lom
except (ImportError, ValueError):  # tests import it as a top-level module
    import lom

_text = lom._text
CLASS_NAME = "InstrumentVector"
# Live's enums, in the order of the device's menus
EFFECT_MODES = ["None", "FM", "Classic", "Modern"]
UNISON_MODES = ["None", "Classic", "Shimmer", "Noise", "Phase Sync", "Position Spread", "Random Note"]
FILTER_ROUTINGS = ["Serial", "Parallel", "Split"]
VOICES = [2, 3, 4, 5, 6, 7, 8]  # unison_voice_count
POLY_VOICES = [2, 3, 4, 5, 6, 7, 8, 16, 24, 32]
# columns of the modulation matrix (get/set_modulation_value source index)
SOURCES = ["Env 1", "Env 2", "Env 3", "LFO 1", "LFO 2", "Velocity", "Note", "Pitch Bend",
           "Pressure", "Mod Wheel", "Random"]
SOURCE_ALIASES = {"amp": 0, "amp env": 0, "env 1": 0, "env1": 0, "env 2": 1, "env2": 1, "env 3": 2,
                  "env3": 2, "lfo 1": 3, "lfo1": 3, "lfo 2": 4, "lfo2": 4, "velocity": 5, "vel": 5,
                  "note": 6, "key": 6, "pitch bend": 7, "pitchbend": 7, "pressure": 8,
                  "aftertouch": 8, "mod wheel": 9, "modwheel": 9, "random": 10}


def _check(device):
    if _text(getattr(device, "class_name", u"")) != CLASS_NAME:
        raise ValueError(u"'%s' is not a Wavetable" % _text(device.name))


def _get(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _name(items, i):
    try:
        return items[int(i)]
    except (TypeError, ValueError, IndexError):
        return i


def _choice(items, value, what):
    """Index of `value` (a name, case-insensitive, or an index) in `items`."""
    if isinstance(value, bool):
        raise ValueError(u"%s: give a name or index" % what)
    if isinstance(value, (int, float)):
        i = int(value)
        if not 0 <= i < len(items):
            raise ValueError(u"%s: index %d out of range (0..%d)" % (what, i, len(items) - 1))
        return i
    low = _text(value).strip().lower()
    names = [_text(n) for n in items]
    for i, n in enumerate(names):
        if n.lower() == low:
            return i
    hits = [i for i, n in enumerate(names) if low in n.lower()]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(u"%s: %r matches %d of: %s" % (what, value, len(hits), u", ".join(names)))


def read(device):
    _check(device)
    cats = [_text(c) for c in (_get(device, "oscillator_wavetable_categories") or [])]
    out = {"categories": cats}
    for n in (1, 2):
        p = "oscillator_%d_" % n
        out["osc%d" % n] = {
            "category": _name(cats, _get(device, p + "wavetable_category")),
            "table": _name([_text(t) for t in (_get(device, p + "wavetables") or [])],
                           _get(device, p + "wavetable_index")),
            "tables": [_text(t) for t in (_get(device, p + "wavetables") or [])],
            "effect_mode": _name(EFFECT_MODES, _get(device, p + "effect_mode")),
        }
    mono = _get(device, "mono_poly")
    out["mono"] = None if mono is None else int(mono) == 0
    out["poly_voices"] = _name(POLY_VOICES, _get(device, "poly_voices"))
    out["unison"] = {"mode": _name(UNISON_MODES, _get(device, "unison_mode")),
                     "voices": _name(VOICES, _get(device, "unison_voice_count"))}
    out["filter_routing"] = _name(FILTER_ROUTINGS, _get(device, "filter_routing"))
    targets = [_text(t) for t in (_get(device, "visible_modulation_target_names") or [])]
    mods = []
    for ti, t in enumerate(targets):
        for si, s in enumerate(SOURCES):
            try:
                v = device.get_modulation_value(ti, si)
            except Exception:
                continue
            if v:
                mods.append({"target": t, "source": s, "amount": round(float(v), 3)})
    out["modulation_targets"] = targets
    out["modulation"] = mods
    out["sources"] = SOURCES
    out["api"] = sorted(a for a in dir(device) if not a.startswith("_") and any(
        k in a for k in ("oscillator", "modulation", "unison", "mono", "poly", "routing")))
    return out


def _target_index(device, name):
    targets = [_text(t) for t in (_get(device, "visible_modulation_target_names") or [])]
    low = _text(name).strip().lower()
    for i, t in enumerate(targets):
        if t.lower() == low:
            return i
    # not in the matrix yet: add the device parameter of that name
    params = [p for p in device.parameters if _text(p.name).lower() == low]
    if not params:
        raise ValueError(u"no modulation target or parameter %r (targets: %s)"
                         % (name, u", ".join(targets)))
    if not device.is_parameter_modulatable(params[0]):
        raise ValueError(u"parameter %r can't be modulated" % name)
    device.add_parameter_to_modulation_matrix(params[0])
    targets = [_text(t) for t in device.visible_modulation_target_names]
    for i, t in enumerate(targets):
        if t.lower() == low:
            return i
    raise ValueError(u"Live did not add %r to the modulation matrix" % name)


def _source_index(source):
    if isinstance(source, int) and not isinstance(source, bool):
        if 0 <= source < len(SOURCES):
            return source
    else:
        i = SOURCE_ALIASES.get(_text(source).strip().lower())
        if i is not None:
            return i
    raise ValueError(u"unknown modulation source %r (sources: %s)" % (source, u", ".join(SOURCES)))


def plan(device, settings):
    """Validate `settings` against the device; return [(what, write)] without writing."""
    _check(device)
    if not isinstance(settings, dict) or not settings:
        raise ValueError(u"settings must be a non-empty object")
    known = {"osc1", "osc2", "mono", "poly_voices", "unison", "filter_routing", "modulation"}
    extra = set(settings) - known
    if extra:
        raise ValueError(u"unknown settings: %s (have: %s)" % (u", ".join(sorted(extra)),
                                                              u", ".join(sorted(known))))
    steps = []

    def step(what, attr, value):
        steps.append((what, lambda: setattr(device, attr, value)))

    cats = [_text(c) for c in (_get(device, "oscillator_wavetable_categories") or [])]
    for n in (1, 2):
        spec = settings.get("osc%d" % n)
        if not spec:
            continue
        p = "oscillator_%d_" % n
        if "category" in spec:
            step(u"osc%d category" % n, p + "wavetable_category",
                 _choice(cats, spec["category"], u"osc%d category" % n))
        if "table" in spec:
            table = spec["table"]

            def set_table(p=p, n=n, table=table):  # the table list depends on the category
                tables = [_text(t) for t in getattr(device, p + "wavetables")]
                setattr(device, p + "wavetable_index", _choice(tables, table, u"osc%d table" % n))
            steps.append((u"osc%d table" % n, set_table))
        if "effect_mode" in spec:
            step(u"osc%d effect mode" % n, p + "effect_mode",
                 _choice(EFFECT_MODES, spec["effect_mode"], u"osc%d effect_mode" % n))
    if "mono" in settings:
        step(u"mono/poly", "mono_poly", 0 if settings["mono"] else 1)
    if "poly_voices" in settings:
        step(u"poly voices", "poly_voices",
             _choice([_text(v) for v in POLY_VOICES], _text(settings["poly_voices"]), u"poly_voices"))
    uni = settings.get("unison") or {}
    if "mode" in uni:
        step(u"unison mode", "unison_mode", _choice(UNISON_MODES, uni["mode"], u"unison mode"))
    if "voices" in uni:
        step(u"unison voices", "unison_voice_count",
             _choice([_text(v) for v in VOICES], _text(uni["voices"]), u"unison voices"))
    if "filter_routing" in settings:
        step(u"filter routing", "filter_routing",
             _choice(FILTER_ROUTINGS, settings["filter_routing"], u"filter_routing"))
    for m in settings.get("modulation") or []:
        try:
            target, amount = m["target"], float(m["amount"])
            si = _source_index(m["source"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(u"modulation entry %r: needs target, source and amount (%s)"
                             % (m, _text(e)))
        if not -1.0 <= amount <= 1.0:
            raise ValueError(u"modulation amount must be in -1..1, got %s" % amount)

        def set_mod(target=target, si=si, amount=amount):
            device.set_modulation_value(_target_index(device, target), si, amount)
        steps.append((u"mod %s -> %s" % (SOURCES[si], _text(target)), set_mod))
    return steps


def apply(song, device, settings):
    """Write the settings in one undo step; return {applied, total, error?, state}."""
    steps = plan(device, settings)
    done, error = [], None
    song.begin_undo_step()
    try:
        for what, write in steps:
            try:
                write()
            except Exception as e:
                error = u"%s: %s" % (what, _text(e))
                break
            done.append(what)
    finally:
        song.end_undo_step()
    out = {"applied": len(done), "total": len(steps), "changes": done, "state": read(device)}
    if error:
        out["error"] = error
    return out
