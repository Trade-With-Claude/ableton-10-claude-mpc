"""sound.py: notes, rhythm and timbre of synthetic samples with known answers."""

import subprocess

import numpy as np
import pytest
import soundfile as sf

from claude_mpc import sound

SR = 44100
TEMPO = 172.0
BEAT = 60.0 / TEMPO


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def wave(freqs, shape):
    """Band-limited oscillator following a per-sample frequency array."""
    phase = 2 * np.pi * np.cumsum(freqs) / SR
    if shape == "sine":
        return np.sin(phase)
    out = np.zeros_like(phase)
    for k in range(1, 40):
        if shape == "square" and k % 2 == 0:
            continue
        if shape == "triangle" and k % 2 == 0:
            continue
        amp = (1 / k ** 2 * (-1) ** ((k - 1) // 2)) if shape == "triangle" else 1 / k
        out += amp * np.sin(k * phase) * (k * freqs < SR / 2 - 1000)
    return out / np.abs(out).max()


def note(midi, beats, shape="square", glide_from=None, attack_s=0.005, glide_s=0.08):
    n = int(beats * BEAT * SR)
    f = np.full(n, hz(midi))
    if glide_from is not None:
        g = int(glide_s * SR)
        f[:g] = hz(np.linspace(glide_from, midi, g))
    env = np.minimum(1.0, np.arange(n) / max(1, attack_s * SR))
    env[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))
    return 0.5 * wave(f, shape) * env


def rest(beats):
    return np.zeros(int(beats * BEAT * SR))


def write(tmp_path, name, mono, right=None):
    path = tmp_path / name
    right = mono if right is None else right
    sf.write(path, np.stack([mono, right], axis=1), SR)
    return str(path)


@pytest.fixture
def arpeggio(tmp_path):
    bar = np.concatenate([note(70, 1.25, glide_from=68), rest(0.25), note(78, 1.25), rest(0.25),
                          note(85, 0.75, glide_from=83), rest(0.25)])
    return write(tmp_path, "lead_172_tension_F#.wav", np.tile(bar, 2))


def test_arpeggio_with_glides(arpeggio):
    r = sound.analyze_sample(arpeggio)
    assert r["tempo"] == 172.0 and r["tempo_source"] == "file name"
    assert r["bars"] == pytest.approx(2.0, abs=0.05)
    got = [(n["pitch"], n["start_beat"]) for n in r["notes"]]
    assert got == [(70, 0.0), (78, 1.5), (85, 3.0), (70, 4.0), (78, 5.5), (85, 7.0)]
    glides = [n["glide_from"] for n in r["notes"]]
    assert glides[0] in (68, 69) and glides[1] is None and glides[2] in (83, 84)
    assert r["glides"] == 4
    assert r["notes"][0]["length_beats"] == pytest.approx(1.25, abs=0.25)
    assert r["notes"][0]["name"] == "A#4" and r["notes"][0]["glide_from_name"] in ("G#4", "A4")
    assert all(60 <= n["velocity"] <= 127 for n in r["notes"])
    assert r["key"] == "F# major" and r["key_from_name"] == "F# major"
    assert r["timbre"]["osc"] == "square" and r["timbre"]["noise"] == "none"
    assert r["stereo"]["width"] == "mono"


@pytest.mark.parametrize("shape", ["square", "saw", "sine", "triangle"])
def test_oscillator_family(tmp_path, shape):
    path = write(tmp_path, f"{shape}.wav", np.concatenate([note(57, 3, shape), rest(1)]))
    r = sound.analyze_sample(path, tempo=TEMPO)
    assert r["tempo_source"] == "given"
    assert [n["name"] for n in r["notes"]] == ["A3"]
    assert r["timbre"]["osc"] == shape


def test_unfiltered_saw_is_open_and_lowpassed_saw_has_cutoff(tmp_path):
    open_saw = sound.analyze_sample(write(tmp_path, "saw.wav", note(57, 3, "saw")), tempo=TEMPO)
    assert open_saw["timbre"]["filter"].startswith("open") and open_saw["timbre"]["cutoff_hz"] is None
    sine = sound.analyze_sample(write(tmp_path, "sine.wav", note(57, 3, "sine")), tempo=TEMPO)
    assert sine["timbre"]["cutoff_hz"] < 600


def test_envelope_attack(tmp_path):
    slow = np.concatenate([note(57, 2, "saw", attack_s=0.15), rest(1)] * 2)
    r = sound.analyze_sample(write(tmp_path, "pad.wav", slow), tempo=TEMPO)
    assert 90 <= r["envelope"]["attack_ms"] <= 220
    assert r["envelope"]["sustain"] > 0.8


def test_stereo_width(tmp_path):
    sig = note(57, 3, "saw")
    wide = sound.analyze_sample(write(tmp_path, "wide.wav", sig, np.roll(sig, 200) * -0.3),
                                tempo=TEMPO)
    assert wide["stereo"]["width"] == "wide"


@pytest.mark.parametrize("name,tempo,key", [
    ("TSP_SL_172_synth_lead_tension_F#.wav", 172.0, "F# major"),
    ("bass 174bpm Fm.wav", 174.0, "F minor"),
    ("reese_Bbmin_140.wav", 140.0, "A# minor"),
    ("pad_loop_A.wav", None, "A major"),
    ("vocal.wav", None, None),
])
def test_hints_from_file_name(name, tempo, key):
    assert sound.tempo_from_name(name) == tempo
    assert sound.key_from_name(name) == key


def test_missing_and_silent_files(tmp_path):
    with pytest.raises(sound.SoundError, match="can't read"):
        sound.analyze_sample(str(tmp_path / "nope.wav"))
    with pytest.raises(sound.SoundError, match="silent"):
        sound.analyze_sample(write(tmp_path, "silence.wav", rest(4)))


def test_find_sample(tmp_path, monkeypatch):
    real = write(tmp_path, "lead.wav", note(57, 1))
    assert sound.find_sample(real) == [real]

    def fake_mdfind(cmd, **kw):
        assert cmd == ["mdfind", "-name", "lead"]
        out = "/x/other lead take.wav\n/x/lead.wav\n/x/lead.wav.asd\n/x/lead.als\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=out)
    monkeypatch.setattr(sound.subprocess, "run", fake_mdfind)
    assert sound.find_sample("lead") == ["/x/lead.wav", "/x/other lead take.wav"]
