"""MCP server exposing Ableton Live 10 to Claude Code (stdio)."""

import asyncio
import os
import time

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import analysis, sound
from .client import LiveClient
from .protocol import DEFAULT_PORT, LiveError

PREROLL_S = 1.0  # after autoplay starts Live, let the section settle before recording
RECORD_POLL_S = 0.25  # record_automation: status poll interval
RECORD_SLACK_S = 5.0  # record_automation: allowed time beyond the take's expected length

mcp = MCPServer("claude-mpc")
live = LiveClient(port=int(os.environ.get("CLAUDE_MPC_PORT", DEFAULT_PORT)))

METER_NOTE = (
    "Values are Live's raw output-meter scale (0-1, peak-ish, not dBFS or LUFS); "
    "peaks are the max over all reads. Tracks inside a folded group read 0.0 (Live stops "
    "metering them); unfold groups for per-track values. Use analyze_master for loudness."
)


async def _call(cmd: str, params: dict | None = None):
    # ToolError, so the message reaches Claude (any other exception shows as a bare
    # "Error executing tool <name>").
    try:
        return await asyncio.to_thread(live.request, cmd, params)
    except LiveError as exc:
        raise ToolError(str(exc)) from exc
    except OSError as exc:
        raise ToolError(
            f"Cannot reach Live ({exc}). Is Live open with ClaudeMPC selected as a Control Surface?"
        ) from exc


