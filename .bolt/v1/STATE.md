# STATE

## Current Position
- **Phase**: 5 (Workflow Foundations)
- **Plan**: created (05-01-PLAN.md)
- **Task**: 2/3 (Task 3 = Live UAT, Remote Script 0.4.0 installed, waiting on Dorian)
- **Status**: building

## Progress
<!-- Updated after each /bolt:close -->
- Phase 1 (Bridge Foundation): complete, 4/4 ACs PASS (2026-10-14). MCP ping 152.6 ms from real Live 10.1.43; raw p50 ~100 ms.
- Phase 2 (Session Read): complete, 3/3 ACs PASS (2026-10-14). Real 39-track session read in 32.5 ms (58 KB). Meters of tracks in folded groups read 0.0; Live's meter scale isn't dB.
- Phase 3 (Mixer & Device Control): complete, 3/3 ACs PASS (2026-10-14). 4-op batch incl. EQ Eight load applied in 110 ms, reverted by ONE Cmd+Z. Findings: load unfolds groups (fold not restored), auto-named returns rename on device change, bare error on missing device path.
- Phase 4 (Master Analysis): complete, 3/3 ACs PASS (2026-10-20; AC-2 lock-grep hit is extra metadata only, AC-3 dpMeter5 by eye). Real drop analysed in 16.5 s; analysis-driven batch measurably closed the 250–500 Hz gap vs reference. 9 findings in docs/UAT-phase4.md.

## Recent Decisions
<!-- Last 3-5 decisions, older ones move to PROJECT.md -->
- One `apply` = one Cmd+Z, and `load_item` joins the undo step, so DnB chain presets (Phase 5) should be single batches
- Address sends by letter/index, not return name (auto-named returns rename when their devices change)
- Restore `fold_state` in `_load_effect` + auto-unfold for meters, in Phase 5
- Per-track meters require unfolded groups
- On-demand `analyze_master` tool built on spectrum-advisor; spectrum-advisor to be made public (pending)
- Roadmap split (2026-10-20): Phase 5 = Workflow Foundations (UAT-4 fixes), Phase 6 = DnB Workflow, Phase 7 = Polish & Release
- `analyze_master` autoplays + rejects partly-silent captures (Phase 5); "Reference" track deferred (Live 10 has no arrangement-clip API)
- Fix `apply` display parsing for plugin params using U+2212 minus (use `value` for third-party plugins until then)

## Blockers
<!-- Anything preventing progress -->

## Next Action
<!-- Exactly ONE suggested next action -->
Restart Live (loads Remote Script 0.4.0) + restart Claude Code, `/bolt:resume`, then continue `/bolt:build 5` Task 3 (UAT)
