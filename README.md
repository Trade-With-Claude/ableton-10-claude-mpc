# Ableton 10 Claude MPC

An MCP bridge that lets [Claude Code](https://claude.com/claude-code) see and control a running **Ableton Live 10.1** session, from a chat in your terminal. Claude can:
- read your tracks, groups, returns, devices and mixer;
- mix and load stock effects;
- listen to the master;
- record automation from a description ("filter slowly opening over 16 bars");
- rebuild a sample on a stock Wavetable synth.

Existing Ableton MCP servers target Live 11/12. Live 10 runs its Remote Scripts on an embedded **Python 2.7** and starves background threads, so none of them work there. This one is written for Live 10.1: a threadless Python 2.7 Remote Script that talks to a Python 3.13 MCP server.

```
Claude Code (terminal chat)
   │  MCP (stdio)
   ▼
MCP server (Python 3.13, uv) ──── spectrum-advisor (BlackHole capture + analysis)
   │  TCP JSON, localhost:9879
   ▼
Remote Script "ClaudeMPC" inside Live 10 (Python 2.7)  →  Live Object Model
```

## How it works with you

- **Propose → confirm → apply.**
  - Claude states the planned changes and you approve them. Read tools run freely; write tools ask for permission.
  - Every write is undoable: one `apply` batch = **one Cmd+Z** in Live.
  - Click in Live before pressing Cmd+Z, because keystrokes in the terminal don't reach Live.
- **Explanations:** Claude explains why it makes each move, in mixing terms (loudness, mud, sub, masking).

## Requirements

- macOS (tested on macOS 15, Apple Silicon)
- **Ableton Live 10.1.x** (tested on 10.1.43 Suite). Live 11/12 are not supported.
- [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 for you)
- [Claude Code](https://claude.com/claude-code)
- [BlackHole 2ch](https://existential.audio/blackhole/), only for `analyze_master` (listening to the master)
- git, to fetch the [spectrum-advisor](https://github.com/Trade-With-Claude/spectrum-advisor) analysis engine

## Install

```bash
git clone https://github.com/Trade-With-Claude/ableton-10-claude-mpc.git
cd ableton-10-claude-mpc
uv sync                      # Python deps, including spectrum-advisor from GitHub
uv run pytest -q             # optional: everything should pass, no Live needed
scripts/install.sh           # copies the Remote Script into Ableton's User Library
```

`install.sh` copies `remote_script/ClaudeMPC/` to `~/Music/Ableton/User Library/Remote Scripts/ClaudeMPC/`. Set `CLAUDE_MPC_DEST` to install somewhere else.

### Select the control surface in Live

1. Restart Live, so it picks up the new script.
2. **Preferences › Link/MIDI**: in a free **Control Surface** slot, choose **ClaudeMPC**. Set **Input** and **Output** to **None**.
3. Live's status bar shows `ClaudeMPC listening on port 9879`.

### Connect Claude Code

The repo's `.mcp.json` declares the `claude-mpc` server, so start Claude Code from the repo folder:

```bash
claude
```

- Approve the project MCP server when Claude Code asks. `/mcp` should show `claude-mpc` as connected.
- Ask Claude to "ping Live". You should get Live's version, tempo and a round trip of about 100–200 ms.
- `.claude/settings.json` lets the read-only tools run without asking. Every write tool still asks for permission.

### BlackHole (to let Claude hear the master)

`analyze_master` records Live's output through BlackHole 2ch, then runs spectrum-advisor's analysis on it.

1. Install BlackHole 2ch.
2. **Audio MIDI Setup**: set **BlackHole 2ch** and your real output to **48000 Hz**.
3. To keep hearing your mix, do one of these:
   - create a **Multi-Output Device** (your headphones/interface + BlackHole 2ch) and use it as Live's output;
   - or send Live to BlackHole and monitor through an app such as eqMac.
4. **Live › Preferences › Audio**: Output Device = BlackHole 2ch (or the Multi-Output Device). **Sample Rate = 48000.**

Every point in the chain must run at **48 kHz**: spectrum-advisor refuses a mismatch.

## Tools

| Tool | Kind | What it does |
|---|---|---|
| `ping` | read | Live version, tempo, transport, playhead bar, round trip. Warns if the installed Remote Script is out of date. |
| `get_session` | read | All tracks, groups, returns and master: mixer state, sends, device chains (racks and chains included) and their addresses |
| `get_device_params` | read | Every parameter of one device: value, range, display string. Includes third-party plugins' exposed params. |
| `get_meters` | read | Peak-hold output meters while Live plays (Live's raw scale, not dB) |
| `analyze_master` | read | Records 10–60 s of the master through BlackHole and returns LUFS-I/S, true peak, PLR, spectrum zones, sub, stereo, punch, pump and diagnoses. Can use a reference track. Starts and stops playback itself. |
| `analyze_sample` | read | Analyses an audio file (path or Spotlight name): notes and glides, tempo, key, timbre, envelope, stereo. Used for sound reproduction. |
| `get_wavetable` | read | Wavetable's tables, voices, unison, filter routing and modulation matrix |
| `apply` | write | A batch of mixer / param / load_effect / delete_device / chain_mixer ops as **one undo step**. The whole batch is validated before anything changes. |
| `set_mixer`, `set_device_param`, `load_effect`, `delete_device` | write | Single-op shortcuts for `apply` |
| `record_automation` | write | Records parameter curves (ramps, dips, LFO/wobble, steps) into the Arrangement from a given bar |
| `create_instrument_track` | write | New MIDI track with a stock instrument and a clip of notes, as one undo step |
| `set_wavetable` | write | Sets Wavetable's tables, voices, unison and modulation matrix |

Claude loads **stock** Live devices only. Third-party plugins are read and tweaked through their exposed parameters, but never loaded.

## Things to ask

- "Read my session and tell me what you'd change on the drum bus."
- "Set the loop on the drop and analyse the master against my reference."
- "The 250–500 Hz area feels muddy: propose an EQ move on the bass bus."
- "Filter slowly opening on ATMO over 16 bars from bar 33, wobble on the last 2."
- "Reproduce the sample `my_lead_172.wav` on a new track."

## Live 10 limits

- **No Arrangement clip API.** Clips Claude creates land in **Session View**. To move one: select it, Cmd+C, Tab to the Arrangement, place the cursor, Cmd+V.
- For the same reason, Claude can't tell which audio file an Arrangement clip plays. Give it the sample's path or file name.
- Automation is **recorded** in real time, not drawn: at about 10 points per second, at the song's tempo. Movements faster than ½ bar belong on a device LFO or envelope.
- Racks, rack chains and group tracks can't be created from a script. Claude works inside existing ones.
- Tracks inside a **folded** group meter 0.0, so unfold the group for per-track meters.
- Output meters are peak-ish values, not LUFS. Loudness comes from `analyze_master`.

## Troubleshooting

| Message / symptom | Fix |
|---|---|
| `Cannot reach Live on 127.0.0.1:9879 … Is Live open, with the ClaudeMPC control surface selected…` | Open Live. Check Preferences › Link/MIDI: a Control Surface slot = ClaudeMPC, Input/Output = None. If another app uses port 9879, set `CLAUDE_MPC_PORT` (in Live too: `PORT` in `ClaudeMPC.py`). |
| `Live did not answer '…' within 5s … blocked by a dialog` | Live is busy (loading a set, a long batch) or a dialog is open. Click in Live, close the dialog, retry. |
| `Connection to Live lost after sending '…': it may or may not have been applied` | Live quit or the surface was re-selected mid-command. Ask Claude to read the session (`get_session`) before retrying, so nothing is applied twice. |
| `ping` shows a `warning` about the script version | Live runs an older copy of the Remote Script. Run `scripts/install.sh`, then restart Live. |
| Changes to the Remote Script don't show up | Live caches compiled scripts. `install.sh` deletes the `.pyc` files, but you still need to restart Live (or re-select the surface). |
| MCP server code changed | `/mcp` › Reconnect in Claude Code. No Live restart needed. |
| `analyze_master`: "No signal on BlackHole 2ch" or sample-rate errors | Live's output must go to BlackHole 2ch (or a Multi-Output Device that includes it), and everything must run at 48 kHz. Long silent stretches in the capture are rejected. Loop a section that plays. |
| Anything else | Live's log: `~/Library/Preferences/Ableton/Live 10.1.43/Log.txt` (lines start with `ClaudeMPC:`) |

## Development

```bash
uv run pytest -q             # MCP server + Remote Script logic against a fake Live (no Live needed)
```

- `remote_script/ClaudeMPC/` must stay **Python 2.7**-compatible: no f-strings, `unicode()` for names. `tests/test_py27_compat.py` checks this with vermin.
- The Remote Script is **threadless**: all socket I/O and Live calls happen in `update_display()` (~100 ms ticks). Live 10 starves background threads.
- To work on spectrum-advisor side by side, point the dependency at your local clone in `pyproject.toml`, then run `uv sync`:

  ```toml
  [tool.uv.sources]
  spectrum-advisor = { path = "../spectrum-advisor", editable = true }
  ```

## Credits

- [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) (MIT, © 2025 Siddharth Ahuja) is the original Ableton MCP server. This project's Remote Script is written from scratch for Live 10, but its approach comes from there: browser lookup and `load_item` on the selected track, and the session/track serialization. The threadless `update_display()` design follows the Live 10 findings in that repo's PR #103.
- [spectrum-advisor](https://github.com/Trade-With-Claude/spectrum-advisor) does the master analysis (LUFS, spectrum, stereo, diagnoses).

## License

MIT, see [LICENSE](LICENSE).
