# -*- coding: utf-8 -*-
"""Live Object Model addressing + serializers.

Pure Python 2.7 / 3 compatible, no Live imports: it only touches LOM objects
passed in, so it can be unit-tested outside Live with duck-typed fakes.

Addressing:
  track   {"kind": "track|return|master", "index": n}   (index ignored for master)
  device  path = [dev] or [rack, chain, dev, chain, dev, ...] inside that track
"""
from __future__ import absolute_import

try:
    text_type = unicode  # noqa: F821  (py2: Live 10)
except NameError:  # py3: tests
    text_type = str

MAX_RACK_DEPTH = 4
KINDS = ("track", "return", "master")
_DEVICE_TYPES = {1: "instrument", 2: "audio_effect", 4: "midi_effect"}
_PLUGIN_CLASSES = ("PluginDevice", "AuPluginDevice")


def _text(x):
    if isinstance(x, text_type):
        return x
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    try:
        return text_type(x)
    except Exception:
        return text_type(repr(x))


def _ptr(obj):
    return getattr(obj, "_live_ptr", None) or id(obj)


# -- addressing ---------------------------------------------------------------
def resolve_track(song, kind, index=0):
    if kind == "master":
        return song.master_track
    if kind == "track":
        seq, label = list(song.tracks), u"track"
    elif kind == "return":
        seq, label = list(song.return_tracks), u"return track"
    else:
        raise ValueError(u"kind must be one of %s, got %r" % (u"|".join(KINDS), kind))
    try:
        i = int(index)
    except (TypeError, ValueError):
        raise ValueError(u"index must be an integer, got %r" % (index,))
    if not 0 <= i < len(seq):
        raise LookupError(u"no %s %d (have %d)" % (label, i, len(seq)))
    return seq[i]


def resolve_device(track, path):
    if isinstance(path, int):
        path = [path]
    path = list(path or [])
    if not path or len(path) % 2 == 0:
        raise ValueError(u"device path must be [dev] or [rack, chain, dev, ...], got %r" % (path,))
    devices = list(track.devices)
    where = u"track"
    device = None
    for depth, i in enumerate(path):
        i = int(i)
        if depth % 2 == 0:
            if not 0 <= i < len(devices):
                raise LookupError(u"no device %d in %s (have %d)" % (i, where, len(devices)))
            device = devices[i]
            where = u"device '%s'" % _text(device.name)
        else:
            if not getattr(device, "can_have_chains", False):
                raise LookupError(u"%s is not a rack (no chains)" % where)
            chains = list(device.chains)
            if not 0 <= i < len(chains):
                raise LookupError(u"no chain %d in %s (have %d)" % (i, where, len(chains)))
            devices = list(chains[i].devices)
            where = u"chain '%s'" % _text(chains[i].name)
    return device


# -- values -------------------------------------------------------------------
def _display(param, value=None):
    try:
        return _text(param.str_for_value(param.value if value is None else value))
    except Exception:
        return _text(param)


def _param_value(param):
    return {"value": param.value, "display": _display(param)}


def _color(obj):
    try:
        return u"#%06X" % (int(obj.color) & 0xFFFFFF)
    except Exception:
        return None


def _output(track):
    try:
        return _text(track.output_routing_type.display_name)
    except Exception:
        try:
            return _text(track.current_output_routing)
        except Exception:
            return None


# -- devices ------------------------------------------------------------------
def _device_on(device):
    params = list(device.parameters)
    if params and _text(params[0].name) == u"Device On":
        return bool(params[0].value)
    return bool(getattr(device, "is_active", True))


