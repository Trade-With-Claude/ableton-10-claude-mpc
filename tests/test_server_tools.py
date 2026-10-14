"""MCP tool functions end to end against FakeLive (which serializes a fake LOM via lom.py)."""

import asyncio

import pytest

from claude_mpc import server
from claude_mpc.protocol import LiveError


@pytest.fixture(autouse=True)
def wired(client, monkeypatch):
    monkeypatch.setattr(server, "live", client)


def run(coro):
    return asyncio.run(coro)


def test_ping_has_rtt():
    r = run(server.ping())
    assert r["live_version"] == "10.1.43" and r["rtt_ms"] >= 0


def test_get_session():
    s = run(server.get_session())
    assert [t["name"] for t in s["tracks"]][:4] == ["DRUMS", "Kick", "Snare", "Bässe ✦ Sub"]
    assert s["tracks"][1]["group_index"] == 0
    assert [r["name"] for r in s["returns"]] == ["A-Reverb", "B-Delay"]
    assert s["master"]["devices"][0]["name"] == "Limiter"


def test_get_device_params_nested_and_query():
    r = run(server.get_device_params("track", 3, [1, 1, 0], query="drive"))
    assert r["track"] == "Bässe ✦ Sub" and r["device"]["name"] == "Saturator"
    assert [(p["name"], p["display"]) for p in r["params"]] == [("Drive", "6.0 dB")]


def test_get_device_params_master():
    r = run(server.get_device_params("master", 0, [0]))
    assert r["params"][1]["display"] == "-0.3 dB"


def test_bad_address_is_tool_error():
    with pytest.raises(LiveError, match="no return track 7"):
        run(server.get_device_params("return", 7, [0]))


def test_get_meters_peak_hold():
    r = run(server.get_meters(reads=3, interval_ms=1))
    assert r["reads"] == 3 and "not dBFS" in r["note"]
    master = [m for m in r["meters"] if m["kind"] == "master"][0]
    assert master["peak_left"] == 1.0 and master["peak_right"] == 0.95
    assert "MIDI only" not in [m["name"] for m in r["meters"]]


def test_tools_registered():
    names = {t.name for t in run(server.mcp.list_tools())}
    assert {"ping", "get_session", "get_device_params", "get_meters"} <= names
