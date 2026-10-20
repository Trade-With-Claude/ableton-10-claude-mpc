"""ops.py: batch validation, display-unit conversion and undo grouping against a fake LOM."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"))
import lom  # noqa: E402
import ops  # noqa: E402

from fake_lom import FakeLoader, Param, dnb_song  # noqa: E402


@pytest.fixture
def song():
    return dnb_song()


@pytest.fixture
def loader():
    return FakeLoader()


def disp(param):
    return lom._display(param)


def glue(song):
    return song.tracks[0].devices[0]


# -- display parsing / conversion --------------------------------------------
@pytest.mark.parametrize("s,n", [("-12.0 dB", -12.0), ("-inf dB", float("-inf")), ("C", 0.0),
                                 ("25L", -25.0), ("10R", 10.0), ("1.20 kHz", 1200.0),
                                 ("200 Hz", 200.0), ("100 %", 100.0), (".1", 0.1),
                                 ("22.0k", 22000.0), ("1.5k", 1500.0), ("856", 856.0),
                                 ("59 ms", 59.0), ("15.0 s", 15000.0), ("1.00 ms", 1.0)])
def test_parse_display(s, n):
    assert ops.parse_display(s) == n


def test_time_param_mixing_ms_and_s():
    """Analog's envelope times show '5 ms' .. '15.0 s': display=60 means 60 ms (UAT-8 bug)."""
    def fmt(v):
        ms = 5.0 * 3000 ** v
        return "%d ms" % ms if ms < 1000 else "%.1f s" % (ms / 1000)
    p = Param("AEG1 Attack", 0.0, 0.0, 1.0, fmt=fmt)
    assert ops.parse_display(p.str_for_value(ops.value_for(p, display=60))) == pytest.approx(60, abs=2)
    assert p.str_for_value(ops.value_for(p, display="2 s")) == "2.0 s"


def test_volume_db_and_inf(song):
    vol = song.tracks[1].mixer_device.volume
    assert disp_after(vol, ops.value_for(vol, display=-6)) == "-6.0 dB"
    assert disp_after(vol, ops.value_for(vol, display="+3 dB")) == "3.0 dB"
    assert ops.value_for(vol, display="-inf") == 0.0
    assert ops.value_for(vol, display=99) == 1.0  # clamped to +6 dB


def disp_after(param, raw):
    return param.str_for_value(raw)


def test_pan_strings_and_numbers(song):
    pan = song.tracks[1].mixer_device.panning
    assert disp_after(pan, ops.value_for(pan, display="25L")) == "25L"
    assert disp_after(pan, ops.value_for(pan, display=10)) == "10R"
    assert disp_after(pan, ops.value_for(pan, display="C")) == "C"


def test_raw_value_is_clamped(song):
    thr = glue(song).parameters[1]
    assert ops.value_for(thr, value=12.0) == 0.0
    assert ops.value_for(thr, value=-99) == -40.0


def test_quantized_by_item_name_number_and_bool(song):
    g = glue(song)
    ratio, eq_type, on = g.parameters[2], g.parameters[3], g.parameters[0]
    assert ops.value_for(ratio, display=4) == 1.0  # the "4" item, not index 4
    assert ops.value_for(ratio, display="10") == 2.0
    assert ops.value_for(eq_type, display="high PASS") == 5.0
    assert ops.value_for(on, display="off") == 0.0 and ops.value_for(on, display=True) == 1.0
    with pytest.raises(ValueError, match="items: Low Shelf"):
        ops.value_for(eq_type, display="Notch")


def test_khz_display(song):
    freq = glue(song).parameters[4]
    assert disp_after(freq, ops.value_for(freq, display="1.2 kHz")) == "1.20 kHz"
    assert disp_after(freq, ops.value_for(freq, display=200)) == "200 Hz"


def test_find_param_exact_substring_ambiguous(song):
    g = glue(song)
    assert ops.find_param(g, "threshold").name == "Threshold"
    assert ops.find_param(g, "makeup").name == "Makeup"
    assert ops.find_param(g, 2).name == "Ratio" and ops.find_param(g, "2").name == "Ratio"
    with pytest.raises(LookupError, match="ambiguous.*S/C EQ Type, S/C EQ Freq"):
        ops.find_param(g, "s/c eq")
    with pytest.raises(LookupError, match="no param 'Knee'.*Threshold"):
        ops.find_param(g, "Knee")


