# PROJECT — Ableton 10 Claude MPC

## What
An MCP bridge that lets Claude (chatting in Claude Code, in the terminal) see and control a running **Ableton Live 10.1.43 Suite** session, to help mix and master Dorian's DnB tracks. Claude reads the session (tracks, groups, returns, devices, parameters, mixer state). It controls the mixer (volume, pan, sends, mute/solo), loads **stock Ableton effects** and tweaks their parameters. It can also "hear" the master through an on-demand analysis tool built on **spectrum-advisor** (BlackHole capture → LUFS, spectrum, sub, stereo, diagnosis).

## Why
Dorian is an experienced DnB producer whose multi-year blocker is getting a clean, loud, commercial mix (target −4 LUFS-I, range down to −6; mix bus ≈ −5/−6 LUFS-S before the master). He mixes on SRH440 headphones, which hide the sub. Existing Ableton MCP servers target Live 11/12 (Python 3 remote scripts). **Live 10 runs its remote scripts on embedded Python 2.7**, so nothing works out of the box for his setup. This project gives him a mix engineer that acts directly in his DAW and explains what it does.

## Scope — v1
- **Read session**: tracks, groups/buses, returns, master, device chains, parameter values, mixer state (and output meters if exposed).
- **Mixer control**: volume, pan, sends, mute/solo, returns, master.
- **Load stock effects**: EQ Eight, Glue Compressor, Compressor, Saturator, Limiter, Utility, Multiband Dynamics, etc. on any track/bus/return/master.
- **Set device parameters**: any stock *or* third-party device (third-party plugins are read and tweaked via their exposed params, but never loaded by Claude).
- **Analyze master (on demand)**: MCP tool captures N seconds via BlackHole while Dorian plays the section, runs spectrum-advisor analysis, and returns LUFS-I/S, TP, PLR, spectrum balance, sub/low-mid issues, stereo and diagnosis.
- **DnB workflow helpers**: bus-level mixing, one-command DnB chain presets (kick clip, drum bus glue, bass bus, master chain), automatic gain staging toward the mix-bus target, and a teaching explanation for every change.

## Out of scope — v1
- Loading third-party plugins
- MIDI/clip composition and arrangement editing
- Live 11/12 support
- Continuous (streaming) audio monitoring; analysis is on demand only

## Interaction model
- Chat in the terminal via **Claude Code**, which is the MCP client.
- **Propose → confirm → apply**: Claude states the planned changes, Dorian approves, then Claude applies them. Changes stay undoable in Live (Cmd+Z).
- Explanations are pedagogical: *why* each move is made, in terms of loudness, mud, sub and masking.

## Stack
- **Remote Script** (inside Live 10): written from scratch, Python **2.7**, `_Framework` ControlSurface, **threadless**: non-blocking `select(timeout=0)` socket I/O and all LOM calls in `update_display()` (~100 ms main-thread tick). Borrows the browser walk and serializers from ahujasid/ableton-mcp (MIT, keep attribution). Installed at `~/Music/Ableton/User Library/Remote Scripts/<Name>/`, selected in a free Control Surface slot (2–6; slot 1 = Launchkey_MK3).
- **MCP server** (outside Live): Python 3.13 + `mcp` SDK (FastMCP), managed with `uv`.
- **Analysis**: `spectrum-advisor` as an editable path dependency (`../spectrum-advisor`) without the Qt extra: librosa, pyloudnorm, sounddevice, BlackHole 2ch.
- **Tests**: pytest with a fake-Live socket stub for the MCP server, plus manual UAT in real Live 10 sessions.
- Platform: macOS 15, Apple Silicon M4, 16 GB.

## Architecture
```
Claude Code (terminal chat)
   │  MCP (stdio)
   ▼
MCP server (Py 3.13, uv) ──── spectrum-advisor (BlackHole capture + analysis)
   │  TCP JSON (localhost)
   ▼
Remote Script in Live 10 (Py 2.7, _Framework)  →  Live Object Model (song/tracks/devices/mixer)
```

