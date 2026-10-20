"""recorder.py: a take driven tick by tick against a fake song."""

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"))
import curves  # noqa: E402
import recorder  # noqa: E402

from fake_lom import Track, auto_filter, dnb_song  # noqa: E402

TICK_S = 0.1


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def song():
    s = dnb_song()
    s.tempo = 175.0
    s.tracks.append(Track("test", devices=[auto_filter()]))
    s.tracks[2].arm = True  # Snare armed, like track 28 in Dorian's set
    s.current_song_time = s.insert_marker = 37.0  # Dorian's cursor somewhere else
    return s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def rec(clock):
    return recorder.Recorder(clock=clock)


def freq(song):
    return song.tracks[5].devices[0].parameters[1]


def opening(start_bar=9, bars=4, **kw):
    lane = {"kind": "track", "index": 5, "device_path": [0], "param": "Frequency",
            "segments": [{"from_bar": start_bar, "to_bar": start_bar + bars, "shape": "ramp",
                          "start": 300, "end": "12 kHz"}]}
    lane.update(kw)
    return lane


def run(song, rec, clock, max_ticks=10000, on_tick=None):
    """Advance Live's playhead by one tick of beats per update_display, like Live does."""
    beats_per_tick = TICK_S * song.tempo / 60.0
    history = []
    for _ in range(max_ticks):
        if rec.state not in recorder.RUNNING:
            break
        if song.is_playing:
            song.current_song_time += beats_per_tick
        clock.t += TICK_S
        rec.tick()
        history.append((song.current_song_time, song.record_mode, freq(song).value))
        if on_tick:
            on_tick(history)
    return history


def note(hz):
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def test_full_take(song, rec, clock):
    status = rec.start(song, [opening()], start_bar=9, bars=4)
    assert status["state"] == "preroll"
    # set up for the take: loop off, armed track disarmed, automation arm on, playing
    assert song.loop is False and song.session_automation_record is True
    assert song.tracks[2].arm is False
    assert song.is_playing and not song.record_mode
    # nothing is written before the punch-in: Live keeps the original value before the take
    assert freq(song).value == 127.0
    # Live started at the cursor; the first tick jumps the playhead 1 bar before the take
    assert song.current_song_time == 37.0
    clock.t += TICK_S
    rec.tick()
    assert song.current_song_time == curves.bar_to_beat(8)

    history = run(song, rec, clock)
    assert all(v == 127.0 for b, r, v in history if b < curves.bar_to_beat(9))
    begin, end = curves.bar_to_beat(9), curves.bar_to_beat(13)
    # never records during the pre-roll; punches in on the first tick at/after bar 9
    assert all(not r for b, r, _ in history if b < begin)
    first_rec = next(b for b, r, _ in history if r)
    assert begin <= first_rec < begin + 175.0 / 60.0 * TICK_S
    # values follow the ramp while recording
    for b, r, v in history:
        if r and b < end:
            t = (b - begin) / (end - begin)
            assert v == pytest.approx(note(300) + (note(12000) - note(300)) * t, abs=0.15)
    # ends on the end value, then everything is restored
    assert freq(song).value == pytest.approx(note(12000), abs=0.1)
    st = rec.status()
    assert st["state"] == "done" and st["progress"] == 1.0 and st["error"] is None
    assert st["points_written"] > 40 and st["mean_tick_ms"] == pytest.approx(100.0)
    assert st["ticks"] - st["points_written"] >= 13  # ~1 bar of pre-roll ticks wrote nothing
    assert st["lanes"] == [{"param": "Auto Filter: Frequency", "track": "test"}]
    assert not song.is_playing and not song.record_mode
    assert song.loop is True and song.session_automation_record is False
    assert song.current_song_time == 37.0
    assert song.tracks[2].arm is True


def test_two_lanes_in_one_take(song, rec, clock):
    reso = {"kind": "track", "index": 5, "device_path": [0], "param": "Resonance",
            "segments": [{"from_bar": 9, "to_bar": 13, "shape": "sine", "start": 0.2, "end": 0.8,
                          "rate": 1}]}
    rec.start(song, [opening(), reso], start_bar=9, bars=4)
    run(song, rec, clock)
    assert rec.state == "done"
    assert song.tracks[5].devices[0].parameters[2].value == pytest.approx(0.2, abs=0.01)


