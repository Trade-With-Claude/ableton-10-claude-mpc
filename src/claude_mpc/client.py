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


class LiveClient:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def _connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise ConnectionError(
                f"Cannot reach Live on {self.host}:{self.port} — is Live open with the "
                f"ClaudeMPC control surface selected? ({e})"
            ) from e
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._buf = b""

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
        if self._sock is None:
            self._connect()
        assert self._sock is not None
        self._sock.sendall(payload)
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
            except (BrokenPipeError, ConnectionResetError, ConnectionError):
                # one reconnect attempt (Live restarted / surface re-selected)
                self.close()
                try:
                    msg = self._roundtrip(req_id, payload)
                except Exception:
                    self.close()
                    raise
            except socket.timeout as e:
                self.close()
                raise TimeoutError(f"Live did not answer '{cmd}' within {self.timeout}s") from e
            except ProtocolError:
                self.close()
                raise
        if not msg["ok"]:
            raise LiveError(msg.get("error", "unknown error"))
        return msg.get("result")
