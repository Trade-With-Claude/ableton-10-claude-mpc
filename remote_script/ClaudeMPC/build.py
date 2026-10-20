# -*- coding: utf-8 -*-
"""Build a new instrument track: MIDI track + stock instrument + a session clip of notes.

Pure Python 2.7 / 3 compatible, no Live imports (like lom.py and ops.py). Loading the
instrument goes through an injected `loader` with:
  loader.check_instrument(name)          -> raise LookupError if not a stock instrument
  loader.load_instrument(track, name)    -> load it onto the (empty) track, return the device

clip = {"length_beats": 16, "name": "lead",
        "notes": [{"pitch": 70, "start_beat": 0, "length_beats": 0.75, "velocity": 110}, ...]}
"""
from __future__ import absolute_import

try:
    from . import lom
except (ImportError, ValueError):  # tests import it as a top-level module
    import lom

_text = lom._text
MAX_CLIP_BEATS = 1024.0
MAX_NOTES = 2000


def clean_notes(clip):
    """Validate a clip spec; return (length, name, notes as Live's set_notes tuples)."""
    if not isinstance(clip, dict):
        raise ValueError(u"clip must be an object with length_beats and notes")
    try:
        length = float(clip.get("length_beats"))
    except (TypeError, ValueError):
        raise ValueError(u"clip needs a numeric length_beats")
    if not 0 < length <= MAX_CLIP_BEATS:
        raise ValueError(u"clip length_beats must be in (0, %d], got %s" % (MAX_CLIP_BEATS, length))
    notes = clip.get("notes") or []
    if not isinstance(notes, list) or len(notes) > MAX_NOTES:
        raise ValueError(u"clip notes must be a list of at most %d notes" % MAX_NOTES)
    out = []
    for n, note in enumerate(notes):
        where = u"note %d" % n
        try:
            pitch = int(note["pitch"])
            start = float(note["start_beat"])
            dur = float(note["length_beats"])
            vel = float(note.get("velocity", 100))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError(u"%s needs numeric pitch, start_beat, length_beats" % where)
        if not 0 <= pitch <= 127:
            raise ValueError(u"%s: pitch %d out of 0..127" % (where, pitch))
        if start < 0 or dur <= 0:
            raise ValueError(u"%s: needs start_beat >= 0 and length_beats > 0" % where)
        if start >= length:
            raise ValueError(u"%s starts at beat %s, after the clip's end (%s)" % (where, start, length))
        out.append((pitch, start, dur, max(1.0, min(127.0, vel)), False))
    return length, _text(clip.get("name") or u""), tuple(out)


def create_instrument_track(song, loader, name, instrument, index=None, clip=None):
    """Validate everything, then create, name, load and fill the track in one undo step."""
    name = _text(name or u"").strip()
    instrument = _text(instrument or u"").strip()
    if not name or not instrument:
        raise ValueError(u"give a track name and a stock instrument (Operator, Analog, Wavetable...)")
    loader.check_instrument(instrument)
    n_tracks = len(list(song.tracks))
    if index is None:
        index = n_tracks
    index = int(index)
    if not 0 <= index <= n_tracks:
        raise LookupError(u"index %d out of range (0..%d)" % (index, n_tracks))
    spec = clean_notes(clip) if clip is not None else None

    prev = song.view.selected_track
    song.begin_undo_step()
    created = False
    try:
        song.create_midi_track(-1 if index == n_tracks else index)
        created = True
        track = list(song.tracks)[index]
        track.name = name
        device = loader.load_instrument(track, instrument)
        out = {"track_index": index, "track": _text(track.name),
               "device": {"name": _text(device.name), "path": [0]}, "clip": None}
        if spec is not None:
            length, clip_name, notes = spec
            slot = list(track.clip_slots)[0]
            slot.create_clip(length)
            c = slot.clip
            if clip_name:
                c.name = clip_name
            c.set_notes(notes)
            out["clip"] = {"slot": 0, "name": _text(c.name), "length_beats": length,
                           "notes": len(notes)}
    except Exception:
        if created:  # don't leave a half-built track behind
            try:
                song.delete_track(index)
            except Exception:
                pass
        raise
    finally:
        song.end_undo_step()
        try:
            if prev is not None:
                song.view.selected_track = prev
        except Exception:
            pass
    return out