def test_preroll_zero_and_bar_one(song, rec, clock):
    rec.start(song, [opening(start_bar=1, bars=2)], start_bar=1, bars=2, preroll_bars=1)
    rec.tick()
    assert song.current_song_time == 0.0  # can't pre-roll before the song start
    run(song, rec, clock)
    assert rec.state == "done"


def test_stop_in_live_aborts_and_restores(song, rec, clock):
    rec.start(song, [opening()], start_bar=9, bars=4)

    def press_stop(history):
        if history[-1][0] >= curves.bar_to_beat(10):
            song.stop_playing()

    run(song, rec, clock, on_tick=press_stop)
    st = rec.status()
    assert st["state"] == "aborted" and "playback stopped in Live" in st["error"]
    assert not song.record_mode and song.loop is True and song.tracks[2].arm is True
    assert 0 < st["progress"] < 1


def test_abort_request(song, rec, clock):
    rec.start(song, [opening()], start_bar=9, bars=4)
    run(song, rec, clock, max_ticks=30)
    st = rec.abort("aborted by request")
    assert st["state"] == "aborted" and st["error"] == "aborted by request"
    assert not song.is_playing and not song.record_mode and song.tracks[2].arm is True
    assert rec.abort()["state"] == "aborted"  # idempotent once finished


def test_write_error_restores(song, rec, clock):
    rec.start(song, [opening()], start_bar=9, bars=4)
    p = freq(song)

    def break_param(history):
        if history[-1][1]:
            p.min = p.max = 0.0  # every later write is out of range
    run(song, rec, clock, on_tick=break_param)
    st = rec.status()
    assert st["state"] == "error" and "out of range" in st["error"]
    assert not song.is_playing and not song.record_mode and song.tracks[2].arm is True


def test_live_never_starts(song, rec, clock):
    song.start_playing = lambda: None
    rec.start(song, [opening()], start_bar=9, bars=4)
    for _ in range(recorder.START_TIMEOUT_TICKS + 1):
        rec.tick()
    st = rec.status()
    assert st["state"] == "error" and "did not start" in st["error"]
    assert song.loop is True and song.tracks[2].arm is True


@pytest.mark.parametrize("setup,msg", [
    (lambda s: setattr(s, "is_playing", True), "stop playback first"),
    (lambda s: setattr(s, "record_mode", True), "record is on"),
    (lambda s: setattr(s, "signature_numerator", 7), "only 4/4"),
    (lambda s: setattr(s, "back_to_arranger", True), "Back to Arrangement"),
])
def test_refuses_bad_transport(song, rec, setup, msg):
    setup(song)
    with pytest.raises((RuntimeError, ValueError), match=msg):
        rec.start(song, [opening()], start_bar=9, bars=4)
    assert rec.state == "idle"


def test_refuses_automated_param_unless_overwrite(song, rec, clock):
    freq(song).automation_state = 1
    with pytest.raises(ValueError, match="already has automation"):
        rec.start(song, [opening()], start_bar=9, bars=4)
    assert song.loop is True and song.tracks[2].arm is True  # nothing touched
    rec.start(song, [opening()], start_bar=9, bars=4, overwrite=True)
    assert rec.state == "preroll"


@pytest.mark.parametrize("lanes,msg", [
    ([], "at least one lane"),
    ([opening(param="Nope")], "lane 0: no param"),
    ([opening(index=99)], "lane 0: no track 99"),
    ([opening(segments=[{"from_bar": 8, "to_bar": 10, "start": 300, "end": 400}])], "within bars"),
    ([opening(), opening()], "already in another lane"),
    ([{"kind": "track", "index": 5, "device_path": [0], "segments": []}], "missing"),
])
def test_bad_lanes(song, rec, lanes, msg):
    with pytest.raises(ValueError, match=msg):
        rec.start(song, lanes, start_bar=9, bars=4)
    assert rec.state == "idle" and song.loop is True


def test_one_take_at_a_time(song, rec):
    rec.start(song, [opening()], start_bar=9, bars=4)
    with pytest.raises(RuntimeError, match="already running"):
        rec.start(song, [opening()], start_bar=9, bars=4)


def test_idle_status(rec):
    st = rec.status()
    assert st["state"] == "idle" and st["bar"] is None and st["mean_tick_ms"] is None
