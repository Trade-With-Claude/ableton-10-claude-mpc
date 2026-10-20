"""MCP tool functions end to end against FakeLive (which serializes a fake LOM via lom.py)."""

import asyncio
import json
import pathlib

import pytest

from claude_mpc import server
from mcp.server.mcpserver.exceptions import ToolError


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
    with pytest.raises(ToolError, match="no return track 7"):
        run(server.get_device_params("return", 7, [0]))


def test_get_meters_peak_hold():
    r = run(server.get_meters(reads=3, interval_ms=1))
    assert r["reads"] == 3 and "not dBFS" in r["note"]
    master = [m for m in r["meters"] if m["kind"] == "master"][0]
    assert master["peak_left"] == 1.0 and master["peak_right"] == 0.95
    assert "MIDI only" not in [m["name"] for m in r["meters"]]


READ_TOOLS = {"ping", "get_session", "get_device_params", "get_meters", "analyze_master"}
WRITE_TOOLS = {"apply", "set_mixer", "set_device_param", "load_effect", "delete_device"}


def test_tools_registered():
    names = {t.name for t in run(server.mcp.list_tools())}
    assert READ_TOOLS | WRITE_TOOLS <= names


def test_only_read_tools_are_allowlisted():
    root = pathlib.Path(__file__).parent.parent
    allow = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["allow"]
    assert {a.removeprefix("mcp__claude-mpc__") for a in allow} == READ_TOOLS


def test_set_mixer(fake_live):
    r = run(server.set_mixer("track", 1, volume_db=-6, pan="25L", sends={"B": -12}, mute=True))
    assert r["applied"] == r["total"] == 4
    assert [(c["what"], c["after"]) for c in r["results"][0]["changes"]] == [
        ("volume", "-6.0 dB"), ("pan", "25L"), ("send B-Delay", "-12.0 dB"), ("mute", "on")]
    assert fake_live.song.tracks[1].mute is True
    assert (fake_live.song.undo_begins, fake_live.song.undo_ends) == (1, 1)


def test_set_device_param_by_name_and_item():
    r = run(server.set_device_param("track", 0, [0], "S/C EQ Type", display="Low pass"))
    assert r["results"][0]["changes"][0] == {
        "what": "Glue Compressor: S/C EQ Type", "before": "Low Shelf", "after": "Low pass"}
    r = run(server.set_device_param("track", 3, [1, 1, 0], "drive", value=99))
    assert r["results"][0]["changes"][0]["after"] == "36.0 dB"  # clamped


def test_load_and_delete_effect(fake_live):
    r = run(server.load_effect("master", 0, "Utility"))
    assert r["results"][0]["changes"][0]["after"] == "Utility at [2]"
    r = run(server.delete_device("master", 0, [2]))
    assert [d.name for d in fake_live.song.master_track.devices] == ["Limiter", "kHs Limiter"]


def test_apply_batch_is_one_undo_step(fake_live):
    r = run(server.apply([
        {"op": "mixer", "kind": "track", "index": 0, "volume_db": -3, "sends": {"A-Reverb": -20}},
        {"op": "param", "kind": "track", "index": 0, "path": [0], "param": "Threshold", "display": -10},
        {"op": "load_effect", "kind": "track", "index": 0, "name": "EQ Eight"},
    ]))
    assert r["applied"] == r["total"] == 4 and "error" not in r
    assert (fake_live.song.undo_begins, fake_live.song.undo_ends) == (1, 1)


def test_invalid_batch_changes_nothing(fake_live):
    with pytest.raises(ToolError, match="op 1: .*no param 'Knee'"):
        run(server.apply([
            {"op": "mixer", "kind": "track", "index": 0, "volume_db": -3},
            {"op": "param", "kind": "track", "index": 0, "path": [0], "param": "Knee", "display": 1},
        ]))
    vol = fake_live.song.tracks[0].mixer_device.volume
    assert vol.str_for_value(vol.value) == "0.0 dB" and fake_live.song.undo_begins == 0


def test_chain_mixer_and_load_into_chain_via_apply(fake_live):
    r = run(server.apply([
        {"op": "chain_mixer", "kind": "track", "index": 3, "chain": [1, 1], "volume_db": -3},
        {"op": "load_effect", "kind": "track", "index": 3, "name": "EQ Eight", "chain": [1, 1], "position": 0},
    ]))
    assert "error" not in r and r["applied"] == r["total"] == 2
    assert r["results"][1]["changes"][0]["after"] == "EQ Eight at chain 'Mid' [0]"
    chains = run(server.get_session())["tracks"][3]["devices"][1]["chains"]
    assert chains[1]["volume"]["display"] == "-3.0 dB"
    assert chains[1]["devices"][0]["name"] == "EQ Eight"
