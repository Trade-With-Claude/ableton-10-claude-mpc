# -*- coding: utf-8 -*-
"""Threadless, non-blocking TCP transport for the ClaudeMPC Remote Script.

Pure Python 2.7 / 3 compatible, no Live imports, so it can be unit-tested
outside Live. Live 10 starves background threads of the GIL, so everything
runs from poll(), which the control surface calls on each update_display()
tick (~100 ms) on Live's main thread.

Wire protocol: newline-delimited JSON.
  request  {"id": n, "cmd": "...", "params": {...}}
  response {"id": n, "ok": true, "result": ...} | {"id": n, "ok": false, "error": "..."}
"""
from __future__ import absolute_import

import errno
import json
import select
import socket

MAX_LINE_BYTES = 1024 * 1024
_WOULD_BLOCK = (errno.EAGAIN, errno.EWOULDBLOCK)


def _error_text(e):
    try:
        return u"%s: %s" % (type(e).__name__, e)
    except Exception:
        return repr(e)


class _Client(object):
    def __init__(self, sock):
        self.sock = sock
        self.inbuf = b""
        self.outbuf = b""


class Transport(object):
    def __init__(self, handler, host="127.0.0.1", port=9879, max_commands_per_tick=8, log=None):
        """handler(cmd, params) -> result; raise to send an error response."""
        self.handler = handler
        self.host = host
        self.port = port
        self.max_commands_per_tick = max_commands_per_tick
        self.log = log or (lambda msg: None)
        self.server = None
        self.clients = []
        self._bind_retry_ticks = 0

    # -- lifecycle -------------------------------------------------------
    def start(self):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen(4)
            srv.setblocking(False)
            self.server = srv
            self.log("listening on %s:%d" % (self.host, self.port))
            return True
        except socket.error as e:
            self.log("bind failed on port %d: %s (will retry)" % (self.port, _error_text(e)))
            self.server = None
            return False

    def close(self):
        for c in list(self.clients):
            self._drop(c)
        if self.server is not None:
            try:
                self.server.close()
            except socket.error:
                pass
            self.server = None

    # -- main tick -------------------------------------------------------
    def poll(self):
        if self.server is None:
            self._bind_retry_ticks += 1
            if self._bind_retry_ticks >= 50:  # ~5 s
                self._bind_retry_ticks = 0
                self.start()
            return

        readers = [self.server] + [c.sock for c in self.clients]
        writers = [c.sock for c in self.clients if c.outbuf]
        try:
            readable, writable, _ = select.select(readers, writers, [], 0)
        except (select.error, socket.error, ValueError) as e:
            self.log("select failed: %s" % _error_text(e))
            return

        if self.server in readable:
            self._accept()

        budget = self.max_commands_per_tick
        for c in list(self.clients):
            if c.sock in readable:
                self._read(c)
            budget = self._dispatch(c, budget)

        for c in list(self.clients):
            if c.outbuf:
                self._flush(c)

    # -- internals -------------------------------------------------------
    def _accept(self):
        while True:
            try:
                sock, _ = self.server.accept()
            except socket.error as e:
                if e.args and e.args[0] in _WOULD_BLOCK:
                    return
                self.log("accept failed: %s" % _error_text(e))
                return
            sock.setblocking(False)
            self.clients.append(_Client(sock))
            self.log("client connected")

    def _drop(self, c):
        try:
            c.sock.close()
        except socket.error:
            pass
        if c in self.clients:
            self.clients.remove(c)

    def _read(self, c):
        try:
            data = c.sock.recv(65536)
        except socket.error as e:
            if e.args and e.args[0] in _WOULD_BLOCK:
                return
            self._drop(c)
            return
        if not data:
            self._drop(c)
            return
        c.inbuf += data
        if len(c.inbuf) > MAX_LINE_BYTES and b"\n" not in c.inbuf:
            self.log("client line too long, dropping")
            self._drop(c)

    def _dispatch(self, c, budget):
        while budget > 0 and b"\n" in c.inbuf and c in self.clients:
            line, c.inbuf = c.inbuf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            budget -= 1
            self._queue(c, self._handle_line(line))
        return budget

    def _handle_line(self, line):
        req_id = None
        try:
            req = json.loads(line.decode("utf-8"))
            if not isinstance(req, dict) or "cmd" not in req:
                raise ValueError("request must be an object with 'cmd'")
            req_id = req.get("id")
            result = self.handler(req["cmd"], req.get("params") or {})
            return {"id": req_id, "ok": True, "result": result}
        except Exception as e:
            self.log("command error: %s" % _error_text(e))
            return {"id": req_id, "ok": False, "error": _error_text(e)}

    def _queue(self, c, resp):
        try:
            data = json.dumps(resp)
        except Exception as e:
            data = json.dumps({"id": resp.get("id"), "ok": False,
                               "error": u"unserializable result: " + _error_text(e)})
        c.outbuf += data.encode("utf-8") + b"\n"

    def _flush(self, c):
        # send() may write only part of the buffer: keep the rest for next tick
        try:
            sent = c.sock.send(c.outbuf)
        except socket.error as e:
            if e.args and e.args[0] in _WOULD_BLOCK:
                return
            self._drop(c)
            return
        c.outbuf = c.outbuf[sent:]
