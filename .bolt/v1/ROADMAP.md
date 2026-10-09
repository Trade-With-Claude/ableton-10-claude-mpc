# ROADMAP

## Phases

### Phase 1: Bridge Foundation
- **Goal**: Threadless Py2.7 Remote Script running in Live 10, talking end-to-end to a Py3.13 MCP server.
- **Requirements**:
  - [ ] R1: uv project with FastMCP server skeleton + pytest fake-Live socket stub
  - [ ] R2: Remote Script with `_Framework` ControlSurface, non-blocking `select()` loop in `update_display()`, newline-JSON protocol `{id, cmd, params}`, buffered partial-write send
  - [ ] R3: `ping` command + MCP tool; install script that copies to the User Library
  - [ ] R4: py2.7 syntax guard (vermin or similar) in tests
  - [ ] R5: Spikes: round-trip latency/stability; load stock FX onto master and onto a return
- **Success Criteria**: `ping` from Claude Code returns from real Live 10 in ~200 ms, Live UI stays smooth, spike results documented.
- **Status**: pending

### Phase 2: Session Read
- **Goal**: Claude can see the whole session.
- **Requirements**:
  - [ ] R1: `get_session`: tracks, groups (fold/group_track), returns, master, mixer state, device list
  - [ ] R2: `get_device_params`: value/min/max/quantized/`str_for_value` (stock + 3rd-party)
  - [ ] R3: `get_meters`: one-shot output peak L/R per track
  - [ ] R4: Unicode-safe serializers + kind/index addressing
- **Success Criteria**: Claude accurately describes one of Dorian's real DnB sessions: bus structure and all device params.
- **Status**: pending

### Phase 3: Mixer & Device Control
- **Goal**: Claude changes the mix, and every change can be undone.
- **Requirements**:
  - [ ] R1: `set_mixer` (volume/pan/sends/mute/solo) on tracks, returns, master
  - [ ] R2: `set_device_param` by name or index, with range clamping
  - [ ] R3: `load_effect` (stock, cached browser lookup, selection restored) + `delete_device`
  - [ ] R4: Batch `apply` = one undo step; read tools allowlisted, write tools prompt
- **Success Criteria**: A proposed batch is approved, applied in Live, and reverted with one Cmd+Z.
- **Status**: pending

### Phase 4: Master Analysis
- **Goal**: Claude "hears" the master on demand.
- **Requirements**:
  - [ ] R1: spectrum-advisor: `capture.record()` + `oneshot.analyze_buffer()`; Qt moved to `[ui]` extra
  - [ ] R2: `analyze_master(seconds=15, reference=None)` MCP tool via `asyncio.to_thread`; reference fallback arg → last-used → none
  - [ ] R3: Strict 48 kHz check, clear errors when BlackHole is missing
- **Success Criteria**: Dorian plays a drop; Claude reports LUFS-I/S, TP, PLR, spectrum balance, sub, stereo, and a diagnosis.
- **Status**: pending

### Phase 5: DnB Workflow
- **Goal**: One-command mixing helpers built on phases 2–4.
- **Requirements**:
  - [ ] R1: Chain presets (kick clip, drum bus glue, bass bus, master chain) as proposable batches
  - [ ] R2: Auto gain staging toward the mix-bus target (−5/−6 LUFS-S) using meters + analysis
  - [ ] R3: Teaching explanation attached to every proposed change
- **Success Criteria**: "Set up my drum bus" proposes, explains and applies a chain; a re-analysis shows the mix moving toward the target.
- **Status**: pending

### Phase 6: Polish & Release
- **Goal**: Robust, documented, ready to open source.
- **Requirements**:
  - [ ] R1: Reconnect/timeout handling; graceful errors when Live is closed or the surface isn't selected
  - [ ] R2: README (install, Control Surface slot, BlackHole setup) + MIT attribution to ahujasid
  - [ ] R3: Full UAT pass in a real session; spectrum-advisor made public
- **Success Criteria**: A fresh install by following the README works first time.
- **Status**: pending
