"""build.py: a new MIDI track with a stock instrument and a clip, in one undo step."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"))
import build  # noqa: E402

from fake_lom import FakeLoader, dnb_song  # noqa: E402

CLIP = {"length_beats": 16, "name": "lead",
        "notes": [{"pitch": 70, "start_beat": 0, "length_beats": 0.75, "velocity": 115},
                  {"pitch": 78, "start_beat": 1.5, "length_beats": 0.75},
                  {"pitch": 85, "start_beat": 3, "length_beats": 0.75, "velocity": 300}]}


@pytest.fixture
def song():
    return dnb_song()


@pytest.fixture
def loader():
    return FakeLoader()


def test_builds_track_at_the_end(song, loader):
    user = song.tracks[2]
    song.view.selected_track = user
    r = build.create_instrument_track(song, loader, "Lead copy", "Analog", clip=CLIP)
    assert r["track_index"] == 5 and r["track"] == "Lead copy"
    assert r["device"] == {"name": "Analog", "path": [0]}
    assert r["clip"] == {"slot": 0, "name": "lead", "length_beats": 16.0, "notes": 3}
    t = song.tracks[5]
    assert t.has_midi_input and [d.class_name for d in t.devices] == ["UltraAnalog"]
    clip = t.clip_slots[0].clip
    assert clip.length == 16.0 and clip.name == "lead"
    assert clip.notes == ((70, 0.0, 0.75, 115.0, False), (78, 1.5, 0.75, 100.0, False),
                          (85, 3.0, 0.75, 127.0, False))  # velocity default 100, clamped to 127
    assert (song.undo_begins, song.undo_ends) == (1, 1)
    assert song.view.selected_track is user  # the user's selection is back


def test_builds_at_index_without_clip(song, loader):
    r = build.create_instrument_track(song, loader, "Bass", "operator", index=1)
    assert r["track_index"] == 1 and r["clip"] is None
    assert song.tracks[1].name == "Bass" and song.tracks[2].name == "Kick"


@pytest.mark.parametrize("kw,msg", [
    (dict(instrument="Serum"), "instrument not found"),
    (dict(name=""), "track name"),
    (dict(index=9), "out of range"),
    (dict(clip={"length_beats": 0, "notes": []}), "length_beats"),
    (dict(clip={"length_beats": 4, "notes": [{"pitch": 200, "start_beat": 0, "length_beats": 1}]}),
     "out of 0..127"),
    (dict(clip={"length_beats": 4, "notes": [{"pitch": 60, "start_beat": 4, "length_beats": 1}]}),
     "after the clip's end"),
    (dict(clip={"length_beats": 4, "notes": [{"pitch": 60, "length_beats": 1}]}), "needs numeric"),
])
def test_invalid_requests_change_nothing(song, loader, kw, msg):
    args = dict(name="Lead", instrument="Analog", clip=CLIP)
    args.update(kw)
    with pytest.raises((ValueError, LookupError), match=msg):
        build.create_instrument_track(song, loader, **args)
    assert len(song.tracks) == 5 and song.undo_begins == 0 and loader.loads == []


def test_failed_load_removes_the_new_track(song):
    with pytest.raises(RuntimeError, match="exploded"):
        build.create_instrument_track(song, FakeLoader(fail=True), "Lead", "Analog", clip=CLIP)
    assert len(song.tracks) == 5 and (song.undo_begins, song.undo_ends) == (1, 1)
