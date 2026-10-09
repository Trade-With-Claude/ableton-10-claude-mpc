import socket

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
    with pytest.raises(ConnectionError, match="ClaudeMPC control surface"):
        c.request("ping")


def test_server_imports():
    from claude_mpc import server

    assert server.mcp.name == "claude-mpc"