# -- batches ----------------------------------------------------------------
def test_batch_applies_in_one_undo_step(song, loader):
    batch = [
        {"op": "mixer", "kind": "track", "index": 1, "volume_db": -6, "pan": "25L",
         "sends": {"A-Reverb": -20}, "mute": True},
        {"op": "param", "kind": "track", "index": 0, "path": [0], "param": "Threshold", "display": -10},
        {"op": "param", "kind": "track", "index": 0, "path": [0], "param": "S/C EQ Type",
         "display": "High pass"},
        {"op": "param", "kind": "master", "index": 0, "path": [0], "param": "Ceiling", "value": 3.0},
        {"op": "load_effect", "kind": "track", "index": 0, "name": "EQ Eight"},
        {"op": "delete_device", "kind": "return", "index": 0, "path": [0]},
    ]
    r = ops.apply(song, batch, loader)
    assert (song.undo_begins, song.undo_ends) == (1, 1)
    assert r["applied"] == r["total"] == 9 and "error" not in r
    mixer = r["results"][0]
    assert mixer["target"] == "track 1 'Kick'"
    assert [(c["what"], c["before"], c["after"]) for c in mixer["changes"]] == [
        ("volume", "0.0 dB", "-6.0 dB"), ("pan", "C", "25L"),
        ("send A-Reverb", "-inf dB", "-20.0 dB"), ("mute", "off", "on")]
    assert r["results"][1]["changes"][0]["after"] == "-10.0 dB"
    assert r["results"][2]["changes"][0]["after"] == "High pass"
    assert r["results"][3]["changes"][0]["after"] == "0.0 dB"  # +3 clamped to max 0
    assert r["results"][4]["changes"][0]["after"] == "EQ Eight at [1]"
    assert song.return_tracks[0].devices == [] and r["results"][5]["changes"][0]["after"] == "(deleted)"


def test_validation_failure_applies_nothing(song, loader):
    vol = song.tracks[1].mixer_device.volume.value
    batch = [
        {"op": "mixer", "kind": "track", "index": 1, "volume_db": -6},
        {"op": "load_effect", "kind": "track", "index": 0, "name": "Serum"},
    ]
    with pytest.raises(ValueError, match="op 1: stock effect not found.*Serum"):
        ops.apply(song, batch, loader)
    assert song.tracks[1].mixer_device.volume.value == vol
    assert (song.undo_begins, song.undo_ends) == (0, 0) and loader.loads == []


@pytest.mark.parametrize("op,msg", [
    ({"op": "mixer", "kind": "track", "index": 99, "volume_db": 0}, "no track 99"),
    ({"op": "mixer", "kind": "master", "mute": True}, "master has no mute"),
    ({"op": "mixer", "kind": "master", "sends": {"A": -10}}, "master has no sends"),
    ({"op": "mixer", "kind": "track", "index": 1, "sends": {"C": -10}}, "matches 0 returns"),
    ({"op": "mixer", "kind": "track", "index": 1}, "changes nothing"),
    ({"op": "param", "kind": "track", "index": 0, "path": [5], "param": "x", "value": 0}, "no device 5"),
    ({"op": "load_effect", "kind": "track", "index": 0, "name": "EQ Eight", "position": 9}, "out of range"),
    ({"op": "explode", "kind": "track", "index": 0}, "unknown op"),
])
def test_invalid_ops(song, loader, op, msg):
    with pytest.raises(ValueError, match=msg):
        ops.apply(song, [op], loader)
    assert song.undo_begins == 0


def test_empty_batch_rejected(song):
    with pytest.raises(ValueError, match="non-empty"):
        ops.apply(song, [])


def test_send_by_letter_and_index(song, loader):
    r = ops.apply(song, [{"op": "mixer", "kind": "track", "index": 2, "sends": {"b": -6, "0": "-inf"}}], loader)
    assert [(c["what"], c["after"]) for c in r["results"][0]["changes"]] == [
        ("send A-Reverb", "-inf dB"), ("send B-Delay", "-6.0 dB")]


def test_mid_batch_error_still_closes_undo_step(song):
    r = ops.apply(song, [
        {"op": "mixer", "kind": "track", "index": 1, "volume_db": -3},
        {"op": "load_effect", "kind": "track", "index": 0, "name": "Utility", "position": 0},
        {"op": "mixer", "kind": "track", "index": 2, "volume_db": -3},
    ], FakeLoader(fail=True))
    assert (song.undo_begins, song.undo_ends) == (1, 1)
    assert r["applied"] == 1 and r["total"] == 3
    assert "browser exploded" in r["error"] and "track 0 'DRUMS' load Utility" in r["error"]
    assert song.tracks[2].mixer_device.volume.str_for_value(song.tracks[2].mixer_device.volume.value) == "0.0 dB"


def test_delete_nested_and_shifted_indices(song, loader):
    bass = song.tracks[3]
    r = ops.apply(song, [
        {"op": "load_effect", "kind": "track", "index": 3, "name": "Utility", "position": 0},
        {"op": "delete_device", "kind": "track", "index": 3, "path": [1, 1, 0]},  # Saturator in rack
        {"op": "delete_device", "kind": "track", "index": 3, "path": [0]},  # Serum, now at [1]
    ], loader)
    assert "error" not in r
    assert [d.name for d in bass.devices] == ["Utility", "Bass Rack"]
    assert [d.name for d in bass.devices[1].chains[1].devices] == ["Inner"]