## Protocol & command set
- TCP localhost, newline-delimited JSON. Request `{id, cmd, params}`; response `{id, ok, result|error}`. Buffered non-blocking send with partial-write handling (the known bug in PR #103's `sendall`).
- Addressing: `{"kind": "track|return|master", "index": n}`; group-aware (`is_foldable`, `group_track`).
- ~10 commands: `ping`, `get_session` (tracks/groups/returns/master + mixer + device list), `get_device_params` (value/min/max/quantized/`str_for_value`), `set_mixer` (volume/pan/sends/mute/solo), `load_effect` (stock by name → browser `audio_effects`), `set_device_param` (by name or index), `get_meters` (one-shot `output_meter_left/right`), `delete_device`, and a batch `apply` that runs one undo step per batch.
- MCP tools mirror these, plus `analyze_master(seconds=15, reference=None)`.

## spectrum-advisor integration
- Add to spectrum-advisor: `audio.capture.record(seconds, device="BlackHole 2ch", sr=48000)` (blocking `sd.rec`) and `analysis/oneshot.py: analyze_buffer(frames, sr, ref=None, mode="coach") -> dict` (LiveAnalyzer + direct `analyze_transients`/`compute_pump_score` + `generate_diagnoses`/`diagnoses_to_text` + JSON sanitising).
- Split `pyside6` and `pyqtgraph` into `[project.optional-dependencies] ui`; gate `tests/test_imports.py`.
- Reference: tool argument → else `~/.config/spectrum-advisor/session.json` `last_reference_path` → else no reference (DnB absolute targets only; spectrum diagnoses need a reference).
- MCP runs the capture via `asyncio.to_thread`. Default 15 s, min 10 s (LRA needs 30 s).

## Constraints
- Live 10.1.43 only, with embedded Python 2.7 in the Remote Script (no f-strings, no py3-only stdlib).
- **Live 10 threads are GIL-starved** (PR #103, tested on 10.1.43: socket thread waits 60–90 s) → no threads in the Remote Script; everything happens in `update_display()`.
- ~100 ms tick → ~10 commands/s; batch per tick; keep `update_display` work short (it freezes the Live UI); cache the `audio_effects` browser lookup.
- Py2 unicode: use `unicode()` and `u''` on names, never `str()`. Live caches `.pyc` files, so restart Live or re-select the surface after edits.
- `load_item` loads onto `song.view.selected_track`: clear `browser.hotswap_target`, set `device_insert_mode = selected_right`, then restore the user's selection. Loading onto master/return is **untested**, so spike it early.
- Third-party plugins expose only the params configured in Live ("Configure"); values are often normalized 0–1.
- Output meters are peak-ish instantaneous values, not LUFS; loudness comes from `analyze_master`.
- BlackHole and Live must both run at **48 kHz** (strict check in spectrum-advisor).
- Loading devices goes through the Live 10 browser API (`application().browser` + `load_item`), which needs the target track selected first.
- Local only, no cloud; zero cost apart from the Claude subscription.
- Safety: never apply changes without confirmation; prefer additive/undoable operations.

## Decisions
| Decision | Choice | Rationale |
|----------|--------|-----------|
| Client | Claude Code terminal (MCP) | Dorian wants to chat in the terminal |
| Scope v1 | Read + mixer + stock FX + params + analysis | All four control areas chosen, plus spectrum-advisor |
| Change policy | Propose → confirm → apply | Safety and learning; Cmd+Z remains available |
| Audio "hearing" | On-demand `analyze_master` tool using spectrum-advisor | Reuses the existing validated analysis modules |
| Third-party plugins | Read and tweak params, never load | Browser loading of VST/AU is fragile |
| Base implementation | Remote Script **from scratch**, threadless pattern from PR #103 | ahujasid's syntax is py2-OK, but its threading breaks on Live 10 and it lacks mixer setters, returns/master and undo |
| spectrum-advisor visibility | Make it **public**; consume as path dependency | Dorian's choice, so both projects are open source (visibility switch still pending) |
| Qt deps in spectrum-advisor | Move to `[ui]` extra | Keeps the MCP server light (~500 MB saved) |
| Analysis reference | Arg → last used → none | Flexible without extra config |
| Live meters | One-shot peak read in v1 | Catch clipping tracks and guide gain staging |
| Confirmation mechanism | Claude Code permissions: read tools allowlisted, write tools prompt | Native propose → confirm, batched via `apply` |
| Testing | pytest + fake-Live stub, then UAT in Live | Reliable without always needing Live open |
| Workflow features | Bus mixing, DnB chain presets, auto gain staging, explanations | Matches Dorian's mixing philosophy (loudness from the mix, not the master) |

## Research sources
- ahujasid/ableton-mcp (MIT): https://github.com/ahujasid/ableton-mcp
- PR #103, threadless Live 10 fix: https://github.com/ahujasid/ableton-mcp/pull/103 (fork leroidubuffet/AbletonMCP)
- Decompiled Live 10.1 scripts: https://github.com/gluon/AbletonLive10.1_MIDIRemoteScripts (Push2 browser_component.py:543, Push/actions.py:73)

## Spikes needed early
- Load a stock effect onto master and onto a return track.
- Round-trip latency and stability of the threadless loop on Dorian's machine.
- py2.7 syntax check without python2 locally (e.g. `uvx --python 2.7`? Probably unavailable; fall back to a vermin/pyflakes-style check plus in-Live testing).

## Brownfield Notes
Greenfield repo. Related local projects: `../spectrum-advisor` (analysis library, phases 1–5 built), `../Track_analyser` (earlier comparison script).
