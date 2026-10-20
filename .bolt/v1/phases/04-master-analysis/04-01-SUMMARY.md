# SUMMARY — Phase 4: Master Analysis

## Acceptance Criteria Results
| # | Criterion | Result | Notes |
|---|-----------|--------|-------|
| AC-1 | spectrum-advisor has a headless one-shot API, and Qt is optional | PASS | `cd ../spectrum-advisor && uv run pytest -q`: 166 passed (2026-10-20). spectrum-advisor commit 2b45287 |
| AC-2 | `analyze_master` MCP tool wired, resolves the reference | PASS (literal lock check deviates) | `uv run pytest -q`: 85 passed. `analyze_master` allowlisted. `grep -c pyside6 uv.lock` returns **1**, not 0: the hit is spectrum-advisor's `requires-dist` metadata declaring the optional `ui` extra (`marker = "extra == 'ui'"`). No PySide6 package is resolved or installed (`find_spec('PySide6')` is None). The intent (no Qt pulled in) holds |
| AC-3 | Claude reports on a real drop, consistent with dpMeter5 | PASS (dpMeter5 compared by eye) | `docs/UAT-phase4.md`: a full report (LUFS-I/S, TP, PLR, zones incl. sub, stereo, diagnoses) on runs with and without a reference. No stutter. Stopped playback → the clear `No signal on BlackHole 2ch…` error. dpMeter5 agreement was confirmed by Dorian by eye ("around the same average"), not as a numeric ±1 LU / ±1 dB check. Runs 1/2/4 agree with each other within 0.35 LU |

## Task Results
| # | Task | Result | Notes |
|---|------|--------|-------|
| 1 | spectrum-advisor one-shot API + Qt split | PASS | spectrum-advisor commit 2b45287 |
| 2 | `analyze_master` MCP tool | PASS | commit cbe8e4a |
| 3 | Live UAT on a real drop | PASS | `docs/UAT-phase4.md` (2026-10-16) |

## Deviations
- **Reference was a given path, not the last-used one.** spectrum-advisor had no last-used reference, so run 1 resolved to none and Dorian gave an mp3 path. The `last_used` branch is covered by unit tests only.
- **The UAT turned into a real mixing session.** Claude proposed and applied mix batches from the analysis (ATMO −4 → −1 dB, MIDS EQ 359 Hz → +1.5 dB, kHs Limiter output → −1 dB, then MIDS EQ band 3 → 750 Hz +2.5 dB, Q 1). Re-analysis measured the effect: low_mid vs ref −2.66 → −0.44 dB, TP +0.29 → −0.24 dBTP. This is a preview of the Phase 5 workflow, and it worked.
- **One invalid capture (run 3)** started before Dorian had restarted playback. It's excluded from the results and drives finding 3.
- **Bug found in Phase 3 code:** `apply` with `display: -1` on a third-party plugin param shown with a U+2212 minus (kHs Limiter `Output gain`) set the minimum (−20 dB) instead. Stock devices are unaffected. Dorian corrected it by hand; nothing was harmed (it only made the output quieter).
- **Findings for later phases** (details in `docs/UAT-phase4.md`):
  1. The 20 Hz and 40 Hz bands are always empty (FFT 4096 @ 48 kHz = 11.7 Hz bins); per-band readings below ~60 Hz are unreliable → spectrum-advisor fix
  2. Partly-silent captures give wrong reference deviations → detect and reject
  3. Capture start depends on Dorian's timing → `analyze_master` should start playback (Remote Script) → Phase 5
  4. The pump score is unstable on the same loop (0 / 4 / 8.5 / 0) → advisory only
  5. The U+2212 display parser bug in `apply` → fix soon (Phase 5 relies on plugin params)
  6. mp3 references are weak (+2.7 dBTP, band-limited)
  7. Reference from a "Reference" track in the Live set (Dorian's idea) → Phase 5
  8. Rack chain mixer is not readable, and `load_effect` can't insert into rack chains → Phase 5
  9. The stereo metrics never moved (corr 0.95–0.96) and haven't been cross-checked against SPAN or a soloed source
- No code changes in Task 3; it added only `docs/UAT-phase4.md`.

## Phase Complete?
YES. All 3 ACs pass, two with caveats stated above (the lock-check wording and dpMeter5 by eye). Claude hears the master on demand and turns the analysis into concrete, measurable mix changes. Nine findings are logged, mostly for Phase 5.

## Next Action
Run `/bolt:plan 5`
