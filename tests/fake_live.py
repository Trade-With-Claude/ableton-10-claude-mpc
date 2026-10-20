"""Fake Live Remote Script: speaks the wire protocol over a real socket."""

import json
import pathlib
import socket
import sys
import threading

from fake_lom import FakeLoader, dnb_song

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"))
import build  # noqa: E402
import lom  # noqa: E402
import ops  # noqa: E402
import recorder  # noqa: E402
import wavetable  # noqa: E402


class FakeLive:
    def __init__(self, chunk_size: int | None = None):
        self.chunk_size = chunk_size  # send replies in small pieces to exercise partial reads
        self.handlers = {
            "ping": lambda p: {"live_version": "10.1.43", "tempo": 174.0, "is_playing": self.playing,
                               "script_version": "fake"},
            "transport": self._transport,
            "echo": lambda p: p,
            "get_session": lambda p: lom.serialize_session(self.song),
            "get_device_params": self._device_params,
            "get_meters": self._meters,
            "apply": lambda p: ops.apply(self.song, p["ops"], self.loader),
            "automation_record": lambda p: self.recorder.start(self.song, **p),
            "automation_status": self._automation_status,
            "automation_abort": self._automation_abort,
            "create_instrument_track": lambda p: build.create_instrument_track(
                self.song, self.loader, **p),
            "wavetable_get": lambda p: wavetable.read(self._dev(p)),
            "wavetable_set": lambda p: wavetable.apply(self.song, self._dev(p), p["settings"]),
        }
        self.recorder = recorder.Recorder()
        self.ticks_per_poll = 5  # update_display ticks simulated per status poll
        self.abort_calls = 0
        self.song = dnb_song()
        self.loader = FakeLoader()
        self.meter_reads = 0
        self.playing = False
        self.transport_calls: list[bool] = []
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        self.raw_reply: bytes | None = None  # if set, sent verbatim instead of a real reply
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _dev(self, p):
        return lom.resolve_device(lom.resolve_track(self.song, p["kind"], p.get("index", 0)), p.get("path"))

    def _device_params(self, p):
        track = lom.resolve_track(self.song, p["kind"], p.get("index", 0))
        device = lom.resolve_device(track, p.get("path"))
        return {"track": track.name, "device": lom.serialize_device(device, p.get("path")),
                "params": lom.serialize_params(device, p.get("query"))}

    def _transport(self, p):
        self.transport_calls.append(bool(p["play"]))
        self.playing = bool(p["play"])
        return {"is_playing": self.playing}

    def _automation_abort(self, p):
        self.abort_calls += 1
        return self.recorder.abort("aborted by request")

    def _automation_status(self, p):
        # Live ticks ~10x/s; simulate a few ticks (and the playhead moving) per poll
        beats_per_tick = 0.1 * self.song.tempo / 60.0
        for _ in range(self.ticks_per_poll):
            if self.song.is_playing:
                self.song.current_song_time += beats_per_tick
            self.recorder.tick()
        return self.recorder.status()

    def _meters(self, p):
        # master peaks on the 2nd read only, to exercise peak-hold
        self.meter_reads += 1
        out = lom.read_meters(self.song)
        if self.meter_reads == 2:
            out[-1]["left"] = 1.0
        return out

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
                        try:
                            resp = {"id": req["id"], "ok": True, "result": h(req.get("params", {}))}
                        except Exception as e:
                            resp = {"id": req["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}
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