def test_unicode_track_label(song, loader):
    r = ops.apply(song, [{"op": "mixer", "kind": "track", "index": 3, "solo": True}], loader)
    assert r["results"][0]["target"] == "track 3 'Bässe ✦ Sub'"


# -- Phase 5: typographic minus, rack chains, insertion plan -------------------
@pytest.mark.parametrize("s,n", [("−0.51 dB", -0.51), ("–12.0 dB", -12.0), ("+1.10 dB", 1.1)])
def test_parse_display_typographic_minus(s, n):
    assert ops.parse_display(s) == pytest.approx(n)


def test_plugin_with_typographic_minus_sets_the_right_value(song, loader):
    # Phase 4 UAT bug: display -1 on kHs Limiter 'Output gain' landed at -20 dB (the minimum)
    r = ops.apply(song, [{"op": "param", "kind": "master", "path": [1], "param": "Output gain",
                          "display": -1}], loader)
    param = song.master_track.devices[1].parameters[1]
    assert param.value == pytest.approx(0.475, abs=0.001)
    assert r["results"][0]["changes"][0]["before"] == "−0.51 dB"
    assert r["results"][0]["changes"][0]["after"] == "−1.00 dB"


@pytest.mark.parametrize("n,position,expected", [
    (0, None, (None, "default")), (0, 0, (None, "default")),
    (3, None, (2, "selected_right")), (3, 3, (2, "selected_right")), (3, 9, (2, "selected_right")),
    (3, 0, (0, "selected_left")), (3, 2, (1, "selected_right")),
])
def test_insert_plan(n, position, expected):
    assert ops.insert_plan(list(range(n)), position) == expected


def test_load_into_chain_at_position(song, loader):
    r = ops.apply(song, [{"op": "load_effect", "kind": "track", "index": 3, "name": "EQ Eight",
                          "chain": [1, 1], "position": 0}], loader)
    mid = song.tracks[3].devices[1].chains[1]
    assert [d.name for d in mid.devices] == ["EQ Eight", "Saturator", "Inner"]
    assert r["results"][0]["changes"][0]["after"] == "EQ Eight at chain 'Mid' [0]"
    assert loader.loads == [("Mid", "EQ Eight", 0)]


def test_load_into_nested_chain_default_end(song, loader):
    ops.apply(song, [{"op": "load_effect", "kind": "track", "index": 3, "name": "Utility",
                      "chain": [1, 1, 1, 0]}], loader)
    deep = song.tracks[3].devices[1].chains[1].devices[1].chains[0]
    assert [d.name for d in deep.devices] == ["Utility", "Utility"]


@pytest.mark.parametrize("op,msg", [
    ({"chain": [1, 2]}, "empty chain"),
    ({"chain": [1, 9]}, "no chain 9"),
    ({"chain": [0, 0]}, "not a rack"),
    ({"chain": [1]}, "chain path must be"),
    ({"chain": [1, 0], "position": 5}, "out of range"),
])
def test_load_into_chain_invalid(song, loader, op, msg):
    from fake_lom import Chain
    song.tracks[3].devices[1].chains.append(Chain("Empty"))
    with pytest.raises(ValueError, match=msg):
        ops.apply(song, [dict({"op": "load_effect", "kind": "track", "index": 3, "name": "Utility"}, **op)],
                  loader)
    assert loader.loads == []


def test_chain_mixer_in_one_undo_step(song, loader):
    r = ops.apply(song, [
        {"op": "chain_mixer", "kind": "track", "index": 3, "chain": [1, 0], "volume_db": -6, "pan": "10L"},
        {"op": "chain_mixer", "kind": "track", "index": 3, "chain": [1, 1], "mute": True},
        {"op": "load_effect", "kind": "track", "index": 3, "name": "EQ Eight", "chain": [1, 1], "position": 0},
    ], loader)
    assert (song.undo_begins, song.undo_ends) == (1, 1) and "error" not in r
    assert [(c["what"], c["before"], c["after"]) for c in r["results"][0]["changes"]] == [
        ("chain 'Sub' volume", "-3.0 dB", "-6.0 dB"), ("chain 'Sub' pan", "C", "10L")]
    assert r["results"][1]["changes"][0] == {"what": "chain 'Mid' mute", "before": "off", "after": "on"}
    assert song.tracks[3].devices[1].chains[1].mute is True


@pytest.mark.parametrize("op,msg", [
    ({}, "needs \"chain\""),
    ({"chain": [1, 0]}, "changes nothing"),
    ({"chain": [0, 0], "mute": True}, "not a rack"),
])
def test_chain_mixer_invalid(song, op, msg):
    with pytest.raises(ValueError, match=msg):
        ops.apply(song, [dict({"op": "chain_mixer", "kind": "track", "index": 3}, **op)])
