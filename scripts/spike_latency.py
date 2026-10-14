"""Latency spike against a running Live 10 with the ClaudeMPC surface selected.

  uv run python scripts/spike_latency.py ping [-n 100]
"""

import argparse
import json
import statistics
import time

from claude_mpc.client import LiveClient
from claude_mpc.protocol import DEFAULT_PORT


def ping_burst(c: LiveClient, n: int) -> None:
    rtts = []
    errors = 0
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            c.request("ping")
            rtts.append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            errors += 1
            print("error:", e)
    rtts.sort()
    if not rtts:
        print("no successful pings")
        return
    p95 = rtts[min(len(rtts) - 1, int(len(rtts) * 0.95))]
    print(json.dumps({
        "n": n, "ok": len(rtts), "errors": errors,
        "p50_ms": round(statistics.median(rtts), 1), "p95_ms": round(p95, 1),
        "max_ms": round(rtts[-1], 1), "min_ms": round(rtts[0], 1),
    }, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("ping")
    p.add_argument("-n", type=int, default=100)
    args = ap.parse_args()

    c = LiveClient(port=args.port, timeout=10)
    try:
        ping_burst(c, args.n)
    finally:
        c.close()


if __name__ == "__main__":
    main()
