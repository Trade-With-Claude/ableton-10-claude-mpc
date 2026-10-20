# -*- coding: utf-8 -*-
"""Write operations: validate a batch, then apply it as one Live undo step.

Pure Python 2.7 / 3 compatible, no Live imports (like lom.py). Loading stock
effects needs the browser, so it goes through an injected `loader` with:
  loader.check(name)                  -> raise LookupError if not a stock effect
  loader.load(track, name, position)  -> load it, return the new device

Ops (tracks addressed by kind/index, never by name):
  {"op": "mixer", "kind", "index", "volume_db"|"volume", "pan", "sends": {ret: dB}, "mute", "solo"}
  {"op": "param", "kind", "index", "path", "param": name|index, "value"|"display"}
  {"op": "load_effect", "kind", "index", "name", "position": None (end) | n,
   "chain": [rack path..., chain_idx] (optional: load inside that rack chain)}
  {"op": "delete_device", "kind", "index", "path"}
  {"op": "chain_mixer", "kind", "index", "chain": [rack path..., chain_idx],
   "volume_db"|"volume", "pan", "mute", "solo"}
"""
from __future__ import absolute_import

import re

try:
    from . import lom
except (ImportError, ValueError):  # tests import it as a top-level module
    import lom

_text = lom._text
_NUM = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)")
_PAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([LR])\s*$", re.I)
BISECT_STEPS = 40
# Some plugins (e.g. kHs) display a typographic minus or an en dash instead of '-'.
_MINUS = {0x2212: u"-", 0x2013: u"-"}


# -- display units <-> raw values ------------------------------------------
def parse_display(s):
    """Leading number of a display string: '-12.0 dB' -12, '1.20 kHz' 1200, '25L' -25, 'C' 0."""
    s = _text(s).strip().translate(_MINUS)
    low = s.lower()
    if low.startswith(u"-inf"):
        return float("-inf")
    if low in (u"c", u"center", u"centre"):
        return 0.0
    m = _PAN.match(s)
    if m:
        n = float(m.group(1))
        return -n if m.group(2).upper() == u"L" else n
    m = _NUM.search(s)
    if not m:
        raise ValueError(u"no number in display %r" % s)
    n = float(m.group(0))
    if u"khz" in low:
        n *= 1000.0
    return n


def _clamp(param, v):
    return max(param.min, min(param.max, v))


def _bisect(param, target):
    """Raw value whose display shows `target`. Displays are rounded ('-20.0 dB'), so aim
    for the middle of the run of values showing the closest display, not its edge."""
    lo, hi = float(param.min), float(param.max)
    sign = 1.0 if parse_display(param.str_for_value(hi)) >= parse_display(param.str_for_value(lo)) else -1.0
    g = lambda v: sign * parse_display(param.str_for_value(v))  # noqa: E731  rising
    t = sign * target
    if t <= g(lo):
        return lo
    if t >= g(hi):
        return hi

    def first(pred):  # smallest v in [lo, hi] with pred(g(v)), g rising
        a, b = lo, hi
        for _ in range(BISECT_STEPS):
            mid = (a + b) / 2.0
            if pred(g(mid)):
                b = mid
            else:
                a = mid
        return b

    start = first(lambda y: y >= t)  # first value displaying >= target
    shown = g(start)
    prev = g(start - (hi - lo) * 1e-9)  # the display step just below the target
    if abs(prev - t) < abs(shown - t):
        return (first(lambda y: y >= prev) + start) / 2.0
    return (start + first(lambda y: y > shown)) / 2.0


def value_for(param, value=None, display=None):
    """Raw value to write: `value` is raw (clamped); `display` is in display units
    (number, '-inf', '25L', an item name for quantized params, 'on'/'off')."""
    if value is None and display is None:
        raise ValueError(u"give value or display for '%s'" % _text(param.name))
    if value is not None:
        return _clamp(param, float(value))
    items = []
    if param.is_quantized:
        items = [_text(i) for i in getattr(param, "value_items", [])]
    if items:
        return float(param.min) + _item_index(param, items, display)
    if isinstance(display, bool):
        return param.max if display else param.min
    target = float(display) if isinstance(display, (int, float)) else parse_display(display)
    return _bisect(param, target)


def _item_index(param, items, display):
    """Quantized params: match an item by name ('High pass'), number ('4' or 4) or on/off."""
    if isinstance(display, bool):
        display = u"on" if display else u"off"
    want = _text(display).strip().lower()
    for i, item in enumerate(items):
        if item.lower() == want:
            return i
    if isinstance(display, (int, float)):
        for i, item in enumerate(items):
            try:
                if parse_display(item) == float(display):
                    return i
            except ValueError:
                pass
    if len(items) == 2 and want in (u"on", u"off", u"true", u"false", u"1", u"0"):
        return 1 if want in (u"on", u"true", u"1") else 0
    raise ValueError(u"'%s' has no item %r (items: %s); use value=<index> for a raw index"
                     % (_text(param.name), display, u", ".join(items)))


