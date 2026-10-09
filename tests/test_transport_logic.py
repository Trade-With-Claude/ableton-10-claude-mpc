"""Drive the Remote Script transport with LiveClient, polling it like update_display() would."""

import pathlib
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"))
import transport as rs_transport  # noqa: E402

from claude_mpc.client import LiveClient  # noqa: E402
from claude_mpc.protocol import LiveError  # noqa: E402


def handler(cmd, params):
    if cmd == "ping":
        return {"live_version": "10.1.43", "tempo": 174.0}
    if cmd == "echo":
        return params
    if cmd == "boom":
        raise RuntimeError("kaboom")
    raise KeyError("unknown command: " + cmd)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def ticking():
    """Transport polled every 10 ms in a helper thread (stands in for Live's tick)."""
    port = free_port()
    t = rs_transport.Transport(handler, port=port, max_commands_per_tick=2)
    assert t.start()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            t.poll()
            time.sleep(0.01)

    th = threading.Thread(target=loop, daemon=True)
    th.start()
    yield t, port
    stop.set()
    th.join()
    t.close()


def test_ping_roundtrip(ticking):
    _, port = ticking
    c = LiveClient(port=port, timeout=2)
    assert c.request("ping")["tempo"] == 174.0
    c.close()


def test_handler_exception_becomes_error_not_crash(ticking):
    _, port = ticking
    c = LiveClient(port=port, timeout=2)
    with pytest.raises(LiveError, match="kaboom"):
        c.request("boom")
    assert c.request("ping")  # still alive
    c.close()


def test_malformed_line_gets_error_response(ticking):
    _, port = ticking
    s = socket.create_connection(("127.0.0.1", port), timeout=2)
    s.sendall(b"{not json\n")
    data = b""
    while b"\n" not in data:
        data += s.recv(4096)
    assert b'"ok": false' in data
    s.close()


def test_large_response_partial_writes(ticking):
    _, port = ticking
    c = LiveClient(port=port, timeout=5)
    big = {"names": ["Pad été %d" % i for i in range(40000)]}  # ~800 KB reply
    assert c.request("echo", big) == big
    c.close()


def test_many_requests_respect_tick_budget(ticking):
    _, port = ticking
    c = LiveClient(port=port, timeout=5)
    for i in range(30):
        assert c.request("echo", {"i": i}) == {"i": i}
    c.close()


def test_client_disconnect_is_cleaned_up(ticking):
    t, port = ticking
    s = socket.create_connection(("127.0.0.1", port))
    time.sleep(0.05)
    s.close()
    time.sleep(0.05)
    assert t.clients == []
