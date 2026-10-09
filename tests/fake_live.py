"""Fake Live Remote Script: speaks the wire protocol over a real socket."""

import json
import socket
import threading


class FakeLive:
    def __init__(self, chunk_size: int | None = None):
        self.chunk_size = chunk_size  # send replies in small pieces to exercise partial reads
        self.handlers = {
            "ping": lambda p: {"live_version": "10.1.43", "tempo": 174.0, "script_version": "fake"},
            "echo": lambda p: p,
        }
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        self.raw_reply: bytes | None = None  # if set, sent verbatim instead of a real reply
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _send(self, conn, data: bytes) -> None:
        if not self.chunk_size:
            conn.sendall(data)
            return
        for i in range(0, len(data), self.chunk_size):
            conn.sendall(data[i : i + self.chunk_size])

    def _handle(self, conn) -> None:
        buf = b""
        with conn:
            while True:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if self.raw_reply is not None:
                        self._send(conn, self.raw_reply)
                        continue
                    req = json.loads(line)
                    h = self.handlers.get(req["cmd"])
                    if h is None:
                        resp = {"id": req["id"], "ok": False, "error": "unknown command: " + req["cmd"]}
                    else:
                        resp = {"id": req["id"], "ok": True, "result": h(req.get("params", {}))}
                    self._send(conn, (json.dumps(resp) + "\n").encode())

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def close(self) -> None:
        self._stop = True
        self._srv.close()
