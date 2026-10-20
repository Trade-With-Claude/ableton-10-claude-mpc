"""curves.py: segments in bars -> raw parameter values."""

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"))
import curves  # noqa: E402

from fake_lom import Param, auto_filter, db  # noqa: E402

TEMPO = 175.0


def note(hz):
    return 69.0 + 12.0 * math.log2(hz / 440.0)


@pytest.fixture
def freq():
    return auto_filter().parameters[1]


@pytest.fixture
def gain():
    return Param("Gain", 0.0, -35.0, 35.0, fmt=db)


def lane(param, *segments):
    return curves.compile_lane(param, list(segments), TEMPO)


def beat(bar):
    return curves.bar_to_beat(bar)


@pytest.mark.parametrize("rate,bars", [(2, 2.0), (0.5, 0.5), ("1/2", 0.5), ("1/4 bar", 0.25), ("2 bars", 2.0)])
def test_parse_rate(rate, bars):
    assert curves.parse_rate(rate) == bars


@pytest.mark.parametrize("rate", ["fast", 0, "-1", "1/0"])
def test_parse_rate_rejects(rate):
    with pytest.raises(ValueError):
        curves.parse_rate(rate)


def test_ramp_in_raw_space_from_display_units(freq):
    ln = lane(freq, {"from_bar": 9, "to_bar": 25, "shape": "ramp", "start": 300, "end": "12 kHz"})
    a, b = curves.value_at(ln, beat(9)), curves.value_at(ln, beat(25))
    assert a == pytest.approx(note(300), abs=0.1)
    assert b == pytest.approx(note(12000), abs=0.1)
    assert curves.value_at(ln, beat(17)) == pytest.approx((a + b) / 2)
    # before the segment it holds the start, after it the end
    assert curves.value_at(ln, 0.0) == a
    assert curves.value_at(ln, beat(40)) == b


def test_exp_and_log_bend_the_ramp(gain):
    mid = beat(1) + 2.0  # half of a 1-bar segment
    lin = curves.value_at(lane(gain, {"from_bar": 1, "to_bar": 2, "start": -12, "end": 0}), mid)
    exp = curves.value_at(lane(gain, {"from_bar": 1, "to_bar": 2, "shape": "exp", "start": -12, "end": 0}), mid)
    log = curves.value_at(lane(gain, {"from_bar": 1, "to_bar": 2, "shape": "log", "start": -12, "end": 0}), mid)
    assert lin == pytest.approx(-6, abs=0.1)
    assert exp == pytest.approx(-9, abs=0.1)  # slow start
    assert log == pytest.approx(-3, abs=0.1)  # fast start


def test_lfo_shapes_cycle_between_start_and_end(gain):
    seg = {"from_bar": 1, "to_bar": 3, "start": -12, "end": 0, "rate": "1/2"}  # 2-beat cycle
    sine = lane(gain, dict(seg, shape="sine"))
    tri = lane(gain, dict(seg, shape="triangle"))
    sq = lane(gain, dict(seg, shape="square"))
    for ln in (sine, tri, sq):
        assert curves.value_at(ln, 0.0) == pytest.approx(-12, abs=0.1)
    assert curves.value_at(sine, 1.0) == pytest.approx(0, abs=0.1)  # half a cycle: peak
    assert curves.value_at(sine, 2.0) == pytest.approx(-12, abs=0.1)
    assert curves.value_at(tri, 0.5) == pytest.approx(-6, abs=0.1)
    assert curves.value_at(sq, 0.9) == pytest.approx(-12, abs=0.1)
    assert curves.value_at(sq, 1.1) == pytest.approx(0, abs=0.1)
    # an LFO ends on its start value
    assert curves.value_at(sine, beat(5)) == pytest.approx(-12, abs=0.1)


def test_steps_and_hold(gain):
    ln = lane(gain,
              {"from_bar": 1, "to_bar": 2, "shape": "hold", "start": -6},
              {"from_bar": 2, "to_bar": 3, "shape": "steps", "values": [-12, 0, -3, 3], "rate": "1/4"})
    assert curves.value_at(ln, 2.0) == pytest.approx(-6, abs=0.1)
    got = [curves.value_at(ln, beat(2) + b + 0.5) for b in range(4)]
    assert got == pytest.approx([-12, 0, -3, 3], abs=0.1)
    assert curves.value_at(ln, beat(9)) == pytest.approx(3, abs=0.1)


def test_between_segments_holds_the_last_value(gain):
    ln = lane(gain,
              {"from_bar": 5, "to_bar": 6, "start": -12, "end": -6},
              {"from_bar": 1, "to_bar": 2, "start": 0, "end": -12})  # unsorted on purpose
    assert curves.value_at(ln, beat(3)) == pytest.approx(-12, abs=0.1)
    assert curves.value_at(ln, beat(5.5)) == pytest.approx(-9, abs=0.1)


def test_values_clamp_to_range(gain):
    ln = lane(gain, {"from_bar": 1, "to_bar": 2, "start": -100, "end": 100})
    assert curves.value_at(ln, 0.0) == -35.0
    assert curves.value_at(ln, beat(2)) == 35.0


@pytest.mark.parametrize("seg,msg", [
    ({"from_bar": 2, "to_bar": 2, "start": 0, "end": 1}, "after from_bar"),
    ({"from_bar": 0, "to_bar": 2, "start": 0, "end": 1}, ">= 1"),
    ({"to_bar": 2, "start": 0, "end": 1}, "from_bar and to_bar"),
    ({"from_bar": 1, "to_bar": 2, "shape": "zigzag", "start": 0, "end": 1}, "unknown shape"),
    ({"from_bar": 1, "to_bar": 2, "shape": "ramp", "start": 0}, "missing value"),
    ({"from_bar": 1, "to_bar": 2, "shape": "sine", "start": 0, "end": 1}, "needs a `rate`"),
    ({"from_bar": 1, "to_bar": 2, "shape": "steps", "rate": 1}, "non-empty `values`"),
])
def test_bad_segments(gain, seg, msg):
    with pytest.raises(ValueError, match=msg):
        lane(gain, seg)


def test_overlap_rejected(gain):
    with pytest.raises(ValueError, match="overlap"):
        lane(gain, {"from_bar": 1, "to_bar": 3, "start": 0, "end": 1},
             {"from_bar": 2, "to_bar": 4, "start": 0, "end": 1})


def test_fast_lfo_steers_to_device_lfo(gain):
    # 1/8 bar at 175 BPM = 171 ms per cycle, under 4 ticks of 100 ms
    with pytest.raises(ValueError, match="device's own LFO"):
        lane(gain, {"from_bar": 1, "to_bar": 2, "shape": "sine", "start": 0, "end": 1, "rate": "1/8"})
    # 1/2 bar = 686 ms is fine
    lane(gain, {"from_bar": 1, "to_bar": 2, "shape": "sine", "start": 0, "end": 1, "rate": "1/2"})


def test_too_short_steps_rejected(gain):
    with pytest.raises(ValueError, match="too short"):
        lane(gain, {"from_bar": 1, "to_bar": 2, "shape": "steps", "values": [0, 1], "rate": "1/32"})


def test_empty_lane_rejected(gain):
    with pytest.raises(ValueError, match="at least one segment"):
        curves.compile_lane(gain, [], TEMPO)
