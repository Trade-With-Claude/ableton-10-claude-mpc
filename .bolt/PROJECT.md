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
- **Remote Script** (inside Live 10): Python **2.7**-compatible, `_Framework` ControlSurface, TCP socket server, commands executed on Live's main thread.
- **MCP server** (outside Live): Python 3.13 + `mcp` SDK (FastMCP), managed with `uv`.
- **Analysis**: `spectrum-advisor` as a path dependency (`../spectrum-advisor`): librosa, pyloudnorm, sounddevice, BlackHole 2ch.
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

## Constraints
- Live 10.1.43 only, with embedded Python 2.7 in the Remote Script (no f-strings, no py3-only stdlib).
- LOM mutations must run on Live's main thread (schedule_message / update_display loop).
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
| Base implementation | **TBD in /bolt:research** (fork ahujasid/ableton-mcp vs. from scratch) | Need to verify real Live 10 / Py 2.7 compatibility |
| spectrum-advisor visibility | Make it **public**; consume as path dependency | Dorian's choice, so both projects are open source (visibility switch still pending) |
| Testing | pytest + fake-Live stub, then UAT in Live | Reliable without always needing Live open |
| Workflow features | Bus mixing, DnB chain presets, auto gain staging, explanations | Matches Dorian's mixing philosophy (loudness from the mix, not the master) |

## Open questions for research
- Does ahujasid/ableton-mcp's Remote Script actually run on Live 10.1.43 / Py 2.7? What breaks?
- Live 10 LOM: are `output_meter_left/right` available on tracks? What's the device-loading API and its browser URIs for stock devices?
- How robust is threading/scheduling in Live 10 (`schedule_message` vs. `update_display`)?
- Can spectrum-advisor's analysis be imported cleanly without its UI (PySide6) dependencies?

## Brownfield Notes
Greenfield repo. Related local projects: `../spectrum-advisor` (analysis library, phases 1–5 built), `../Track_analyser` (earlier comparison script).
