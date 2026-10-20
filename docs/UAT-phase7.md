# UAT — Phase 7: Automation from Vibes

Date: 2026-10-20 · Live 10.1.43 · 175 BPM · Remote Script 0.5.0 → 0.5.1
Target: track 33 "test" (audio, TSP_SL_172_synth_lead_tension_F#), Auto Filter [0] → Frequency (raw 20..135)

## Results

| Step | Result | Notes |
|---|---|---|
| Pre-build spike | PASS | 5 `set_device_param` calls with Automation Arm + Arrangement record → stepped curve recorded. Live 10 records script-made param changes. |
| 1. Test take (0.5.0) | PASS with fixes | exp 300 Hz → 12 kHz, bars 65–69: `done`, 56 points, mean tick 101.2 ms, 5.9 s. Curve starts on bar 65 and tops out at 69. Automation Arm off and playhead back on 65 afterwards. **One Cmd+Z removes the whole take.** Two defects found (below), fixed in 0.5.1. |
| 1b. Test take (0.5.1) | PASS | Same curve: `done`, 55 points / 70 ticks (15 pre-roll ticks write nothing), 7.4 s, mean tick 101.7 ms. Value before bar 65 keeps its original value. Cursor read from `ping.position_bar` (65), not dictated. |
| 2. Vibe "pluck" | PASS | Dorian: "fais une courbe d'automation en mode pluck". Translated into 8 `log` segments of 1/2 bar, 6 kHz → 400 Hz (jump up, fast decay). 54 points, 7.2 s. Dorian: "parfait". |
| 3. Vibe dip + wobble | PASS | One lane, 4 segments: log dip 12 kHz → 300 Hz (½ bar), exp back up, sine 800 Hz ↔ 5 kHz at 1/2 bar over 66–68, exp 800 Hz → 12 kHz. 54 points, 7.2 s. Dorian: "tout fonctionne". |
| 4. Stop in Live mid-take | NOT RUN LIVE | Dorian closed the UAT after step 3. Covered by `test_stop_in_live_aborts_and_restores` and the server abort tests only. |

Vibe 1 as planned (ATMO filter over 16 bars) was replaced by Dorian's own vibe ("pluck") on the test track; the
16-bar ramp breakpoint count was not measured. Two lanes in one take was unit-tested only (the live vibes used one
lane with several segments).

## Findings

1. **Setting `current_song_time` while stopped doesn't move the playback start.** Live plays from the insert marker.
   0.5.0 had no pre-roll in practice (elapsed 5.9 s = 4 bars, points == ticks). Fix (0.5.1): jump the playhead on the
   first tick where `is_playing` is true.
2. **Pre-writing the param before punch-in leaks into the lane.** Live keeps the param's value at punch-in for the part
   of the lane before it, so the curve read 300 Hz before bar 65. Fix (0.5.1): no write before punch-in.
3. **`ping` reports `position_bar`** (0.5.1) so "start where my cursor is" works without Dorian reading bar numbers.
4. Tick interval ≈ 101–103 ms (~10 Hz), about 3 points per beat at 175 BPM. ½-bar plucks/LFOs (~7 points per cycle)
   read clearly; faster ones belong on a device LFO or envelope.
5. Track 28 was not re-armed after take 1 — most likely already disarmed by Dorian during the spike (snapshot only
   restores tracks that were armed at start). Dorian: not important.
6. One take = one Cmd+Z (Live focused), same as Phase 3/5 batches.