def find_param(device, key):
    params = list(device.parameters)
    if isinstance(key, int) or _text(key).strip().isdigit():
        i = int(key)
        if not 0 <= i < len(params):
            raise LookupError(u"no param %d in '%s' (have %d)" % (i, _text(device.name), len(params)))
        return params[i]
    want = _text(key).strip().lower()
    names = [_text(p.name) for p in params]
    exact = [p for p, n in zip(params, names) if n.lower() == want]
    if len(exact) == 1:
        return exact[0]
    subs = [(p, n) for p, n in zip(params, names) if want in n.lower()]
    if len(exact) > 1 or len(subs) > 1:
        cands = [n for p, n in subs] or [n for n in names if n.lower() == want]
        raise LookupError(u"param '%s' is ambiguous in '%s': %s"
                          % (_text(key), _text(device.name), u", ".join(cands)))
    if not subs:
        raise LookupError(u"no param '%s' in '%s' (params: %s)"
                          % (_text(key), _text(device.name), u", ".join(names)))
    return subs[0][0]


# -- device insertion --------------------------------------------------------------
def insert_plan(devices, position):
    """Where Live's browser should insert into `devices` (a track's or a chain's):
    (index of the device to select | None, insert mode name). `position` None = end."""
    n = len(devices)
    if not n:
        return None, "default"
    if position is None or position >= n:
        return n - 1, "selected_right"
    if position == 0:
        return 0, "selected_left"
    return position - 1, "selected_right"


# -- planning -------------------------------------------------------------------
def _label(kind, index, track):
    if kind == "master":
        return u"master"
    return u"%s %d '%s'" % (kind, int(index), _text(track.name))


def _param_change(what, param, raw):
    """(what, read_display, write) for a parameter write, validated now."""
    if not getattr(param, "is_enabled", True):
        raise ValueError(u"'%s' is disabled (automated or locked)" % what)

    def write():
        param.value = raw
    return (what, lambda: lom._display(param), write)


def _attr_change(what, obj, attr, val):
    def write():
        setattr(obj, attr, bool(val))
    return (what, lambda: u"on" if getattr(obj, attr) else u"off", write)


def _send_index(key, return_names):
    k = _text(key).strip()
    if k.isdigit():
        i = int(k)
    else:
        low = k.lower()
        hits = [i for i, n in enumerate(return_names)
                if n.lower() == low or (len(low) == 1 and n.lower().startswith(low))]
        if len(hits) != 1:
            raise LookupError(u"send '%s' matches %d returns (have: %s)"
                              % (k, len(hits), u", ".join(return_names)))
        i = hits[0]
    if not 0 <= i < len(return_names):
        raise LookupError(u"no send %d (have %d)" % (i, len(return_names)))
    return i


def _plan_mixer(song, op, kind, track):
    mixer = track.mixer_device
    changes = []
    if "volume" in op or "volume_db" in op:
        changes.append(_param_change(u"volume", mixer.volume,
                                     value_for(mixer.volume, op.get("volume"), op.get("volume_db"))))
    if "pan" in op:
        pan = op["pan"]
        # numbers are in Live's display units (-50 = 50L .. 50 = 50R)
        changes.append(_param_change(u"pan", mixer.panning, value_for(mixer.panning, display=pan)))
    sends = op.get("sends") or {}
    if sends and kind == "master":
        raise ValueError(u"master has no sends")
    return_names = [_text(r.name) for r in song.return_tracks]
    for key in sorted(sends, key=_text):
        i = _send_index(key, return_names)
        param = list(mixer.sends)[i]
        changes.append(_param_change(u"send %s" % return_names[i], param,
                                     value_for(param, display=sends[key])))
    for attr in ("mute", "solo"):
        if attr in op:
            if kind == "master":
                raise ValueError(u"master has no %s" % attr)
            changes.append(_attr_change(attr, track, attr, op[attr]))
    if not changes:
        raise ValueError(u"mixer op changes nothing (give volume_db, pan, sends, mute or solo)")
    return changes


def _plan_param(op, track):
    device = lom.resolve_device(track, op.get("path"))
    param = find_param(device, op.get("param"))
    raw = value_for(param, op.get("value"), op.get("display"))
    return [_param_change(u"%s: %s" % (_text(device.name), _text(param.name)), param, raw)]


def _container(track, path):
    """(object with .devices/.delete_device, device) for a device path."""
    path = [int(i) for i in (path if isinstance(path, list) else [path])]
    device = lom.resolve_device(track, path)
    if len(path) == 1:
        return track, device
    rack = lom.resolve_device(track, path[:-2])
    return list(rack.chains)[path[-2]], device