def serialize_device(device, path, depth=0):
    class_name = _text(device.class_name)
    out = {
        "path": list(path),
        "name": _text(device.name),
        "class_name": class_name,
        "type": _DEVICE_TYPES.get(int(getattr(device, "type", 0) or 0), "undefined"),
        "is_plugin": class_name in _PLUGIN_CLASSES,
        "on": _device_on(device),
        "n_params": len(list(device.parameters)),
    }
    if getattr(device, "can_have_chains", False):
        if depth >= MAX_RACK_DEPTH:
            out["chains_truncated"] = True
        else:
            out["chains"] = [
                {
                    "index": ci,
                    "name": _text(chain.name),
                    "mute": bool(getattr(chain, "mute", False)),
                    "solo": bool(getattr(chain, "solo", False)),
                    "devices": [
                        serialize_device(d, list(path) + [ci, di], depth + 1)
                        for di, d in enumerate(chain.devices)
                    ],
                }
                for ci, chain in enumerate(device.chains)
            ]
    return out


def serialize_params(device, query=None):
    q = _text(query).lower() if query else None
    out = []
    for i, p in enumerate(device.parameters):
        name = _text(p.name)
        if q and q not in name.lower():
            continue
        item = {
            "index": i,
            "name": name,
            "value": p.value,
            "min": p.min,
            "max": p.max,
            "is_quantized": bool(p.is_quantized),
            "display": _display(p),
            "is_enabled": bool(getattr(p, "is_enabled", True)),
        }
        if p.is_quantized:
            try:
                item["value_items"] = [_text(v) for v in p.value_items]
            except Exception:
                pass
        out.append(item)
    return out


# -- tracks / session ---------------------------------------------------------
def _track_kind(track):
    if getattr(track, "is_foldable", False):
        return "group"
    return "midi" if getattr(track, "has_midi_input", False) else "audio"


def serialize_track(track, kind, index, return_names, group_index_of=None):
    mixer = track.mixer_device
    out = {
        "kind": kind,
        "index": index,
        "name": _text(track.name),
        "color": _color(track),
        "volume": _param_value(mixer.volume),
        "pan": _param_value(mixer.panning),
        "devices": [serialize_device(d, [i]) for i, d in enumerate(track.devices)],
    }
    if kind == "master":
        return out
    out["mute"] = bool(track.mute)
    out["solo"] = bool(track.solo)
    out["output"] = _output(track)
    out["sends"] = [
        {"return": return_names[i] if i < len(return_names) else None,
         "value": s.value, "display": _display(s)}
        for i, s in enumerate(mixer.sends)
    ]
    if kind == "track":
        out["type"] = _track_kind(track)
        out["is_foldable"] = bool(getattr(track, "is_foldable", False))
        if out["is_foldable"]:
            out["fold_state"] = bool(track.fold_state)
        if getattr(track, "can_be_armed", False):
            out["arm"] = bool(track.arm)
        group = getattr(track, "group_track", None)
        out["group_index"] = group_index_of(group) if (group is not None and group_index_of) else None
    return out


def serialize_session(song):
    tracks = list(song.tracks)
    returns = list(song.return_tracks)
    return_names = [_text(r.name) for r in returns]
    by_ptr = dict((_ptr(t), i) for i, t in enumerate(tracks))

    def group_index_of(group):
        i = by_ptr.get(_ptr(group))
        if i is None:  # wrapper objects may differ: fall back to LOM equality
            for j, t in enumerate(tracks):
                if t == group:
                    return j
        return i

    return {
        "tempo": song.tempo,
        "tracks": [serialize_track(t, "track", i, return_names, group_index_of)
                   for i, t in enumerate(tracks)],
        "returns": [serialize_track(t, "return", i, return_names)
                    for i, t in enumerate(returns)],
        "master": serialize_track(song.master_track, "master", 0, return_names),
    }


def read_meters(song):
    out = []
    groups = (("track", list(song.tracks)), ("return", list(song.return_tracks)),
              ("master", [song.master_track]))
    for kind, seq in groups:
        for i, t in enumerate(seq):
            if not getattr(t, "has_audio_output", True):
                continue
            try:
                left, right = t.output_meter_left, t.output_meter_right
            except Exception:
                continue
            out.append({"kind": kind, "index": i, "name": _text(t.name),
                        "left": left, "right": right})
    return out
