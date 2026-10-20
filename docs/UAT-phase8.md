# UAT — Phase 8: Sound Reproduction

Date: 2026-10-20 · Live 10.1.43 · set at 175 BPM · Remote Script 0.6.0 → 0.6.1 (+ unison fix, installed, loads on next restart)
Sample: `~/Documents/sample/TSP_SL_172_synth_lead_tension_F#.wav` (track 33 "test", 4 bars at 172 BPM)

## Results

| Step | Result | Notes |
|---|---|---|
| Analyse | PASS | `analyze_sample` by path, ~5 s. F# major arpeggio A#4 / F#5 / C#6 on beats 1, 2.5, 4, every note gliding up ~2 st; saw-ish, resonant peak ~1.47 kHz, cutoff ~2.6 kHz, attack ~90 ms, wide. `octave_check` flagged on E5/C#6 (not raised by Dorian). Bars 1–2 transcribed an E5 grace before F#5; Claude cleaned the clip to one consistent pattern. |
| Build v1: Analog | PASS mechanically / "vraiment basique" | `create_instrument_track` 1.3 s: MIDI track 34 "Lead repro", Analog, 16-beat clip with 12 notes. Settings batch (14 ops incl. Chorus) 254 ms. Bug: Attack/Release `display` 60/30 landed on 15.0 s ('s' vs 'ms' display) → fixed live with raw values, fixed in code (0.6.1). Dorian: "ça sonne pas vraiment pareil… t'aurais plus dû essayer d'utiliser wave table". |
| Clip in the Arrangement | PASS with friction | Dorian didn't see the clip (it is in Session View) and couldn't drag across views; Cmd+C / Tab / Cmd+V worked. |
| Wavetable API (0.6.1) | PASS | Live 10.1 exposes `WavetableDevice`: 12 categories, tables per osc, mono_poly, unison, filter routing, modulation matrix with targets incl. "Pitch". Bug: `unison_voice_count` is the count itself (4 showed as 2) → worked around live, fixed in code (`b247964`). |
| Build v2: Wavetable | PASS | Track 35 "Lead WT": mono, Basics/Saw Dual 1, unison Classic 4 voices, Env 2 → Pitch −0.042 (≈ −2 st glide into every note, 120 ms), Filter 1 LP MS2 1.5 kHz Res 55 % Drive 3 dB, Amp A 60 ms / S −3 dB / R 30 ms. Dorian: "ça se rapproche déjà un peu plus… il manque une modulation sur la wave table". |
| + wavetable movement | PASS | Env 3 → Osc 1 Pos +0.5 (A 120 / D 400 / S 50 %), LFO 1 → Osc 1 Pos +0.15 at 1.5 Hz. Dorian: "on se rapproche… une enveloppe qui bouge un peu sur le filtre". |
| + filter per note | PASS | Env 2 / Random / Velocity → Filter 1 Freq (+0.25 / +0.15 / +0.2). **Dorian: "franchement c'est pas mal. Au moins y a une fondation, y a une base et après, moi, j'ai plus qu'à chipoter".** |

Undo: each build/settings call is one Cmd+Z (track creation = one step). Not exercised this session.

## Findings

