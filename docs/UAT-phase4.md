# Phase 4 UAT — Master Analysis on a real drop (2026-10-16)

Setup: Live 10.1.43, output on BlackHole 2ch @ 48 kHz, master chain Utility (bass mono 120 Hz) → Multiband Dynamics →
Newfangled Saturate → kHs Limiter → Voxengo SPAN → dpMeter5. Session: 175 BPM DnB (33 tracks, groups DRUMS / BASS / ATMO / FX,
2 returns). Dorian played a drop on loop; Claude Code restarted so `analyze_master` was loaded.
Reference: `Survey - Choke Point` (mp3 from a download site, see findings).

## Results

| # | Call | Playing? | LUFS-I / LUFS-S | TP | PLR | Onsets (kick) | `elapsed_s` | Notes |
|---|------|----------|-----------------|----|-----|---------------|-------------|-------|
| 1 | `analyze_master(15)` | drop | −7.72 / −8.06 | +0.30 | 8.03 | 94 | 16.6 | no reference (none last-used) |
| 2 | `analyze_master(15, ref)` | drop | −7.84 / −7.97 | +0.29 | 8.13 | 85 | 20.5 | ref decode ≈ +4 s; ref −5.14 LUFS-I, +2.72 dBTP |
| 3 | `analyze_master(15, ref)` | drop **partly** | −8.24 / −7.94 | −0.24 | 8.00 | 35 | 16.5 | after a mix batch; capture started before Dorian restarted playback → invalid |
| 4 | `analyze_master(15, ref)` | drop | −8.06 / −7.59 | −0.24 | 7.82 | 92 | 16.5 | clean re-capture after the batch |
| 5 | `analyze_master(10)` | stopped | — | — | — | — | — | `No signal on BlackHole 2ch: is Live playing, and is its output set to BlackHole 2ch?` |

- **dpMeter5 agreement:** Dorian read dpMeter5 by eye; values "around the same average". Not a precise ±1 LU check (he was
  reading Momentary/Short-term, which move every second). Runs 1, 2 and 4 agree with each other within 0.35 LU.
- **Stutter:** none (Dorian).
- **Diagnosis vs ears:** Dorian confirmed that the analysis and LUFS "make sense". The reference comparison found a
  300 Hz–1 kHz hole; a batch built from it (ATMO group −4 → −1 dB, MIDS EQ band 2 @ 359 Hz −1.1 → +1.5 dB, kHs Limiter output
  −0.5 → −1.0 dB) was liked by ear, and run 4 measured it: low_mid deviation −2.66 → −0.44 dB, 400 Hz −6.4 → −3.2 dB,
  TP +0.29 → −0.24 dBTP.
- **Silent capture (step 3):** PASS, clear error, no report.

## AC-3

| Criterion | Result |
|-----------|--------|
| Reports LUFS-I/S, TP, PLR, bands incl. sub, stereo, diagnosis in plain language | PASS |
| LUFS-I / TP within ±1 LU / ±1 dB of dpMeter5 | PASS (by eye only) |
| No stutter | PASS |
| Stopped playback → silent-capture error | PASS |

## Findings

1. **Empty 20 Hz and 40 Hz third-octave bands (−140 dB)** on every capture. Welch FFT 4096 @ 48 kHz gives 11.7 Hz bins; no bin
   centre falls in 17.8–22.4 Hz or 35.6–44.9 Hz, so those bands are empty and their energy goes to neighbours. Zone totals are
   fine; per-band reading below ~60 Hz is not (and the 25/31.5 Hz "deficits" vs the reference are unreliable). Fix in
   spectrum-advisor: larger FFT for the low end (16384 → 2.9 Hz) or interpolate empty bands.
2. **Partial-silence captures give wrong reference deviations.** Run 3 (drop only partly playing) showed every zone ≈ −5 dB vs
   the reference: LUFS-I is gated (ignores silence) but the spectrum averages over it. Should be detected (onset/RMS coverage)
   and either rejected or compared on spectral shape only.
3. **Capture start depends on Dorian pressing play in time.** Proposal: let `analyze_master` start playback via the Remote
   Script (and optionally stop it) + wait for signal before recording. Needs a Live-side change → Phase 5.
4. **Pump score is unstable** on the same loop: 0.0 / 4.0 / 8.5 / 0.0. Advisory only; don't rely on it.
5. **`apply` display→value bug on plugin params with a typographic minus.** `display: -1` on kHs Limiter `Output gain`
   (displayed as `−0.51 dB`, U+2212) set −20.00 dB (the minimum). Stock devices unaffected. Dorian fixed it by hand. Fix the
   display parser (Phase 3 code) to normalise U+2212; until then use `value` for third-party plugins.
6. **mp3 references are weak:** the download-site mp3 measures +2.72 dBTP and has a band-limited top end. Prefer WAV/320.
7. Idea (Dorian): resolve the reference from a track named "Reference" in the Live set (clip `file_path`) → Phase 5.
8. **Rack internals are half-visible.** Chain volumes/pans inside racks can't be read, and `load_effect` can't insert into a
   rack chain. Both came up while widening the reese (parallel Chorus rack: couldn't check the wet level or add an HP EQ
   before the Chorus) → Phase 5.
9. **Stereo metrics never moved** (correlation 0.95–0.96, side 2 %, mono Δ 0.20–0.22 LU) across 5 captures, including
   after adding a parallel Chorus + Valhalla on the reese. It's plausible for this mix, but it hasn't been cross-checked
   against SPAN's correlation meter or a soloed stereo source yet.