@mcp.tool()
async def ping() -> dict:
    """Check the connection to Ableton Live. Returns Live version, tempo, is_playing,
    position_bar (playhead / insert marker in 1-based 4/4 bars), recorder_state and round-trip time."""
    t0 = time.perf_counter()
    result = await _call("ping")
    result["rtt_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


@mcp.tool()
async def get_session() -> dict:
    """Read the whole Live session: tempo, tracks, return tracks and master.

    Each track has kind/index (its address for other tools), name, type (audio|midi|group),
    group_index (index of its parent group track, or null), output routing, mute/solo/arm,
    volume/pan and sends ({value, display}; sends are named after their return track),
    and its device chain. Each device has a `path` (its address within the track; racks
    list chains with nested devices, path = [rack, chain, device, ...]), class_name,
    is_plugin, on/off and parameter count. Rack chains also show their mixer volume/pan
    ({value, display}) and mute/solo; a chain's address is [rack path..., chain index].
    Call this first to find addresses.
    """
    return await _call("get_session")


@mcp.tool()
async def get_device_params(
    kind: str, index: int, device_path: list[int], query: str | None = None
) -> dict:
    """Read every parameter of one device: value, min, max, quantized items and display string.

    Address it from get_session: kind = "track" | "return" | "master", index = track index
    (ignored for master), device_path = the device's `path` (e.g. [0], or [1, 0, 2] inside
    a rack). `query` filters parameter names (case-insensitive substring), handy for large
    plugins. Third-party plugins only expose parameters configured in Live, often 0-1.
    """
    params = {"kind": kind, "index": index, "path": device_path}
    if query:
        params["query"] = query
    return await _call("get_device_params", params)


@mcp.tool()
async def get_meters(reads: int = 10, interval_ms: int = 100) -> dict:
    """Peak-hold output meters for every track, return and master while Live plays.

    Takes `reads` one-shot meter readings `interval_ms` apart (default ~1 s window) and
    keeps the max per channel. Useful to spot clipping or hot tracks; not a loudness measure.
    Tracks inside a folded group always read 0.0, so ask the user to unfold groups first.
    """
    reads = max(1, min(int(reads), 100))
    peaks: dict[tuple, dict] = {}
    for n in range(reads):
        if n:
            await asyncio.sleep(interval_ms / 1000)
        for m in await _call("get_meters"):
            key = (m["kind"], m["index"])
            p = peaks.setdefault(key, {"kind": m["kind"], "index": m["index"], "name": m["name"],
                                       "peak_left": 0.0, "peak_right": 0.0})
            p["peak_left"] = max(p["peak_left"], m["left"])
            p["peak_right"] = max(p["peak_right"], m["right"])
    return {"reads": reads, "note": METER_NOTE, "meters": list(peaks.values())}


@mcp.tool()
async def analyze_master(
    seconds: int = 15, reference: str | None = None, autoplay: bool = True
) -> dict:
    """Listen to the Live master: record `seconds` (10-60, default 15) from BlackHole 2ch and analyze.

    With autoplay (default), if Live is stopped this starts playback (from Live's insert
    marker, looping if the loop is on), waits ~1 s, records, then stops it again; if Live
    is already playing it is left alone. So ask the user to set the loop (and insert
    marker) on the section first, e.g. the drop. autoplay=False: the user plays it.
    The call blocks for `seconds` + ~2-3 s. Requires Live's output on BlackHole 2ch at 48 kHz.
    Captures more than 10 % silent are rejected (late start, stop, breakdown in the loop);
    `silence_fraction` and `autoplay` ("started"|"already_playing"|"off") are reported.
    Returns loudness (LUFS-I over the capture, LUFS-S = last 3 s, true peak, PLR, crest;
    LRA needs >= 30 s), band zones in dB relative to total energy (sub 20-60, low 60-250,
    low_mid 250-500, mid 500-2k, high_mid 2-6k, air 6k-20k) plus 31 third-octave bands,
    stereo (correlation, side fraction, low-end mono compatibility, mono LUFS delta),
    drum punch per element, pump score (0-10, advisory), translation and diagnoses.
    `reference` = path to a reference track; else spectrum-advisor's last used one; else
    none. Spectrum diagnoses (`reference.zone_deviation_db`, LUFS-matched) need a
    reference; without one only DnB absolute targets apply (mix bus -5/-6 LUFS-S, master
    -4 LUFS-I). Explain results in DnB mixing terms and propose concrete changes.
    """
    try:
        status = await _call("ping")
        bpm, playing = float(status["tempo"]), status.get("is_playing")
    except ToolError:
        bpm, playing = analysis.DEFAULT_BPM, None
    started = False
    if not autoplay:
        mode = "off"
    elif playing is False:
        await _call("transport", {"play": True})
        started, mode = True, "started"
        await asyncio.sleep(PREROLL_S)
    else:  # already playing, or Live unreachable / pre-0.4.0 script: leave the transport alone
        mode = "already_playing" if playing else "unknown"
    try:
        result = await asyncio.to_thread(analysis.run, seconds, reference, bpm)
    except analysis.AnalysisError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        if started:
            try:
                await _call("transport", {"play": False})
            except ToolError:
                pass
    result["autoplay"] = mode
    return result


@mcp.tool()
async def analyze_sample(path_or_name: str, tempo: float | None = None) -> dict:
    """Listen to an audio file (a lead, bass or one-shot line, max 30 s) to reproduce it with a
    stock synth. `path_or_name` = an absolute path, or a file name found with Spotlight (Live 10
    can't tell which file an Arrangement clip plays, so ask the user for the sample's name).
    `tempo` defaults to the BPM in the file name, else an estimate; give the set's tempo if the
    sample was warped to it.

    Monophonic: one note at a time (chords, pads and full loops come out wrong). Returns
    notes [{pitch, name, start_beat, length_beats, velocity, glide_from}] quantised to 1/16,
    key (from the notes; key_from_name is the file-name hint), timbre (osc sine|triangle|
    square|saw, harmonics_db re the fundamental, resonance = a filter peak lifting harmonics,
    cutoff_hz, brightness_move within notes, noise), amp envelope (attack/decay ms, sustain
    0-1, release ms) and stereo width. `glide_from` = the note slides in from that pitch;
    `octave_check` = the note may sound an octave higher. Show the user what you hear
    (notes per bar, rhythm, sound) before building anything.
    """
    try:
        hits = await asyncio.to_thread(sound.find_sample, path_or_name)
        if not hits:
            raise ToolError(f"no audio file named {path_or_name!r} found (give the full path)")
        exact = [h for h in hits if os.path.basename(h) in (path_or_name, os.path.basename(path_or_name))]
        if len(hits) > 1 and len(exact) != 1:
            raise ToolError("several files match, give the full path: " + "; ".join(hits[:10]))
        return await asyncio.to_thread(sound.analyze_sample, (exact or hits)[0], tempo)
    except sound.SoundError as exc:
        raise ToolError(str(exc)) from exc


# -- writes: every tool runs through `apply`, so each call is one Cmd+Z in Live --------
WRITE_POLICY = """
Before calling, tell the user exactly what will change and why (propose -> confirm);
the user approves the tool call. Values are given in Live's display units and clamped
to range. The result lists each change with its before/after display; if a change
fails mid-batch the result has `error` and `applied` < `total` (Cmd+Z reverts the rest).
"""


async def _apply(ops: list[dict]) -> dict:
    return await _call("apply", {"ops": ops})


def _op(op: str, kind: str, index: int, **fields) -> dict:
    return {"op": op, "kind": kind, "index": index,
            **{k: v for k, v in fields.items() if v is not None}}


@mcp.tool(description="""Apply several changes as ONE undo step (one Cmd+Z reverts the batch).

`ops` is a list of operations, each addressed by kind ("track"|"return"|"master") and index:
  {"op": "mixer", "kind", "index", "volume_db": -6, "pan": "25L"|-25, "sends": {"A-Reverb": -20}, "mute": true, "solo": false}
  {"op": "param", "kind", "index", "path": [0], "param": "Threshold"|3, "display": -12 | "High pass" | "on"}  (or "value": raw)
  {"op": "load_effect", "kind", "index", "name": "EQ Eight", "position": null (end) | n,
   "chain": [rack path..., chain index] (optional: load inside that rack chain, position within it;
   the chain must already hold a device)}
  {"op": "delete_device", "kind", "index", "path": [1]}
  {"op": "chain_mixer", "kind", "index", "chain": [1, 0], "volume_db": -3, "pan": "10L", "mute": false, "solo": false}
All ops are validated before anything is written: one bad op means nothing changes.
""" + WRITE_POLICY)
async def apply(ops: list[dict]) -> dict:
    return await _apply(ops)


@mcp.tool(description="""Set mixer controls on one track, return or master (one undo step).

volume_db in dB ("-inf" allowed, max +6), pan as -50..50 or "25L"/"C"/"10R", sends as
{return name | letter | index: dB}, mute/solo as booleans. Master has volume/pan only.
""" + WRITE_POLICY)
async def set_mixer(
    kind: str,
    index: int,
    volume_db: float | str | None = None,
    pan: float | str | None = None,
    sends: dict[str, float | str] | None = None,
    mute: bool | None = None,
    solo: bool | None = None,
) -> dict:
    return await _apply([_op("mixer", kind, index, volume_db=volume_db, pan=pan, sends=sends,
                             mute=mute, solo=solo)])


@mcp.tool(description="""Set one device parameter (one undo step).

Address the device as in get_device_params (kind, index, device_path). `param` is a name
(case-insensitive exact, else unique substring) or an index. Give `display` in the units
get_device_params shows (-12 for dB, 200 or "1.2 kHz", "30 %", an item name like
"High pass", "on"/"off") or a raw `value` within min..max.
""" + WRITE_POLICY)
async def set_device_param(
    kind: str,
    index: int,
    device_path: list[int],
    param: str | int,
    display: float | str | None = None,
    value: float | None = None,
) -> dict:
    return await _apply([_op("param", kind, index, path=device_path, param=param,
                             display=display, value=value)])


@mcp.tool(description="""Load a stock Ableton audio effect (e.g. "EQ Eight", "Glue Compressor",
"Utility", "Saturator", "Limiter") onto a track, return or master (one undo step).

`position` = device index to insert at; omit to append at the end of the chain.
Third-party plugins cannot be loaded. The user's track/device selection is restored.
""" + WRITE_POLICY)
async def load_effect(kind: str, index: int, name: str, position: int | None = None) -> dict:
    return await _apply([_op("load_effect", kind, index, name=name, position=position)])


@mcp.tool(description="""Delete one device (also inside racks via its path) (one undo step).
""" + WRITE_POLICY)
async def delete_device(kind: str, index: int, device_path: list[int]) -> dict:
    return await _apply([_op("delete_device", kind, index, path=device_path)])


@mcp.tool(description="""Write automation into the Arrangement by RECORDING it: Live plays from
`preroll_bars` before `start_bar`, punches in at `start_bar`, the script moves each parameter
along its curve in time with the song, punches out after `bars`, stops and puts everything back
(loop, Automation Arm, playhead, track arms: every track is disarmed during the take so no
audio/MIDI is recorded). The result is ordinary, hand-editable Arrangement automation.
Blocks for the take's length (+ ~1 s); Live must be stopped first. 4/4 only.
The parameters keep their current value before start_bar. "From my cursor": ping returns
`position_bar` (the Arrangement insert marker while stopped); use its whole bar as start_bar.

`lanes`: one per parameter, addressed like set_device_param:
  {"kind": "track", "index": 17, "device_path": [5], "param": "Frequency",
   "segments": [{"from_bar": 33, "to_bar": 49, "shape": "exp", "start": 300, "end": "12 kHz"}, ...]}
Segments use 1-based bars within start_bar..start_bar+bars, values in display units (as
get_device_params shows them); interpolation is in Live's raw scale (filter frequency moves
musically). Shapes: ramp, exp (slow start, fast end: builds), log (fast start, slow end),
hold (start), sine / triangle / square (LFO between start and end, `rate` = bars per cycle,
e.g. "1/2", starting at start), steps (`values` list, one per `rate`). Outside its segments a
lane holds its nearest value.

Turning a vibe into lanes: name the parameter(s) and bars, pick shapes ("slowly opening" =
exp ramp up; "a dip before the drop" = log down then ramp back over 1 bar; "breathing" =
sine at 1-2 bars), and say the values in Hz/dB/%. If the effect isn't on the track yet, load
it first (load_effect/apply). The script draws ~10 points/s (~3 per beat at 175 BPM): fine
for ramps and slow LFOs; an LFO faster than ~1/2 bar is refused, so automate the device's own
LFO (rate/amount) instead. A parameter that already has automation is refused unless
`overwrite` (it would be replaced in those bars): say so in the proposal.

Result: state "done" | "aborted" (Dorian pressed stop: the part already recorded stays) with
points_written, mean_tick_ms and elapsed_s. To remove a take, Dorian presses Cmd+Z in Live
(click in Live first so it has focus).
""" + WRITE_POLICY)
async def record_automation(
    lanes: list[dict],
    start_bar: float,
    bars: float,
    preroll_bars: float = 1,
    overwrite: bool = False,
) -> dict:
    status = await _call("ping")
    expected_s = (bars + preroll_bars) * 4 * 60.0 / float(status["tempo"])
    t0 = time.perf_counter()
    await _call("automation_record", {"lanes": lanes, "start_bar": start_bar, "bars": bars,
                                      "preroll_bars": preroll_bars, "overwrite": overwrite})
    finished = False
    try:
        while True:
            await asyncio.sleep(RECORD_POLL_S)
            result = await _call("automation_status")
            if result["state"] not in ("preroll", "recording"):
                finished = True
                break
            if time.perf_counter() - t0 > expected_s + RECORD_SLACK_S:
                raise ToolError(f"take did not finish in {expected_s + RECORD_SLACK_S:.0f} s "
                                f"(stuck at bar {result.get('bar')}): aborted it")
    finally:
        if not finished:  # timeout, error or cancellation: never leave Live recording
            try:
                await _call("automation_abort")
            except ToolError:
                pass
    result["elapsed_s"] = round(time.perf_counter() - t0, 1)
    if result["state"] == "error":
        raise ToolError(f"take failed: {result.get('error')} (transport and arms restored)")
    return result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
