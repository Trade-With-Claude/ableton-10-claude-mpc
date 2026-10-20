# SUMMARY — Phase 7: Automation from Vibes

## Acceptance Criteria Results
| # | Criterion | Result | Notes |
|---|-----------|--------|-------|
| AC-1 | Curves and the recorder work against the fake LOM | PASS | `uv run pytest tests/test_curves.py tests/test_recorder.py tests/test_py27_compat.py -q`: 50 passed (2026-10-20) |
| AC-2 | `record_automation` MCP tool | PASS | `uv run pytest -q`: 173 passed (2026-10-20), including the Phase 1–5 tests |
| AC-3 | Live UAT: recorded automation on Dorian's session | PARTIAL | `docs/UAT-phase7.md`. Done: script changes are recorded as Arrangement automation, mean tick 101–103 ms, the curve starts on the bar line, one Cmd+Z removes a take, and two vibes were recorded and approved by ear ("pluck" → "parfait"; dip + ½-bar sine wobble → "tout fonctionne"). After each take, Automation Arm, the loop and the playhead were back as before. Not done live: stop mid-take (abort), a 16-bar ramp breakpoint count, ATMO (Dorian chose his own vibe on the test track), two lanes in one take (unit-tested only), and a check that track 28 is re-armed (it was most likely already disarmed before the take). |

## Task Results
| # | Task | Result | Notes |
|---|------|--------|-------|
| 1 | Remote Script: curves, recorder, commands (0.5.0) | PASS | commit 72f0b8f |
| 2 | MCP server: `record_automation` tool + docs | PASS | commit 9dbe16d |
| 3 | Live UAT | PASS (with gaps, see AC-3) | commits 0d59493 (0.5.1 fixes), ec74ea1 (`docs/UAT-phase7.md`) |

## Deviations
- **Remote Script 0.5.1, found during the UAT:**
  - The pre-roll now jumps the playhead on the first tick after playback starts. Setting `current_song_time` while Live is stopped doesn't move the start: Live plays from the insert marker.
  - Params are not written before the punch-in. Live keeps the value at punch-in for the part of the lane before it, so pre-writing changed the curve before the take.
  - `ping` now reports `position_bar`, so Claude can start "from my cursor".
  - The AC-1 plan text ("sets each param to its curve value at start_bar, moves the playhead before playing") no longer describes the code.
- **Vibe 1:** Dorian's "pluck" on track 33 "test" replaced the planned 16-bar ATMO opening. Vibe 2 was done on the same track.
- **Pre-build spike:** done before the build, with `set_device_param` on the test track. It de-risked the plan, and the fallback (clip envelopes) wasn't needed.
- **Abort test (UAT step 4):** not run live. Dorian closed the UAT after the two vibes. It is covered by unit and server tests only.
- No files changed outside the plan, apart from the `ping` addition in `commands.py` and `server.py`, which were already in the plan's file lists.

## Phase Complete?
YES, accepted by Dorian with the AC-3 gaps (2026-10-20). The goal is met in practice. Dorian describes a movement, Claude turns it into curves and records them as real, editable Arrangement automation, and one Cmd+Z removes a take. Dorian waived the live stop-mid-take test ("je pense pas qu'il y ait besoin de tester ça"). Abort stays covered by unit and server tests.

Intended use (Dorian): put the cursor on the start point and ask for automation over 4, 8 or more bars, up to a whole sample. Live 10 can't read Arrangement clip lengths (`arrangement_clips` came with Live 11), so Dorian gives the bar count. A take lasts in real time: 16 bars ≈ 22 s at 175 BPM.

## Next Action
Run `/bolt:plan 8`
