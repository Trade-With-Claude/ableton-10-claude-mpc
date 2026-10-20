# -*- coding: utf-8 -*-
"""Automation curves: segments in bars -> a raw parameter value at any beat.

Pure Python 2.7 / 3 compatible, no Live imports (like lom.py and ops.py).

A lane is a list of segments (bars are 1-based, 4/4):
  {"from_bar": 9, "to_bar": 25, "shape": "exp", "start": 300, "end": "12 kHz"}
  {"from_bar": 25, "to_bar": 27, "shape": "sine", "start": 800, "end": 3000, "rate": "1/2"}
  {"from_bar": 27, "to_bar": 29, "shape": "steps", "values": [-12, -6, 0, -6], "rate": "1/4"}
Shapes: ramp (linear), exp (slow start, fast end), log (fast start, slow end), hold (start),
sine / triangle / square (LFO between start and end, one cycle per `rate` bars, starting
at start), steps (`values`, one per `rate` bars). Endpoints are in display units and are
converted to raw once; interpolation runs in raw space (Auto Filter frequency's raw scale
is already logarithmic, so a ramp sounds even). Before the first segment the lane holds
its first value, after a segment its last one.
"""
from __future__ import absolute_import, division

import math

try:
    from . import lom
    from . import ops
except (ImportError, ValueError):  # tests import it as a top-level module
    import lom
    import ops

_text = lom._text
BEATS_PER_BAR = 4
TICK_S = 0.1  # update_display() runs at ~10 Hz
MIN_PERIOD_TICKS = 4  # an LFO cycle needs at least this many ticks to be drawn
MIN_STEP_TICKS = 2
RAMPS = ("ramp", "exp", "log")
LFOS = ("sine", "triangle", "square")
SHAPES = RAMPS + ("hold",) + LFOS + ("steps",)


def bar_to_beat(bar):
    return (float(bar) - 1.0) * BEATS_PER_BAR


def parse_rate(rate):
    """Length in bars: 2, 0.5, "1/2", "2", "1/4 bar"."""
    if isinstance(rate, (int, float)) and not isinstance(rate, bool):
        bars = float(rate)
    else:
        s = _text(rate).strip().lower().replace(u"bars", u"").replace(u"bar", u"").strip()
        try:
            if u"/" in s:
                num, den = s.split(u"/", 1)
                bars = float(num) / float(den)
            else:
                bars = float(s)
        except (ValueError, ZeroDivisionError):
            raise ValueError(u"rate must be bars like 1, 2 or '1/2', got %r" % (rate,))
    if bars <= 0:
        raise ValueError(u"rate must be > 0 bars, got %r" % (rate,))
    return bars


def _raw(param, display):
    if display is None:
        raise ValueError(u"missing value")
    return ops.value_for(param, display=display)


def _compile_segment(param, seg, n, tempo, tick_s):
    where = u"segment %d" % n
    try:
        b0, b1 = float(seg["from_bar"]), float(seg["to_bar"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(u"%s: needs numeric from_bar and to_bar" % where)
    if b0 < 1:
        raise ValueError(u"%s: from_bar must be >= 1" % where)
    if b1 <= b0:
        raise ValueError(u"%s: to_bar (%s) must be after from_bar (%s)" % (where, b1, b0))
    shape = _text(seg.get("shape", "ramp")).strip().lower()
    if shape not in SHAPES:
        raise ValueError(u"%s: unknown shape %r (shapes: %s)" % (where, shape, u", ".join(SHAPES)))
    out = {"b0": bar_to_beat(b0), "b1": bar_to_beat(b1), "shape": shape}
    beat_s = 60.0 / float(tempo)
    if shape == "steps":
        values = seg.get("values")
        if not values:
            raise ValueError(u"%s: steps need a non-empty `values` list" % where)
        out["values"] = [_raw(param, v) for v in values]
        out["period"] = parse_rate(seg.get("rate", 1)) * BEATS_PER_BAR
        if out["period"] * beat_s < MIN_STEP_TICKS * tick_s:
            raise ValueError(u"%s: steps of %s bar are too short to draw at ~%d points/s"
                             % (where, seg.get("rate"), int(round(1 / tick_s))))
        return out
    out["a"] = _raw(param, seg.get("start"))
    out["b"] = out["a"] if shape == "hold" else _raw(param, seg.get("end"))
    if shape in LFOS:
        if seg.get("rate") is None:
            raise ValueError(u"%s: %s needs a `rate` (bars per cycle, e.g. '1/2')" % (where, shape))
        out["period"] = parse_rate(seg["rate"]) * BEATS_PER_BAR
        if out["period"] * beat_s < MIN_PERIOD_TICKS * tick_s:
            raise ValueError(u"%s: a %s bar %s is too fast to draw at ~%d points/s: automate the "
                             u"device's own LFO (rate/amount) instead"
                             % (where, seg["rate"], shape, int(round(1 / tick_s))))
    return out


def compile_lane(param, segments, tempo, tick_s=TICK_S):
    """Validate a lane against `param` and convert it to raw values and beats."""
    if not segments:
        raise ValueError(u"a lane needs at least one segment")
    segs = [_compile_segment(param, s, n, tempo, tick_s) for n, s in enumerate(segments)]
    segs.sort(key=lambda s: s["b0"])
    for prev, nxt in zip(segs, segs[1:]):
        if nxt["b0"] < prev["b1"]:
            raise ValueError(u"segments overlap around bar %s" % (nxt["b0"] / BEATS_PER_BAR + 1))
    return {"lo": float(param.min), "hi": float(param.max), "segments": segs}


def _first(seg):
    return seg["values"][0] if seg["shape"] == "steps" else seg["a"]


def _last(seg):
    shape = seg["shape"]
    if shape == "steps":
        return seg["values"][-1]
    if shape in LFOS or shape == "hold":
        return seg["a"]
    return seg["b"]


def _segment_value(seg, beat):
    shape, b0 = seg["shape"], seg["b0"]
    if shape == "steps":
        i = int((beat - b0) // seg["period"])
        return seg["values"][min(i, len(seg["values"]) - 1)]
    a, b = seg["a"], seg["b"]
    if shape == "hold":
        return a
    if shape in RAMPS:
        t = (beat - b0) / (seg["b1"] - b0)
        if shape == "exp":
            t = t * t
        elif shape == "log":
            t = 1.0 - (1.0 - t) * (1.0 - t)
        return a + (b - a) * t
    phase = ((beat - b0) / seg["period"]) % 1.0
    if shape == "sine":
        w = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)
    elif shape == "triangle":
        w = 2.0 * phase if phase < 0.5 else 2.0 - 2.0 * phase
    else:  # square
        w = 0.0 if phase < 0.5 else 1.0
    return a + (b - a) * w


def value_at(lane, beat):
    """Raw value of a compiled lane at `beat` (0-based beats from the song start)."""
    segs = lane["segments"]
    if beat < segs[0]["b0"]:
        v = _first(segs[0])
    else:
        v = None
        for seg in segs:
            if seg["b0"] <= beat < seg["b1"]:
                v = _segment_value(seg, beat)
                break
            if seg["b1"] <= beat:
                v = _last(seg)
    return max(lane["lo"], min(lane["hi"], v))
