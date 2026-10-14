# Phase 1 Spikes — Live 10.1.43 (2026-10-14)

Setup: macOS 15, Apple Silicon M4, Live 10.1.43, ClaudeMPC selected in one Control Surface slot
(Input/Output = None). The Live log confirms `ClaudeMPC: listening on 127.0.0.1:9879`.

## 1. Round-trip latency / stability (threadless loop)

`uv run python scripts/spike_latency.py ping -n 100`

| n | ok | errors | p50 | p95 | max | min |
|---|----|--------|-----|-----|-----|-----|
| 100 | 100 | 0 | 99.9 ms | 101.4 ms | 215.8 ms | 98.4 ms |

- Latency is one `update_display()` tick (~100 ms), as designed. The max of ~216 ms is one missed tick.
- No UI stutter in Live during the burst (Dorian observed).
- Throughput: ~10 sequential round trips/s, up to `max_commands_per_tick=8` pipelined requests per tick.
  **Implication:** batch writes (`apply`) are preferable to many single commands.

## 2. Loading a stock effect onto master / return

`uv run python scripts/spike_latency.py load master` / `load return 0` (command `spike_load_effect`):, Utility via `browser.audio_effects`,
`hotswap_target = None`, `track.view.device_insert_mode = selected_right`, then `browser.load_item`.

| Target | Loaded | Placement | Selection restored | Elapsed |
|--------|--------|-----------|--------------------|---------|
| Master | yes | end of chain (after Glue Compressor, Voxengo SPAN, dpMeter5) | yes | 245 ms |
| Return A | yes | end of chain (after Reverb) | yes | 221 ms |

- Setting `device_insert_mode` raised no error.
- Cmd+Z ×2 removed both Utilities, leaving the existing devices untouched (Dorian observed).
- Each `load_item` is its own undo step.

## Verdict

**GO** for the Phase 3 `load_effect` approach: select the target track, clear hotswap, insert
`selected_right`, `load_item`, then restore the selection. It works on master and returns.

Open points for Phase 3:
- Placement follows the selected device. To guarantee "append at end", select the last device (or none) before loading, or use `selected_left`/index logic for "insert before X".
- Undo across a multi-command `apply` batch still needs to be verified (Live may create one step per change).
- The audio-effects cache is keyed on top-level browser names (e.g. "EQ Eight", "Glue Compressor").
