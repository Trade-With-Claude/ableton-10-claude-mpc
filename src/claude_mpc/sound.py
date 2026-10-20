"""Listen to a sample: notes, rhythm, key and a synth recipe (oscillator, filter, envelope, width).

Monophonic: pyin pitch tracking split into notes at silences, onsets and pitch jumps; a note
that slides into its pitch reports `glide_from`. Timbre comes from the harmonic levels in each
note's settled middle. Good on leads and basses, not on chords or full loops.
"""

import os
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 22050
HOP = 256  # ~11.6 ms per pyin frame
FMIN, FMAX = 40.0, 2000.0
MAX_SECONDS = 30.0
SILENCE_DB = -35.0  # frames this far below the loudest are silence
MIN_NOTE_S = 0.05
JUMP_ST = 3.0  # a pitch move larger than this inside a voiced run starts a new note
GLIDE_FRAMES = 3  # where a note's start pitch is read
GLIDE_MIN_ST = 0.7
PLATEAU_S = 0.12  # two settled pitches this long in one run are two (legato) notes
REATTACK_DB = 3.0  # an onset only splits a voiced run if the level jumps this much
GLIDE_MAX_ST = 2.5  # a sliding segment this close to the next note is its glide
STEADY_FRAMES = 4  # ~46 ms on pitch to read a note's harmonics
RESONANT_DB = 3.0  # a harmonic this far over the fundamental = a filter peak
OCTAVE_DB = 20.0
GRID = 0.25  # beats: 1/16 note
AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a"}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Krumhansl-Kessler key profiles
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


class SoundError(Exception):
    pass


def note_name(midi: int) -> str:
    return f"{NAMES[midi % 12]}{midi // 12 - 1}"


