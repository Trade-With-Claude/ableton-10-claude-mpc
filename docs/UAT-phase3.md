# Phase 3 UAT — Mixer & Device Control on a real session (2026-10-14)

Setup: Live 10.1.43, Remote Script 0.3.0 (confirmed via `ping`, 204 ms), Claude Code with the write tools loaded
(each write prompted for permission and was approved by Dorian).
Session: a 172 BPM DnB sketch, saved as a copy: 26 tracks, 2 returns (A-Reverb, B-Delay), master chain
Glue Compressor → Voxengo SPAN → dpMeter5. It has no DRUMS bus, so the batch targeted **20-Group** (a hats group) and the
Glue tests used the **master Glue** instead.

## Results

| # | Tool | Target | Requested | Read back (before → after) | `elapsed_ms` |
|---|------|--------|-----------|----------------------------|--------------|
| 1 | `set_mixer` | track 4 PAD | vol −3 dB, pan 10L, send A-Reverb −20 dB | −3.7 → −3.0 dB, 5R → 10L, −inf → −20.0 dB | 3.0 |
| 2a | `set_device_param` | master Glue | Threshold `-10` (display) | 0.00 → −10.0 dB | 0.9 |
| 2b | `set_device_param` | master Glue | S/C EQ Type `"Bell"` (item) | High pass → Bell | 0.4 |
| 3a | `load_effect` | master | EQ Eight, end | EQ Eight at [3] (after dpMeter5) | 128.6 |
| 3b | `load_effect` | return A | EQ Eight, end | EQ Eight at [1] (after Reverb) | 126.7 |
| 4a | `delete_device` | master [3] | — | EQ Eight deleted | 84.4 |
| 4b | `delete_device` | return A [1] | — | EQ Eight deleted | 93.4 |
| 5 | `apply` (4 ops) | 20-Group + master | vol −8 dB, send B −25 dB, master Glue Threshold −15 dB, load EQ Eight | −5.6 → −8.0, −inf → −25.0, −10.0 → −15.0, EQ Eight at [0] | 110.5 |

All read-backs matched the requested values exactly. `get_session` afterwards confirmed the Test 1 values.

## Undo (AC-3)

- **The batch with a load (Test 5) was fully reverted by ONE Cmd+Z.** Dorian saw volume back at −5.6 dB, the send back at −inf
  and the master Threshold back at −10. `get_session` confirmed that 20-Group has no devices again. `load_item` therefore **does**
  join an open `begin_undo_step`/`end_undo_step`, unlike the Phase 1 spike, which ran without begin/end.
- No separate param-only batch was run. The batch with a load is the harder case, and it already reverted in one press.
- Single-tool calls are each their own undo step, as designed. Test 1's changes were left in place for the user to keep or undo.

## UI / logs

- No UI stutter during any write (Dorian).
- Placement: Dorian saw EQ Eight appear at the end of the master chain and then disappear on delete.
- Selection restore: not explicitly confirmed (it happened too fast to watch).
- No errors in tool results. `Log.txt` was not inspected.

## Findings

1. **Loading onto a folded group unfolds it.** 20-Group was `fold_state: true` before the batch and `false` after.
   Cmd+Z did not refold it, so fold state isn't part of the undo history. Fix: save and restore `fold_state` in
   `_load_effect`, together with the selection (this ties in with the Phase 5 auto-unfold idea).
2. **Auto-named returns rename themselves when devices change.** While EQ Eight was on return A, Live reported its name as
   "A-Reverb | EQ Eight", and it went back to "A-Reverb" after the delete. Sends addressed by return *name* can therefore stop
   resolving after a load or delete on a return. A batch that loads onto a return and sets a send by name may fail
   validation, or worse, resolve against the stale name. Prefer letters/indices for sends (the batch used `"B"`),
   or resolve names at plan time only.
3. **`get_device_params` on a missing device path returns a bare "Error executing tool"** with no message. The
   index-out-of-range error should name the track and the number of devices (Phase 6 error handling).

## Verdict

AC-3 **PASS**. A proposed batch was approved, applied in Live, read back correctly, and reverted with one Cmd+Z,
including a device load. There was no stutter. Findings 1–3 are minor and logged for follow-up.