1. **basic-pitch is out** (no py3.13 wheels on macOS; 1 note on this gliding lead). pyin + glide merging transcribes it.
2. **Wavetable by default** (Dorian's preference): Analog/Operator sounded basic. The recipe in `create_instrument_track` is now Wavetable-first.
3. **Live 10.1 has `WavetableDevice`**: tables, voices, unison, routing and the modulation matrix are scriptable. Matrix targets include a global "Pitch" (±48 st over ±1 → −0.042 ≈ −2 st), which makes glides from unplayed notes easy.
4. **Display units**: Analog shows "1.5k" and switches "ms" → "s"; `parse_display` now reads both (times compared in ms).
5. **Clips land in Session View**: say so up front and give the Cmd+C / Tab / Cmd+V route.
6. Phase 7 automation on the filter was offered as the next layer; per-note variation (Random/Velocity/Env → filter) was enough for a starting point.

## Sample 2: track 37 "BOS_AA_80_Synth_Arp_Loop_Visions_Counter_C#m" (8 bars, 80 BPM, arp with delay tails)

| Step | Result | Notes |
|---|---|---|
| Analyse | FAIL (tool) / PASS (manual) | `analyze_sample` found the right pitch classes but 1–2 octaves low (E2/E3 instead of E5/G#5), and odd rhythms: delay tails overlap, harmonics dominate pyin. Onsets were a steady 8th grid; a manual onset + harmonic-salience pass (CQT energy that *appears* at each onset) gave a consistent 4-bar pattern (bars 5–8 repeat 1–4): E5 B5 G#4 F#5 B5 E5 B5 B5 / G#4 G#5 B5 D#5 … in C#m/E. |
| Build | PASS | Track 37 "Arp WT": Wavetable poly, Saw Dual 1, unison Classic 2, Filter MS2 1.2 kHz + Env 2/Random → filter (pluck), Amp 2/300/−12 dB/200, Delay (ping-pong; "Ping Pong Delay" isn't a separate device in 10.1) + Reverb 25 %. 64-note clip. |
| Tempo | FIXED by Dorian | Clip twice too fast: the 80 BPM loop plays as 160 BPM in the 175 set, so its 8ths are the set's quarters. Dorian pressed ×2 in the clip; delay moved to a dotted quarter. |
| Lo-fi VHS | PASS | Dorian: "un effet vraiment lo-fi VHS, old school cassette". Added Saturator (+6 dB, soft clip), Redux (10 bit, soft 3), EQ Eight (HP 150 Hz / LP 5 kHz), Vinyl Distortion (tracing 0.15, crackle 0.15), LFO 2 → Pitch wow (0.6 Hz, free-running; raised from 0.004 to 0.008 on request). Dorian switched the table to Saw Harmonics himself. **Dorian: "on n'est vraiment pas très, très loin de l'original. C'est incroyable."** |

## Findings (sample 2)

7. **`analyze_sample` needs a loop/arp mode:** onset-driven notes with harmonic salience instead of pyin, for loops with delay/reverb tails (and octave sanity against the CQT).
8. **Tempo relation:** a loop at half the set's tempo (80 vs 175 → played as 160) doubles every duration. The analysis should report the warped tempo relation and scale the clip (or Claude should ask how Live plays the loop).
9. **A clip-edit command** (scale/replace notes of an existing clip) would have avoided the manual ×2.
10. Live 10.1 has no "Ping Pong Delay" device: it's Delay with Ping Pong on.

## Sample 3: track 35 kick "TSP_SL_kick_bigroller" (not reproducible this way)
Measured: 160 ms, mono, sine body ending ~62 Hz (B1), pitch drop 165 → 62 Hz over ~100 ms, mid "knock" in the first 6 ms. Built as two Wavetable layers (sine + Env 2 → Pitch, band-passed noise click), then Drum Buss, Saturator and a Glue on the group. Dorian: first "kick de tutoriel", then "trop boomy". Verdict: drawing kicks/snares this way isn't viable. A Kick 3-style designer went into the roadmap's future ideas. Live 10 can't create rack chains or group tracks from a script.

## Sample 4: track 35 pad "BOS_AA_80_Synth_Pad_Loop_Visions_C#m" (chords)
- **Chords:** read by hand with a CQT peak analysis per 2 beats (`analyze_sample` is monophonic). Amaj7 → G#m(add11) → C# → G#7sus4, with durations doubled for the 80 → 160 BPM relation. Built as "Pad WT": Wavetable, Saw Dual 2, Shimmer unison, LP 900 Hz, slow attack, Chorus, Reverb 4 s.
- **Composition:** Dorian asked for a 32-bar progression of 8 chords (4 bars each), keeping the 4 original chords and inventing 4 new ones: F#m9 → Emaj7/G# → Amaj7(#11) → G#7(b9). This took two clarifications: a separate 8-bar continuation first, then a 4-phrase plan, both wrong.
- **Bug:** a filter jump at every chord change, from the LFO retriggering on each note. Fixed by turning "LFO 1 Retrigger" Off; the recipe now says so.
- **Dorian: "Fucking amazing pad… It's so freaking good."** (after his own tweaks)
- **Missing:** a command to add a clip to an existing track. Each variant needed a new track with the patch copied over.
