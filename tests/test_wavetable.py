"""wavetable.py: Wavetable's own API (tables, voices, modulation matrix)."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"))
import wavetable  # noqa: E402

from fake_lom import FakeWavetable, dnb_song, Device  # noqa: E402


@pytest.fixture
def song():
    return dnb_song()


@pytest.fixture
def wt():
    return FakeWavetable()


def test_read_defaults(wt):
    r = wavetable.read(wt)
    assert r["categories"] == ["Basics", "Synth"]
    assert r["osc1"]["category"] == "Basics" and r["osc1"]["table"] == "Basic Shapes"
    assert r["osc1"]["effect_mode"] == "None" and r["mono"] is False
    assert r["unison"] == {"mode": "None", "voices": 3} and r["filter_routing"] == "Serial"
    assert r["modulation"] == [] and r["modulation_targets"] == ["Filter 1 Freq"]


def test_apply_everything_in_one_undo_step(song, wt):
    r = wavetable.apply(song, wt, {
        "osc1": {"category": "synth", "table": "Bright Lead", "effect_mode": "Classic"},
        "osc2": {"table": "Pulse"},
        "mono": True,
        "unison": {"mode": "Classic", "voices": 4},
        "filter_routing": "Parallel",
        "modulation": [{"target": "Osc 1 Transp", "source": "Env 2", "amount": -0.08},
                       {"target": "Filter 1 Freq", "source": "lfo1", "amount": 0.3}],
    })
    assert r["applied"] == r["total"] == 10 and "error" not in r
    s = r["state"]
    assert s["osc1"]["category"] == "Synth" and s["osc1"]["table"] == "Bright Lead"
    assert s["osc2"]["table"] == "Pulse Width" and s["osc1"]["effect_mode"] == "Classic"
    assert s["mono"] is True and s["unison"] == {"mode": "Classic", "voices": 4}
    assert wt.unison_voice_count == 4  # Live takes the count itself (UAT-8: 4 showed as 2)
    assert s["filter_routing"] == "Parallel"
    assert {(m["target"], m["source"], m["amount"]) for m in s["modulation"]} == {
        ("Osc 1 Transp", "Env 2", -0.08), ("Filter 1 Freq", "LFO 1", 0.3)}
    assert (song.undo_begins, song.undo_ends) == (1, 1)


@pytest.mark.parametrize("settings,msg", [
    ({}, "non-empty"),
    ({"voices": 3}, "unknown settings"),
    ({"osc1": {"category": "Nope"}}, "matches 0"),
    ({"unison": {"mode": "Supersaw"}}, "unison mode"),
    ({"unison": {"voices": 9}}, "1..8"),
    ({"modulation": [{"target": "Osc 1 Pos", "source": "Env 9", "amount": 0.1}]}, "source"),
    ({"modulation": [{"target": "Osc 1 Pos", "source": "Env 2", "amount": 2}]}, "-1..1"),
    ({"modulation": [{"target": "Osc 1 Pos", "source": "Env 2"}]}, "needs target"),
])
def test_invalid_settings_change_nothing(song, wt, settings, msg):
    with pytest.raises(ValueError, match=msg):
        wavetable.apply(song, wt, settings)
    assert song.undo_begins == 0 and wt.oscillator_1_wavetable_category == 0


def test_runtime_errors_are_reported(song, wt):
    r = wavetable.apply(song, wt, {"osc1": {"table": "Nope"},
                                   "modulation": [{"target": "Volume", "source": "LFO 1", "amount": 0.2}]})
    assert r["applied"] == 0 and "osc1 table" in r["error"]
    r = wavetable.apply(song, wt, {"modulation": [{"target": "Volume", "source": "LFO 1", "amount": 0.2}]})
    assert "can't be modulated" in r["error"]


def test_not_a_wavetable():
    with pytest.raises(ValueError, match="not a Wavetable"):
        wavetable.read(Device("Analog", "UltraAnalog"))
