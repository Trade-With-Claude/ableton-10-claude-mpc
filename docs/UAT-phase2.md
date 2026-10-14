# Phase 2 UAT — Session Read on a real DnB session (2026-10-14)

Setup: Live 10.1.43, Remote Script 0.2.0 (confirmed via `ping`), Claude Code with the new tools loaded.
Session: Dorian's DnB project, 172 BPM.

## Numbers

| Metric | Value |
|--------|-------|
| Tracks / returns | 39 / 2 (+ master) |
| Groups | 6 (DRUMS, TOPS nested in DRUMS, BASS, ATMO, FX, VOCALS) |
| `get_session` `elapsed_ms` (inside Live) | 32.5 ms |
| `get_session` response size | 58.1 KB (Claude Code saved it to a file instead of showing it inline) |
| `ping` MCP round trip | 193.6 ms |
| `get_meters` 20 reads × 100 ms | ~2 s window, no errors |
| LOM errors | none seen in tool results |

## get_session

- Group nesting (`group_index`), output routing (children → their group, groups/returns → Master),
  fold state, mute/solo, volume/pan display, sends and device chains were all read correctly.
- Racks are walked recursively: WET/DRY chains on the LAYER 1 tracks, Valhalla inside a rack on PADS/FX.
  Paths like `[2, 0, 4]` are reported.
- Names: long sample names with brackets and dates (`[2026-09-07 152001]`) come through intact.
  The session has no non-ASCII names, so Unicode was not exercised here (the fake-LOM tests cover it).
- Duplicate names exist (2× "LAYER 1", 2× "PADS"), so writes must address tracks by index, not by name.
- All sends are at −inf; the returns (A-Reverb, B-Delay) are unused.
- **Size:** 58 KB for 39 tracks is heavy for context. Phase 3 should consider a compact mode
  (no sends at −inf, no colors) or a per-group filter.

## get_device_params

| Device | Kind | Params | Notes |
|--------|------|--------|-------|
| Glue Compressor (master [0]) | stock | 17 | value/min/max/display/value_items all populated; display strings are useful ("4", "30", "200 Hz", "High pass") |
| kHs Limiter (master [1]) | VST plugin | 5 | all exposed; display strings in dB/ms |

How many parameters plugins expose varies a lot: dpMeter5 has 58, Valhalla 18–19, Serum 2 / Kontakt 8 / Splice only 1–2
(AU plugins expose only the parameters configured in Live).

## get_meters (drop playing)

**Finding: tracks inside a folded group always read 0.0.** Live only updates meters for visible tracks.

| Track | Groups folded | Groups unfolded |
|-------|---------------|-----------------|
| Master | 0.921 / 0.921 | 0.921 / 0.921 |
| DRUMS (group) | 0.914 / 0.914 | 0.914 / 0.914 |
| KICK | 0.0 / 0.0 | 0.890 / 0.890 |
| SNARE | 0.0 / 0.0 | 0.860 / 0.863 |
| TOPS (nested group) | 0.0 / 0.0 | 0.844 / 0.832 |
| BASS (group) | 0.915 / 0.886 | 0.887 / 0.896 |
| SUB | 0.0 / 0.0 | 0.796 / 0.796 |
| LAYER 1 (#18) | 0.0 / 0.0 | 0.839 / 0.848 |
| PIANNO | 0.0 / 0.0 | 0.755 / 0.712 |

- Top-level groups and the master meter correctly either way. TOPS (nested in DRUMS) read 0 while folded.
- The values are on Live's raw meter scale (0–1, non-linear, not dBFS). They're fine for ranking which tracks are hot relative
  to each other. They're **not** usable as absolute levels for gain staging.
- Master L/R peaks are identical in both runs (0.92105…), so they are probably held at the kHs Limiter ceiling.

**Implications for Phase 5 (gain staging):**
1. Unfold groups before reading per-track meters. The tool docstring and note now say so. Phase 3 could
   unfold automatically via `track.fold_state` (it is writable), then restore the fold state.
2. Map Live's meter scale to dB (calibrate against a known test tone) or rely on
   `analyze_master`/solo captures (Phase 4) for real dBFS/LUFS values.

## Verdict

Phase 2 tools work on a real 39-track session. One limitation was found and documented (meters of folded
tracks read 0.0). No code bugs. Dorian confirmed that the session description (bus structure, device chains, master chain) matches Live. **PASS**.
