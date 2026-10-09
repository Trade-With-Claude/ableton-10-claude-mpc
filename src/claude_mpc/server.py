"""MCP server exposing Ableton Live 10 to Claude Code (stdio)."""

import asyncio
import os
import time

from mcp.server.mcpserver import MCPServer

from .client import LiveClient
from .protocol import DEFAULT_PORT

mcp = MCPServer("claude-mpc")
live = LiveClient(port=int(os.environ.get("CLAUDE_MPC_PORT", DEFAULT_PORT)))


@mcp.tool()
async def ping() -> dict:
    """Check the connection to Ableton Live. Returns Live version, tempo and round-trip time."""
    t0 = time.perf_counter()
    result = await asyncio.to_thread(live.request, "ping")
    result["rtt_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
