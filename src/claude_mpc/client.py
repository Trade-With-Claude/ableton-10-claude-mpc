"""Blocking TCP client for the ClaudeMPC Remote Script."""

import itertools
import socket
import threading

from .protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    LiveError,
    ProtocolError,
    decode_response,
    encode_request,
)

# Safe to resend after a lost reply. Anything else may have run in Live already
# (one apply = one undo step), so it is never sent twice.
READ_ONLY = frozenset(
    {"ping", "get_session", "get_device_params", "get_meters", "automation_status", "wavetable_get"}
)


class LiveClient:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._sent = False  # the current request reached the socket

    def _connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise ConnectionError(
                f"Cannot reach Live on {self.host}:{self.port} ({e}). Is Live open, with the "
                f"ClaudeMPC control surface selected in a free slot (Preferences > Link/MIDI, "
                f"Input/Output = None)? If another app uses the port, set CLAUDE_MPC_PORT."
            ) from e
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._buf = b""

    def _alive(self) -> bool:
        """False if the cached socket was closed by Live (quit, surface re-selected)."""
        assert self._sock is not None
        try:
            self._sock.setblocking(False)
            return self._sock.recv(1, socket.MSG_PEEK) != b""
        except BlockingIOError:
            return True  # open, nothing pending
        except OSError:
            return False
        finally:
            if self._sock is not None:
                self._sock.settimeout(self.timeout)

    def _readline(self) -> bytes:
        assert self._sock is not None
        while b"\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Live closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    def _roundtrip(self, req_id: int, payload: bytes) -> dict:
        if self._sock is not None and not self._alive():
            self.close()
        if self._sock is None:
            self._connect()
        assert self._sock is not None
        self._sent = False
        self._sock.sendall(payload)
        self._sent = True
        while True:
            msg = decode_response(self._readline())
            if msg["id"] == req_id:
                return msg
            # stale reply from a previously timed-out request: drop it

    def request(self, cmd: str, params: dict | None = None):
        """Send a command and return its result, raising LiveError on ok=false."""
        with self._lock:
            req_id = next(self._ids)
            payload = encode_request(req_id, cmd, params)
            try:
                msg = self._roundtrip(req_id, payload)
            except ConnectionError as e:
                self.close()
                if self._sent and cmd not in READ_ONLY:
                    raise ConnectionError(
                        f"Connection to Live lost after sending '{cmd}': it may or may not have "
                        f"been applied. Check with get_session before retrying."
                    ) from e
                # one reconnect attempt (Live restarted / surface re-selected)
                try:
                    msg = self._roundtrip(req_id, payload)
                except ConnectionError as e2:
                    self.close()
                    if self._sent:
                        raise ConnectionError(
                            f"Connection to Live lost during '{cmd}' (Live quit, or the ClaudeMPC "
                            f"surface was re-selected). Retry once Live is back."
                        ) from e2
                    raise
            except socket.timeout as e:
                self.close()
                maybe = "" if cmd in READ_ONLY else " It may or may not have been applied; check with get_session."
                raise TimeoutError(
                    f"Live did not answer '{cmd}' within {self.timeout}s. Live may be busy (loading, "
                    f"a long batch) or blocked by a dialog: click in Live, close any dialog, and "
                    f"retry.{maybe}"
                ) from e
            except ProtocolError:
                self.close()
                raise
        if not msg["ok"]:
            raise LiveError(msg.get("error", "unknown error"))
        return msg.get("result")
