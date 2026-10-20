"""lom.py serializers + addressing against a fake Live Object Model."""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"))
import lom  # noqa: E402

from fake_lom import dnb_song  # noqa: E402


@pytest.fixture
def song():
    return dnb_song()


@pytest.fixture
def session(song):
    return lom.serialize_session(song)


def test_group_hierarchy(session):
    drums, kick, snare, bass, _ = session["tracks"]
    assert drums["type"] == "group" and drums["is_foldable"] and drums["fold_state"] is False
    assert drums["group_index"] is None
    assert kick["group_index"] == 0 and snare["group_index"] == 0
    assert bass["group_index"] is None and bass["type"] == "midi"
    assert kick["output"] == "DRUMS"
    assert "arm" not in drums and kick["arm"] is False


def test_mixer_and_sends(session):
    snare = session["tracks"][2]
    assert snare["volume"] == {"value": 0.85, "display": "0.0 dB"}
    assert [s["return"] for s in snare["sends"]] == ["A-Reverb", "B-Delay"]
    assert snare["sends"][0]["display"] == "-12.0 dB"
    assert [r["name"] for r in session["returns"]] == ["A-Reverb", "B-Delay"]


def test_master_shape(session):
    m = session["master"]
    assert m["kind"] == "master" and m["devices"][0]["name"] == "Limiter"
    assert not {"mute", "solo", "sends", "group_index"} & set(m)


def test_devices_and_racks(session):
    bass = session["tracks"][3]
    serum, rack = bass["devices"]
    assert serum["is_plugin"] and serum["type"] == "instrument" and serum["on"] is True
    assert rack["path"] == [1] and [c["name"] for c in rack["chains"]] == ["Sub", "Mid"]
    inner = rack["chains"][1]["devices"][1]
    assert inner["path"] == [1, 1, 1]
    assert inner["chains"][0]["devices"][0]["path"] == [1, 1, 1, 0, 0]


def test_resolve_nested_device(song):
    track = lom.resolve_track(song, "track", 3)
    assert lom.resolve_device(track, [1, 1, 1, 0, 0]).name == "Utility"
    assert lom.resolve_device(track, 0).name == "Serum"


def test_params(song):
    glue = lom.resolve_device(lom.resolve_track(song, "track", 0), [0])
    params = lom.serialize_params(glue)
    assert [p["name"] for p in params][:3] == ["Device On", "Threshold", "Ratio"]
    thr, ratio = params[1], params[2]
    assert thr["display"] == "-12.0 dB" and (thr["min"], thr["max"]) == (-40.0, 0.0)
    assert ratio["is_quantized"] and ratio["value_items"] == ["2", "4", "10"]
    assert ratio["display"] == "4"
    assert [p["name"] for p in lom.serialize_params(glue, query="THRESH")] == ["Threshold"]


def test_meters(song):
    meters = lom.read_meters(song)
    names = [m["name"] for m in meters]
    assert "MIDI only" not in names
    assert meters[-1] == {"kind": "master", "index": 0, "name": "Master", "left": 0.9, "right": 0.95}
    assert {"track", "return", "master"} == {m["kind"] for m in meters}


def test_unicode_roundtrip(session):
    wire = json.dumps(session).encode("utf-8")
    back = json.loads(wire.decode("utf-8"))
    assert back["tracks"][3]["name"] == "Bässe ✦ Sub"


@pytest.mark.parametrize("kind,index,path,msg", [
    ("return", 5, None, "no return track 5 (have 2)"),
    ("track", 9, None, "no track 9 (have 5)"),
    ("bus", 0, None, "kind must be one of"),
    ("track", 3, [7], "no device 7 in track (have 2)"),
    ("track", 3, [0, 0, 0], "is not a rack"),
    ("track", 3, [1, 4, 0], "no chain 4 in device 'Bass Rack' (have 2)"),
    ("track", 3, [1, 0], "device path must be"),
])
def test_bad_addresses(song, kind, index, path, msg):
    with pytest.raises((LookupError, ValueError), match=msg.replace("(", r"\(").replace(")", r"\)")):
        track = lom.resolve_track(song, kind, index)
        lom.resolve_device(track, path)


# -- Phase 5: chain mixer, chain addressing, fold restore -----------------------
def test_chains_carry_volume_and_pan():
    s = lom.serialize_session(dnb_song())
    sub = s["tracks"][3]["devices"][1]["chains"][0]
    assert sub["volume"]["display"] == "-3.0 dB" and sub["pan"]["display"] == "C"


def test_chain_without_mixer_omits_volume():
    song = dnb_song()
    del song.tracks[3].devices[1].chains[0].mixer_device
    sub = lom.serialize_session(song)["tracks"][3]["devices"][1]["chains"][0]
    assert "volume" not in sub and "pan" not in sub and sub["devices"]


def test_resolve_chain_nested():
    song = dnb_song()
    assert lom.resolve_chain(song.tracks[3], [1, 1, 1, 0]).name == "Deep"


def test_fold_snapshot_restores_target_and_ancestors():
    song = dnb_song()
    drums, kick = song.tracks[0], song.tracks[1]
    outer = drums.group_track = type(drums)("OUTER", foldable=True)
    drums.fold_state, outer.fold_state = 1, 1
    snap = lom.fold_snapshot(kick)  # Kick itself isn't foldable; DRUMS and OUTER are
    assert [(g.name, st) for g, st in snap] == [("DRUMS", 1), ("OUTER", 1)]
    drums.fold_state = outer.fold_state = 0  # Live unfolds them when Kick gets selected
    lom.restore_folds(snap)
    assert (drums.fold_state, outer.fold_state) == (1, 1)
    snap = lom.fold_snapshot(drums)  # a folded group as the load target
    drums.fold_state = 0
    lom.restore_folds(snap)
    assert drums.fold_state == 1
