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


def test_ping_version_warning(monkeypatch):
    monkeypatch.setattr(server, "EXPECTED_SCRIPT_VERSION", "0.6.1")
    r = run(server.ping())  # fake Live reports "fake"
    assert r["expected_script_version"] == "0.6.1" and "install.sh" in r["warning"]
    monkeypatch.setattr(server, "EXPECTED_SCRIPT_VERSION", "fake")
    assert "warning" not in run(server.ping())


def test_expected_script_version_read_from_repo():
    assert server.EXPECTED_SCRIPT_VERSION == "0.6.1"


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


READ_TOOLS = {"ping", "get_session", "get_device_params", "get_meters", "analyze_master",
              "analyze_sample", "get_wavetable"}
WRITE_TOOLS = {"apply", "set_mixer", "set_device_param", "load_effect", "delete_device",
               "record_automation", "create_instrument_track",
               "set_wavetable"}


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


# -- record_automation ---------------------------------------------------------
@pytest.fixture
def take(fake_live, monkeypatch):
    from fake_lom import Track, auto_filter
    monkeypatch.setattr(server, "RECORD_POLL_S", 0.001)
    fake_live.song.tracks.append(Track("test", devices=[auto_filter()]))
    fake_live.song.tracks[2].arm = True
    return fake_live


def filter_lane(**seg):
    s = {"from_bar": 5, "to_bar": 7, "shape": "exp", "start": 300, "end": "12 kHz"}
    s.update(seg)
    return [{"kind": "track", "index": 5, "device_path": [0], "param": "Frequency", "segments": [s]}]


def test_record_automation_done(take):
    r = run(server.record_automation(filter_lane(), start_bar=5, bars=2))
    assert r["state"] == "done" and r["progress"] == 1.0 and r["points_written"] > 10
    assert r["lanes"] == [{"param": "Auto Filter: Frequency", "track": "test"}]
    assert r["elapsed_s"] >= 0
    song = take.song
    assert not song.is_playing and not song.record_mode and song.loop and song.tracks[2].arm
    assert song.tracks[5].devices[0].parameters[1].str_for_value(
        song.tracks[5].devices[0].parameters[1].value) == "12.00 kHz"
    assert take.abort_calls == 0


def test_record_automation_validation_error(take):
    with pytest.raises(ToolError, match="too fast to draw"):
        run(server.record_automation(filter_lane(shape="sine", rate="1/8"), start_bar=5, bars=2))
    assert take.recorder.state == "idle"


def test_record_automation_aborted_by_stop_in_live(take):
    orig = take._automation_status

    def status_then_stop(p):
        out = orig(p)
        if out["state"] == "recording":
            take.song.stop_playing()
        return out
    take.handlers["automation_status"] = status_then_stop
    r = run(server.record_automation(filter_lane(), start_bar=5, bars=2))
    assert r["state"] == "aborted" and "playback stopped in Live" in r["error"]
    assert take.song.tracks[2].arm


def test_record_automation_error_mid_take_is_tool_error(take):
    orig = take._automation_status
    param = take.song.tracks[5].devices[0].parameters[1]

    def status_then_break(p):
        out = orig(p)
        if out["state"] == "recording":
            param.min = param.max = 20.0  # every later write is out of range
        return out
    take.handlers["automation_status"] = status_then_break
    with pytest.raises(ToolError, match="take failed: .*out of range.*restored"):
        run(server.record_automation(filter_lane(), start_bar=5, bars=2))
    assert not take.song.is_playing and not take.song.record_mode and take.song.tracks[2].arm


def test_record_automation_timeout_aborts(take, monkeypatch):
    monkeypatch.setattr(server, "RECORD_SLACK_S", -100.0)  # already late at the first poll
    take.ticks_per_poll = 0
    with pytest.raises(ToolError, match="did not finish"):
        run(server.record_automation(filter_lane(), start_bar=5, bars=2))
    assert take.abort_calls == 1 and take.recorder.state == "aborted"
    assert not take.song.is_playing and take.song.tracks[2].arm


def test_record_automation_cancel_aborts(take):
    take.ticks_per_poll = 0  # never finishes on its own

    async def cancel_soon():
        task = asyncio.create_task(server.record_automation(filter_lane(), start_bar=5, bars=2))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    run(cancel_soon())
    assert take.abort_calls == 1 and not take.song.record_mode


def test_analyze_sample_resolves_name(monkeypatch):
    calls = []
    monkeypatch.setattr(server.sound, "find_sample", lambda n: ["/s/lead.wav", "/s/old/lead 2.wav"])
    monkeypatch.setattr(server.sound, "analyze_sample",
                        lambda p, t: calls.append((p, t)) or {"file": p, "notes": []})
    assert run(server.analyze_sample("lead.wav", tempo=174))["file"] == "/s/lead.wav"
    assert calls == [("/s/lead.wav", 174)]


def test_analyze_sample_errors(monkeypatch):
    monkeypatch.setattr(server.sound, "find_sample", lambda n: [])
    with pytest.raises(ToolError, match="no audio file"):
        run(server.analyze_sample("nope"))
    monkeypatch.setattr(server.sound, "find_sample", lambda n: ["/a/lead.wav", "/b/lead.wav"])
    with pytest.raises(ToolError, match="several files"):
        run(server.analyze_sample("lead"))

    def silent(p, t):
        raise server.sound.SoundError("lead.wav is silent")
    monkeypatch.setattr(server.sound, "find_sample", lambda n: ["/a/lead.wav"])
    monkeypatch.setattr(server.sound, "analyze_sample", silent)
    with pytest.raises(ToolError, match="silent"):
        run(server.analyze_sample("lead"))


def test_create_instrument_track(fake_live):
    clip = {"length_beats": 16, "name": "lead",
            "notes": [{"pitch": 70, "start_beat": 0, "length_beats": 0.75, "velocity": 115}]}
    r = run(server.create_instrument_track("Lead copy", "Analog", clip=clip))
    assert r["track_index"] == 5 and r["device"]["path"] == [0] and r["clip"]["notes"] == 1
    params = run(server.get_session())["tracks"][5]
    assert params["name"] == "Lead copy" and params["type"] == "midi"
    assert params["devices"][0]["name"] == "Analog"
    # the new track is addressable by the usual tools
    run(server.set_mixer("track", 5, volume_db=-6))


def test_create_instrument_track_errors(fake_live):
    with pytest.raises(ToolError, match="instrument not found"):
        run(server.create_instrument_track("Lead", "Serum"))
    with pytest.raises(ToolError, match="pitch"):
        run(server.create_instrument_track("Lead", "Analog", clip={
            "length_beats": 4, "notes": [{"pitch": 128, "start_beat": 0, "length_beats": 1}]}))
    assert len(fake_live.song.tracks) == 5


def test_wavetable_tools(fake_live):
    r = run(server.create_instrument_track("Lead WT", "Wavetable"))
    i = r["track_index"]
    got = run(server.get_wavetable("track", i, [0]))
    assert got["osc1"]["table"] == "Basic Shapes"
    r = run(server.set_wavetable("track", i, [0], {"mono": True, "osc1": {"table": "sine saw"}}))
    assert r["applied"] == 2 and r["state"]["mono"] is True
    assert r["state"]["osc1"]["table"] == "Sine Saw"
    with pytest.raises(ToolError, match="not a Wavetable"):
        run(server.get_wavetable("track", 0, [0]))