def _plan_delete(op, track):
    holder, device = _container(track, op.get("path"))
    name = _text(device.name)

    def write():
        devices = list(holder.devices)
        for i, d in enumerate(devices):  # indices may have shifted earlier in the batch
            if d == device:
                holder.delete_device(i)
                return
        raise LookupError(u"device '%s' no longer exists" % name)
    return [(u"delete %s" % name, lambda: name if device in list(holder.devices) else u"(deleted)", write)]


def _plan_load(op, track, loader):
    name = _text(op.get("name") or u"").strip()
    if not name:
        raise ValueError(u"load_effect needs a stock effect name")
    loader.check(name)
    chain_path = op.get("chain")
    chain = None
    holder = track
    if chain_path is not None:
        chain = holder = lom.resolve_chain(track, chain_path)
        if not list(chain.devices):
            raise ValueError(u"can't load into an empty chain yet: add any device to chain '%s' first"
                             % _text(chain.name))
    position = op.get("position")
    if position is not None:
        position = int(position)
        if not 0 <= position <= len(list(holder.devices)):
            raise LookupError(u"position %d out of range (0..%d)" % (position, len(list(holder.devices))))
    loaded = []

    def write():
        if chain is None:
            loaded.append(loader.load(track, name, position))
        else:
            loaded.append(loader.load(track, name, position, chain=chain))

    def read():
        if not loaded:
            return u"-"
        devices = list(holder.devices)
        idx = [i for i, d in enumerate(devices) if d == loaded[0]]
        where = u"[%s]" % (idx[0] if idx else u"?")
        if chain is not None:
            where = u"chain '%s' %s" % (_text(chain.name), where)
        return u"%s at %s" % (_text(loaded[0].name), where)
    return [(u"load %s" % name, read, write)]


def _plan_chain_mixer(op, track):
    chain_path = op.get("chain")
    if chain_path is None:
        raise ValueError(u"chain_mixer needs \"chain\": [rack path..., chain index]")
    chain = lom.resolve_chain(track, chain_path)
    label = u"chain '%s'" % _text(chain.name)
    mixer = getattr(chain, "mixer_device", None)
    changes = []
    if "volume" in op or "volume_db" in op or "pan" in op:
        if mixer is None:
            raise ValueError(u"%s has no mixer" % label)
        if "volume" in op or "volume_db" in op:
            changes.append(_param_change(u"%s volume" % label, mixer.volume,
                                         value_for(mixer.volume, op.get("volume"), op.get("volume_db"))))
        if "pan" in op:
            changes.append(_param_change(u"%s pan" % label, mixer.panning,
                                         value_for(mixer.panning, display=op["pan"])))
    for attr in ("mute", "solo"):
        if attr in op:
            changes.append(_attr_change(u"%s %s" % (label, attr), chain, attr, op[attr]))
    if not changes:
        raise ValueError(u"chain_mixer op changes nothing (give volume_db, pan, mute or solo)")
    return changes


def plan(song, ops, loader=None):
    """Resolve and validate every op without writing. Returns [(op_name, target, changes)]."""
    if not isinstance(ops, list) or not ops:
        raise ValueError(u"ops must be a non-empty list")
    planned = []
    for n, op in enumerate(ops):
        try:
            kind = op.get("kind")
            index = op.get("index", 0)
            track = lom.resolve_track(song, kind, index)
            name = op.get("op")
            if name == "mixer":
                changes = _plan_mixer(song, op, kind, track)
            elif name == "param":
                changes = _plan_param(op, track)
            elif name == "load_effect":
                if loader is None:
                    raise ValueError(u"no effect loader available")
                changes = _plan_load(op, track, loader)
            elif name == "delete_device":
                changes = _plan_delete(op, track)
            elif name == "chain_mixer":
                changes = _plan_chain_mixer(op, track)
            else:
                raise ValueError(u"unknown op %r (mixer|param|load_effect|delete_device|chain_mixer)"
                                 % (name,))
        except Exception as e:
            raise ValueError(u"op %d: %s" % (n, _text(e)))
        planned.append((name, _label(kind, index, track), changes))
    return planned


def apply(song, ops, loader=None):
    """Validate all ops, then apply them inside one Live undo step."""
    planned = plan(song, ops, loader)
    results = []
    total = sum(len(c) for _, _, c in planned)
    applied = 0
    error = None
    song.begin_undo_step()
    try:
        for name, target, changes in planned:
            entry = {"op": name, "target": target, "changes": []}
            results.append(entry)
            for what, read, write in changes:
                before = read()
                try:
                    write()
                except Exception as e:
                    error = u"%s %s: %s" % (target, what, _text(e))
                    break
                applied += 1
                entry["changes"].append({"what": what, "before": before, "after": read()})
            if error:
                break
    finally:
        song.end_undo_step()
    out = {"applied": applied, "total": total, "results": results}
    if error:
        out["error"] = error
    return out