# -- finding the file -----------------------------------------------------------------
def find_sample(name: str) -> list[str]:
    """Audio files for a path or a file name (Spotlight search), best match first."""
    p = Path(os.path.expanduser(name))
    if p.is_file():
        return [str(p.resolve())]
    try:
        out = subprocess.run(["mdfind", "-name", p.name], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SoundError(f"Spotlight search failed: {exc}") from exc
    hits = [h for h in out.splitlines() if Path(h).suffix.lower() in AUDIO_EXT]
    exact = [h for h in hits if Path(h).name == p.name or Path(h).stem == p.name]
    return sorted(exact) + sorted(set(hits) - set(exact))


# -- hints from the file name -----------------------------------------------------------
def tempo_from_name(path: str) -> float | None:
    stem = Path(path).stem
    m = re.search(r"(\d{2,3})\s*bpm", stem, re.I)
    if m:
        return float(m.group(1))
    for tok in re.split(r"[_\-\s.]+", stem):
        if tok.isdigit() and 60 <= int(tok) <= 200:
            return float(tok)
    return None


def key_from_name(path: str) -> str | None:
    for tok in reversed(re.split(r"[_\-\s.]+", Path(path).stem)):
        m = re.fullmatch(r"([A-Ga-g])([#b]?)(m|min|minor|maj|major)?", tok)
        if m and (m.group(2) or m.group(3) or tok.isupper()):
            root = m.group(1).upper() + m.group(2).replace("b", "♭")
            if "♭" in root:  # spell flats as sharps
                root = NAMES[(NAMES.index(root[0]) - 1) % 12]
            return f"{root} {'minor' if (m.group(3) or '').startswith('m') and m.group(3) not in ('maj', 'major') else 'major'}"
    return None


# -- analysis -----------------------------------------------------------------------------
def _load(path: str):
    try:
        x, sr = sf.read(path, always_2d=True, frames=-1)
    except (RuntimeError, sf.LibsndfileError) as exc:
        raise SoundError(f"can't read {path}: {exc}") from exc
    x = x[: int(MAX_SECONDS * sr)].astype(np.float32)
    if not np.any(np.abs(x) > 1e-4):
        raise SoundError(f"{Path(path).name} is silent")
    return x, sr


def _segments(midi, voiced, loud, onsets, db):
    """[(start_frame, end_frame)] of notes: voiced+loud runs split at onsets, jumps and plateaus."""
    ok = voiced & loud
    segs, start = [], None
    for i, v in enumerate(np.append(ok, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            segs.append((start, i))
            start = None
    out = []
    for s, e in segs:
        cuts = {s, e}
        cuts |= {o for o in onsets if s + 2 < o < e - 2
                 and db[o: o + 4].max() - db[o - 2: o].min() >= REATTACK_DB}
        for i in range(s + 1, e):
            if abs(midi[i] - midi[i - 1]) > JUMP_ST:
                cuts.add(i)
        cuts = sorted(cuts)
        for a, b in zip(cuts, cuts[1:]):
            out.extend(_split_plateaus(midi, a, b))
    return _merge_glides(midi, out)


def _merge_glides(midi, segs):
    """A segment that slides towards the next one it touches is that note's glide, not a note."""
    out = []
    for seg in segs:
        if out:
            s0, e0 = out[-1]
            s1, e1 = seg
            target = np.median(midi[s1 + (e1 - s1) // 2: e1])
            slide = midi[e0 - 1] - midi[s0]
            if (e0 == s1 and abs(target - midi[s0]) <= GLIDE_MAX_ST and abs(slide) >= 0.5
                    and np.sign(slide) == np.sign(target - midi[s0])):
                out[-1] = (s0, e1)
                continue
        out.append(seg)
    return out


def _split_plateaus(midi, s, e):
    """Split a run holding two settled pitches (legato) at the move towards the second one."""
    plateau = int(PLATEAU_S * SR / HOP)
    r = np.round(midi[s:e])
    runs, i = [], 0
    while i < len(r):
        j = i
        while j < len(r) and r[j] == r[i]:
            j += 1
        runs.append((i, j, r[i]))
        i = j
    long_runs = [(a, b, p) for a, b, p in runs if b - a >= plateau]
    if len(long_runs) < 2:
        return [(s, e)]
    out, begin = [], s
    for (a0, b0, _), (a1, _, _) in zip(long_runs, long_runs[1:]):
        out.append((begin, s + b0))
        begin = s + b0
    out.append((begin, e))
    return out


def _steady(midi, s, e, pitch):
    """Longest run of frames in [s, e) within 0.3 semitones of `pitch`."""
    best, a = (s, s), None
    for i in range(s, e + 1):
        on = i < e and abs(midi[i] - pitch) < 0.3
        if on and a is None:
            a = i
        elif not on and a is not None:
            if i - a > best[1] - best[0]:
                best = (a, i)
            a = None
    return best


def _harmonics(x, sr, f0, n=16):
    win = x * np.hanning(len(x))
    nfft = 1 << max(14, int(np.ceil(np.log2(len(win)))))
    sp = np.abs(np.fft.rfft(win, n=nfft))
    fr = np.fft.rfftfreq(nfft, 1 / sr)
    tol = max(3, int(0.03 * f0 / (sr / nfft)))
    levels = []
    for k in range(1, n + 1):
        if k * f0 >= sr / 2:
            break
        c = int(round(k * f0 / (sr / nfft)))
        levels.append(sp[max(0, c - tol): c + tol + 1].max())
    levels = np.array(levels)
    return 20 * np.log10(levels / max(levels[0], 1e-12) + 1e-12)


def _osc(h):
    """sine | triangle | square | saw from harmonic levels (dB re fundamental)."""
    h = np.pad(h, (0, max(0, 8 - len(h))), constant_values=-120.0)
    if max(h[1:5]) < -25:
        return "sine"
    odd, even = np.mean(h[[2, 4, 6]]), np.mean(h[[1, 3, 5]])
    if odd - even >= 8:
        return "square" if h[2] > -15 else "triangle"
    return "saw"


def _key(notes):
    w = np.zeros(12)
    for n in notes:
        w[n["pitch"] % 12] += n["length_beats"]
    if not w.any():
        return None
    best = max(((np.corrcoef(np.roll(prof, k), w)[0, 1], f"{NAMES[k]} {mode}")
                for prof, mode in ((MAJOR, "major"), (MINOR, "minor")) for k in range(12)))
    return best[1]


def _envelope(rms, notes_frames, hop_s):
    att, dec, sus, rel = [], [], [], []
    for (s, e), nxt in zip(notes_frames, [f[0] for f in notes_frames[1:]] + [len(rms)]):
        seg = rms[s:e]
        if len(seg) < 3:
            continue
        pk_i = int(np.argmax(seg))
        pk = seg[pk_i]
        att.append(pk_i * hop_s)
        tail = seg[pk_i:]
        s_lvl = float(np.median(seg[int(len(seg) * 0.7):]) / pk)
        sus.append(s_lvl)
        target = s_lvl + 0.1 * (1 - s_lvl)
        below = np.nonzero(tail / pk <= target)[0]
        dec.append((below[0] if len(below) else len(tail)) * hop_s)
        after = rms[e:nxt]
        quiet = np.nonzero(after <= 0.1 * pk)[0]
        rel.append((quiet[0] if len(quiet) else len(after)) * hop_s)
    if not att:
        return None
    ms = lambda v: round(float(np.median(v)) * 1000)  # noqa: E731
    return {"attack_ms": ms(att), "decay_ms": ms(dec), "sustain": round(float(np.median(sus)), 2),
            "release_ms": ms(rel)}


def analyze_sample(path: str, tempo: float | None = None) -> dict:
    import librosa

    x, sr_file = _load(path)
    mono_full = x.mean(axis=1)
    y = librosa.resample(mono_full, orig_sr=sr_file, target_sr=SR) if sr_file != SR else mono_full
    duration = len(mono_full) / sr_file

    tempo_src = "given"
    if not tempo:
        tempo, tempo_src = tempo_from_name(path), "file name"
    if not tempo:
        est = librosa.beat.beat_track(y=y, sr=SR)[0]
        tempo, tempo_src = float(np.atleast_1d(est)[0]), "estimated"
    beat_s = 60.0 / tempo
    hop_s = HOP / SR

    f0, voiced, _ = librosa.pyin(y, fmin=FMIN, fmax=FMAX, sr=SR, hop_length=HOP, frame_length=2048)
    midi = np.where(voiced, librosa.hz_to_midi(np.nan_to_num(f0, nan=FMIN)), 0.0)
    rms = librosa.feature.rms(y=y, hop_length=HOP, frame_length=2048)[0][: len(midi)]
    db = 20 * np.log10(rms / max(rms.max(), 1e-12) + 1e-12)
    loud = db > SILENCE_DB
    onsets = librosa.onset.onset_detect(y=y, sr=SR, hop_length=HOP, backtrack=True)

    notes, frames = [], []
    min_frames = int(MIN_NOTE_S / hop_s)
    for s, e in _segments(midi, voiced, loud, onsets, db):
        if e - s < min_frames:
            continue
        settled = midi[s + (e - s) // 2: e]
        pitch = int(round(float(np.median(settled))))
        head = float(np.median(midi[s: s + GLIDE_FRAMES]))
        glide = int(round(head)) if abs(head - pitch) >= GLIDE_MIN_ST else None
        start = round(s * hop_s / beat_s / GRID) * GRID
        length = max(GRID, round((e - s) * hop_s / beat_s / GRID) * GRID)
        notes.append({"pitch": pitch, "name": note_name(pitch), "start_beat": start,
                      "length_beats": length, "peak": float(rms[s:e].max()),
                      "glide_from": glide, "glide_from_name": note_name(glide) if glide else None})
        frames.append((s, e))
    if not notes:
        raise SoundError(f"no pitched notes found in {Path(path).name} (drums, noise or chords?)")
    top = max(n["peak"] for n in notes)
    for n in notes:
        n["velocity"] = int(round(60 + 67 * n.pop("peak") / top))

    # timbre: harmonics where each note sits on its pitch (not while it glides)
    hs, moves, peaks = [], [], []
    S = np.abs(librosa.stft(y, hop_length=HOP))
    cent = librosa.feature.spectral_centroid(S=S, sr=SR)[0]
    for n, (s, e) in zip(notes, frames):
        a, b = _steady(midi, s, e, n["pitch"])
        if b - a >= STEADY_FRAMES:
            hz = float(np.median(f0[a:b]))
            hn = _harmonics(mono_full[int(a * hop_s * sr_file): int(b * hop_s * sr_file)], sr_file, hz)
            hs.append(hn)
            if hn[1:6].max() > RESONANT_DB:
                k = int(np.argmax(hn[:6]))
                peaks.append(hz * (k + 1))
            if len(hn) > 1 and hn[1] > OCTAVE_DB:
                n["octave_check"] = "2nd harmonic dominates: may sound an octave higher"
        third = max(1, (e - s) // 3)
        c0, c1 = np.mean(cent[s: s + third]), np.mean(cent[e - third: e])
        moves.append((c1 - c0) / max(c0, 1.0))
    width = min(len(h) for h in hs) if hs else 0
    h = np.median([h[:width] for h in hs], axis=0) if hs else np.array([0.0])
    # the oscillator shows best in notes where no filter peak lifts a harmonic over the fundamental
    clean = [hn[:width] for hn in hs if hn[1:6].max() <= RESONANT_DB]
    osc_h = np.median(clean, axis=0) if clean else h
    above = np.nonzero(h >= h.max() - 24)[0]
    open_top = width and above[-1] >= width - 3  # a plain saw reaches -24 dB at H16
    f_ref = float(np.median([librosa.midi_to_hz(n["pitch"]) for n in notes]))
    resonance = ({"hz": round(float(np.median(peaks))), "notes": len(peaks)}
                 if len(peaks) * 2 >= len(hs) and peaks else None)
    move = float(np.median(moves))
    flat = float(np.mean(librosa.feature.spectral_flatness(S=S)[0][loud[: S.shape[1]]]))

    mid, side = x.mean(axis=1), (x[:, 0] - x[:, -1]) / 2
    ratio = float(np.sqrt(np.mean(side ** 2)) / max(np.sqrt(np.mean(mid ** 2)), 1e-12))

    bars = duration / beat_s / 4
    return {
        "file": str(Path(path).resolve()),
        "sr": sr_file,
        "duration_s": round(duration, 2),
        "tempo": round(tempo, 2),
        "tempo_source": tempo_src,
        "bars": round(bars, 2),
        "notes": notes,
        "key": _key(notes),
        "key_from_name": key_from_name(path),
        "timbre": {
            "osc": _osc(osc_h),
            "osc_confidence": "ok" if clean else "low (every note has a filter peak)",
            "harmonics_db": [round(float(v), 1) for v in h[:8]],
            "resonance": resonance,
            "cutoff_hz": None if open_top else round(f_ref * (above[-1] + 1.5)),
            "filter": "open (no clear low-pass)" if open_top else "low-passed",
            "brightness_move": {
                "within_note": "rises" if move > 0.15 else "falls" if move < -0.15 else "steady",
                "change_pct": round(move * 100),
                "centroid_hz": round(float(np.median(cent[loud[: len(cent)]]))),
            },
            "noise": "noisy" if flat > 0.1 else "some" if flat > 0.01 else "none",
        },
        "envelope": _envelope(rms, frames, hop_s),
        "stereo": {"side_mid": round(ratio, 2),
                   "width": "mono" if ratio < 0.05 else "narrow" if ratio < 0.25 else "wide"},
        "glides": sum(1 for n in notes if n["glide_from"] is not None),
    }
