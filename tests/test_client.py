import socket
import time

import pytest

from claude_mpc.client import LiveClient
from claude_mpc.protocol import LiveError, ProtocolError
from fake_live import FakeLive


def test_ping(client):
    result = client.request("ping")
    assert result["live_version"] == "10.1.43"
    assert result["tempo"] == 174.0


def test_unknown_command_raises_live_error(client):
    with pytest.raises(LiveError, match="unknown command"):
        client.request("nope")


def test_malformed_reply_raises_protocol_error(fake_live, client):
    fake_live.raw_reply = b"this is not json\n"
    with pytest.raises(ProtocolError):
        client.request("ping")


def test_large_payload_chunked():
    fl = FakeLive(chunk_size=7)
    try:
        c = LiveClient(port=fl.port, timeout=5.0)
        big = {"names": [u"Pad été %d" % i for i in range(5000)]}
        assert c.request("echo", big) == big
        c.close()
    finally:
        fl.close()


def test_reconnects_after_server_restart():
    fl = FakeLive()
    port = fl.port
    c = LiveClient(port=port, timeout=2.0)
    assert c.request("ping")
    # simulate Live restart: kill the current connection
    c._sock.shutdown(socket.SHUT_RDWR)
    assert c.request("ping")["tempo"] == 174.0
    c.close()
    fl.close()


def test_connection_refused_message():
    c = LiveClient(port=1, timeout=0.5)
    with pytest.raises(ConnectionError, match="ClaudeMPC control surface selected"):
        c.request("ping")


def test_write_not_resent_after_lost_reply(fake_live, client):
    fake_live.drop_once.add("apply")
    with pytest.raises(ConnectionError, match="may or may not have been applied"):
        client.request("apply", {"ops": []})
    assert fake_live.received.count("apply") == 1
    assert client.request("ping")  # next call reconnects


def test_read_retried_after_lost_reply(fake_live, client):
    fake_live.drop_once.add("get_session")
    assert client.request("get_session")["tracks"]
    assert fake_live.received.count("get_session") == 2


def test_dead_socket_detected_before_send(fake_live, client):
    assert client.request("ping")
    fake_live.drop_connections()
    time.sleep(0.05)
    assert client.request("echo", {"x": 1}) == {"x": 1}  # not read-only: would fail if sent on the dead socket
    assert fake_live.received.count("echo") == 1


def test_timeout_message(fake_live):
    c = LiveClient(port=fake_live.port, timeout=0.3)
    with pytest.raises(TimeoutError, match="blocked by a dialog"):
        c.request("slow", {"s": 1.0})
    c.close()


def test_server_imports():
    from claude_mpc import server

    assert server.mcp.name == "claude-mpc"
