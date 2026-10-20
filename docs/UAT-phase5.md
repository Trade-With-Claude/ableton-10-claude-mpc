# Phase 5 UAT — Workflow Foundations (2026-10-20)

Setup: Live 10.1.43, Remote Script 0.4.0 (`scripts/install.sh`, Live restarted), MCP server reloaded via `/mcp` →
Reconnect (no Claude Code restart needed). Output on BlackHole 2ch @ 48 kHz. Same 175 BPM DnB session as Phase 4
(33 tracks, groups DRUMS / BASS / ATMO / FX, 2 returns).

`ping`: `script_version` 0.4.0, `is_playing: false`, rtt 159 ms.

## Results

| # | Step | Call | Result | Timing |
|---|------|------|--------|--------|
| 1 | Typographic minus | `set_device_param(master [3] kHs Limiter, "Output gain", display=-2)` | `−1.04 dB` → **`−2.00 dB`** (not −20). Restored with raw `value` 0.47404780983924866 → `−1.04 dB` | 2.2 ms |
| 2 | Autoplay | `analyze_master(15)`, Live stopped, loop on the drop | `autoplay: "started"`, `silence_fraction: 0.0`, kick onsets 91, −8.10 LUFS-I / −7.97 LUFS-S, −0.24 dBTP, PLR 7.86. `ping` after: `is_playing: false`. Dorian saw playback start and stop by itself | `elapsed_s` 16.6 |
| 3 | Partial silence | `analyze_master(15)`, Dorian pressed stop ~3.5 s in | `AnalysisError`: "76% of the capture is silent — playback started late or stopped, or the loop contains a breakdown…" — no report | — |
| 4a | Chain mixer read | `get_session` | MIDS (track 16) Chorus rack chain `[0,0,4,0]`: volume `−10.2 dB`, pan `C`; Valhalla rack chain `−21.5 dB`; DRUMS rack chain `−19.6 dB` | 31 ms |
| 4b | Chain mixer + load into chain, one batch | `apply([chain_mixer [0,0,4,0] volume_db −13.2, load_effect EQ Eight chain [0,0,4,0] position 0])` | `−10.2 → −13.2 dB`; EQ Eight at chain position 0, **left of the Chorus** (Dorian checked). **One Cmd+Z** reverted both (read back: chain `−10.2 dB`, devices `[Chorus]`) | 227 ms |
| 5a | Fold, track in folded group | `load_effect(SUBS, Utility)` with BASS folded | BASS stayed folded; Utility at `[4]` | 183 ms |
| 5b | Fold, folded group itself | `load_effect(FX, Utility)` with FX folded | FX stayed folded; Utility at `[2]` | 164 ms |
| 5c | Undo re-check | `load_effect(SUBS, Utility)`, then one Cmd+Z with Live focused | Utility gone after **one** Cmd+Z (SUBS back to 4 devices) | 202 ms |

- **Stutter:** none (Dorian).
- **Placement:** no misplaced device; the nested-chain insert (plan risk 1) works in Live 10.1.43.
- 4b also covered fold state: MIDS is inside BASS, which was folded and stayed folded.

## AC-3

| Criterion | Result |
|-----------|--------|
| kHs Limiter `display` with U+2212 reads back correctly | PASS (tested at −2 dB, since the value was already −1.04) |
| Autoplay from stopped: starts, clean report (`silence_fraction` ≈ 0, ~90 kick onsets), stops | PASS |
| Stop mid-capture → partial-silence error | PASS (76 %) |
| Chain `volume`/`pan` in `get_session` | PASS |
| One batch: chain volume + EQ Eight at chain position 0, before the Chorus; one Cmd+Z reverts both | PASS |
| Loads keep groups folded (track in folded group, folded group itself) | PASS |
| No UI stutter | PASS |

## Findings

1. **Cmd+Z needs Live focused.** In 5a/5b, Dorian's Cmd+Z presses after each load didn't reach Live (the Utilities
   were still there when read back), and it took two later presses to remove them. A controlled re-test (5c) confirmed
   that one load = one undo step. When asking Dorian to undo, say "click in Live first", and read back afterwards.
2. **No last-used reference** in spectrum-advisor this session (`reference_used: null`), so step 2 ran without one.
   It doesn't affect the autoplay or silence checks.
3. **`/mcp` → Reconnect is enough** to load new MCP server code; a full Claude Code restart isn't needed.
4. Both parallel racks on MIDS (Chorus, Valhalla) are currently switched **off**. That's Dorian's state, noted only
   because 4b was inaudible.
