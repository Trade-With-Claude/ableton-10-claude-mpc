# SUMMARY — Phase 8: Sound Reproduction

## Acceptance Criteria Results
| # | Criterion | Result | Notes |
|---|-----------|--------|-------|
| AC-1 | Sample analysis gives notes, rhythm and a synth recipe | PASS | `uv run pytest tests/test_sound.py -q`: 15 passed (2026-10-20). On the real test sample it finds the A#4 / F#5 / C#6 arpeggio on beats 1, 2.5 and 4 with glides, in F# major, saw-ish, with a resonant peak around 1.47 kHz and a wide image. It flags an `octave_check` on 2 notes. |
| AC-2 | Build an instrument track in Live from MCP | PASS | `uv run pytest -q`: 222 passed (2026-10-20). `create_instrument_track` builds a MIDI track, a stock instrument and a session clip as one undo step (1.3 s in Live; 0.4 s for 64 notes). The recipe in the docstring is Wavetable-first. |
| AC-3 | Live UAT: the test sample reproduced | PASS | `docs/UAT-phase8.md`. The test lead was rebuilt on Wavetable with Env 2 → Pitch glides, wavetable movement and per-note filter variation. Dorian: "y a une fondation, y a une base et après, moi, j'ai plus qu'à chipoter". The Analog v1 was "vraiment basique". |

Bonus beyond the ACs: a second sample, the track-37 arp loop with a lo-fi VHS chain. Dorian: "on n'est vraiment pas très, très loin de l'original. C'est incroyable." It needed a manual transcription; see deviations.

## Task Results
| # | Task | Result | Notes |
|---|------|--------|-------|
| 1 | Sample analysis (`sound.py`) + `analyze_sample` | PASS | commit 6fbf3d5 |
| 2 | Remote Script 0.6.0 `create_instrument_track` + MCP tool | PASS | commit 9882c70 |
| 3 | Live UAT | PASS | commits 65b526a and 6096c2b (`docs/UAT-phase8.md`) |

## Deviations
- **Extra scope, Remote Script 0.6.1 (commit 9f2986a):**
  - **Why:** Dorian asked to always use Wavetable, and its tables, voices and modulation matrix aren't device parameters.
  - **What:** new tools `get_wavetable` (read-only, allowlisted) and `set_wavetable` (write), built on Live 10.1's `WavetableDevice` API; new files `remote_script/ClaudeMPC/wavetable.py` and `tests/test_wavetable.py`. The tables, mono, unison, routing and modulation matrix are scriptable.
- **UAT bugs fixed:**
  - **Display parsing:** `parse_display` now reads Analog's "1.5k" and the "ms" → "s" switch. Attack/Release had landed on 15 s.
  - **Unison voices:** `unison_voice_count` is the voice count itself, so 4 voices showed as 2 (commit b247964).
  - Both fixes are installed. The unison fix loads on the next Live restart; until then reads still carry the `api` list and the old voice mapping.
- **Unexpected dependency:** basic-pitch, which the roadmap suggested, was ruled out during research: no Python 3.13 wheels on macOS, and it found 1 note on a gliding lead. pyin is used instead.
- **Clip transcription, sample 1:** the clip was cleaned by hand into one consistent pattern. The tool transcribed an E5 grace note in bars 1–2.
- **Second sample (arp loop):**
  - `analyze_sample` got the octaves (1–2 low) and the rhythm wrong. The transcription was redone ad hoc (onsets + CQT harmonic salience), outside the tool.
  - The 80 BPM loop plays at 160 in the 175 set, so the clip was twice too fast. Dorian fixed it with ×2 in Live.
- **Delay in Live 10.1:** "Ping Pong Delay" is not a device there; it is Delay with Ping Pong on.
- **The clips land in Session View:** Dorian needed the Cmd+C / Tab / Cmd+V route. It's saved as a feedback memory.

## Follow-ups (to plan)
1. `analyze_sample` loop/arp mode: onset-driven notes with harmonic salience, plus an octave sanity check.
2. Tempo relation for loops: detect half/double time against the set and scale the clip.
3. A clip-edit command: scale, replace or transpose the notes of an existing clip.
4. Optional: let Claude load a stock effect by alias (e.g. "Ping Pong Delay" → Delay with Ping Pong).

## Phase Complete?
YES. Dorian points at a sample and Claude builds a usable starting point: notes, a Wavetable patch with modulation, and effects. He confirmed it on both samples. Loops and arps still need the follow-ups above to work without hand transcription.

## Next Action
Run `/bolt:plan 9`
