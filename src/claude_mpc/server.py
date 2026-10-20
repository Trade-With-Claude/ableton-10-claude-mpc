"""MCP server exposing Ableton Live 10 to Claude Code (stdio)."""

import asyncio
import os
import time

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import analysis
from .client import LiveClient
from .protocol import DEFAULT_PORT, LiveError

PREROLL_S = 1.0  # after autoplay starts Live, let the section settle before recording

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
    """Check the connection to Ableton Live. Returns Live version, tempo and round-trip time."""
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
