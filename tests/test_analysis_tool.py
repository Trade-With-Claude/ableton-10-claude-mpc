"""analyze_master: capture mocked with a synthetic buffer, real spectrum-advisor analysis."""

import asyncio
import json

import numpy as np
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from spectrum_advisor.analysis import oneshot
from spectrum_advisor.audio import capture
from spectrum_advisor.audio.samplerate import SampleRateCheck, SampleRateMismatchError
from spectrum_advisor.ui import session

from claude_mpc import analysis, server
from claude_mpc.client import LiveClient

SR = 48000


def _drop(seconds: int) -> np.ndarray:
    rng = np.random.default_rng(0)
    n = SR * seconds
    t = np.arange(n) / SR
    sub = 0.4 * np.sin(2 * np.pi * 50 * t)
    return np.stack([sub + 0.05 * rng.standard_normal(n), sub + 0.05 * rng.standard_normal(n)], 1).astype(
        np.float32
    )


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    def fake_record(seconds, *a, **k):
        calls.append(seconds)
        return _drop(seconds)

    monkeypatch.setattr(capture, "record", fake_record)
    return calls


@pytest.fixture(autouse=True)
def no_session(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "SESSION_PATH", tmp_path / "session.json")
    return tmp_path / "session.json"


@pytest.fixture
def wired(client, monkeypatch):
    monkeypatch.setattr(server, "live", client)


@pytest.fixture(autouse=True)
def no_preroll(monkeypatch):
    monkeypatch.setattr(server, "PREROLL_S", 0)


def run(coro):
    return asyncio.run(coro)


def test_analyze_master_end_to_end(wired, recorded):
    r = run(server.analyze_master())
    json.dumps(r, allow_nan=False)
    assert recorded == [15]
    assert r["seconds"] == 15 and r["bpm"] == 174.0  # FakeLive tempo
    assert r["reference_used"] is None and "reference" not in r
    assert r["bands"]["zones_db"]["sub"] > r["bands"]["zones_db"]["mid"]
    assert r["loudness"]["lufs_i"] is not None


@pytest.mark.parametrize("asked, got", [(3, 10), (15, 15), (300, 60)])
def test_seconds_clamped(wired, recorded, monkeypatch, asked, got):
    monkeypatch.setattr(oneshot, "analyze_buffer", lambda frames, **k: {})
    run(server.analyze_master(seconds=asked))
    assert recorded == [got]


def test_bpm_falls_back_when_live_is_down(recorded, monkeypatch):
    monkeypatch.setattr(server, "live", LiveClient(port=1, timeout=0.2))
    r = run(server.analyze_master(seconds=10))
    assert r["bpm"] == analysis.DEFAULT_BPM


def test_reference_resolution(tmp_path, no_session):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"")
    assert analysis.resolve_reference(str(ref)) == (ref, "arg")
    assert analysis.resolve_reference(None) == (None, None)
    session.save(session.Session(last_reference_path=str(ref)), no_session)
    assert analysis.resolve_reference(None) == (ref, "last_used")
    with pytest.raises(analysis.AnalysisError, match="not found"):
        analysis.resolve_reference(str(tmp_path / "nope.wav"))


def test_reference_from_last_used_is_applied(wired, recorded, monkeypatch, tmp_path, no_session):
    from spectrum_advisor.analysis.reference_profile import ReferenceProfile

    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"")
    session.save(session.Session(last_reference_path=str(ref)), no_session)
    _, _, bands = oneshot.compute_spectrum(_drop(10), sr=SR)
    profile = ReferenceProfile(ref, "0" * 64, SR, 180.0, -5.0, 4.0, 0.5, 8.0, 5.5, bands.astype(np.float32), 0.0)
    monkeypatch.setattr(oneshot, "load_reference_profile", lambda p: profile)
    r = run(server.analyze_master(seconds=10))
    assert r["reference_used"] == {"path": str(ref), "source": "last_used"}
    assert set(r["reference"]["zone_deviation_db"]) == {z[0] for z in oneshot.ZONES}


def test_silence_is_a_readable_tool_error(wired, monkeypatch):
    monkeypatch.setattr(capture, "record", lambda s, *a, **k: np.zeros((SR * s, 2), np.float32))
    with pytest.raises(ToolError, match="is Live playing"):
        run(server.analyze_master())


def test_sample_rate_mismatch_is_a_readable_tool_error(wired, monkeypatch):
    check = SampleRateCheck(False, 0, "BlackHole 2ch", 48000, 44100.0, "BlackHole 2ch reports 44100 Hz, expected 48000 Hz.")

    def bad(*a, **k):
        raise SampleRateMismatchError(check)

    monkeypatch.setattr(capture, "record", bad)
    with pytest.raises(ToolError, match="44100"):
        run(server.analyze_master())


def test_live_errors_reach_claude_as_tool_errors(wired):
    with pytest.raises(ToolError, match="no return track 7"):
        run(server.get_device_params("return", 7, [0]))


# -- Phase 5: autoplay + partial-silence rejection ------------------------------
def _with_gap(seconds: int, silent_share: float) -> np.ndarray:
    frames = _drop(seconds)
    frames[: int(len(frames) * silent_share)] = 0.0
    return frames


@pytest.mark.parametrize("share, expected", [(0.0, 0.0), (0.3, 0.3), (1.0, 1.0)])
def test_silence_fraction(share, expected):
    assert analysis.silence_fraction(_with_gap(10, share), SR) == pytest.approx(expected, abs=0.011)


def test_autoplay_starts_and_stops_live(wired, recorded, fake_live):
    r = run(server.analyze_master(seconds=10))
    assert fake_live.transport_calls == [True, False] and fake_live.playing is False
    assert r["autoplay"] == "started" and r["silence_fraction"] == 0.0


def test_autoplay_leaves_a_playing_live_alone(wired, recorded, fake_live):
    fake_live.playing = True
    r = run(server.analyze_master(seconds=10))
    assert fake_live.transport_calls == [] and fake_live.playing is True
    assert r["autoplay"] == "already_playing"


def test_autoplay_off(wired, recorded, fake_live):
    r = run(server.analyze_master(seconds=10, autoplay=False))
    assert fake_live.transport_calls == [] and r["autoplay"] == "off"


def test_autoplay_unknown_when_live_is_down(recorded, monkeypatch):
    monkeypatch.setattr(server, "live", LiveClient(port=1, timeout=0.2))
    assert run(server.analyze_master(seconds=10))["autoplay"] == "unknown"


def test_partial_silence_is_rejected_and_playback_still_stopped(wired, fake_live, monkeypatch):
    monkeypatch.setattr(capture, "record", lambda s, *a, **k: _with_gap(s, 0.3))
    with pytest.raises(ToolError, match=r"30% of the capture is silent.*Loop a continuous section"):
        run(server.analyze_master(seconds=10))
    assert fake_live.transport_calls == [True, False]


def test_small_gap_is_tolerated(wired, monkeypatch):
    monkeypatch.setattr(capture, "record", lambda s, *a, **k: _with_gap(s, 0.05))
    r = run(server.analyze_master(seconds=10))
    assert r["silence_fraction"] == pytest.approx(0.05, abs=0.011)
