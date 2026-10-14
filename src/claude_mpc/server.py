"""MCP server exposing Ableton Live 10 to Claude Code (stdio)."""

import asyncio
import os
import time

from mcp.server.mcpserver import MCPServer

from .client import LiveClient
from .protocol import DEFAULT_PORT

mcp = MCPServer("claude-mpc")
live = LiveClient(port=int(os.environ.get("CLAUDE_MPC_PORT", DEFAULT_PORT)))

METER_NOTE = (
    "Values are Live's raw output-meter scale (0-1, peak-ish, not dBFS or LUFS); "
    "peaks are the max over all reads. Use analyze_master for loudness."
)


async def _call(cmd: str, params: dict | None = None):
    return await asyncio.to_thread(live.request, cmd, params)


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
    is_plugin, on/off and parameter count. Call this first to find addresses.
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
