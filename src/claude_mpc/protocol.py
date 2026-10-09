"""Newline-delimited JSON wire protocol shared with the Live Remote Script.

Request:  {"id": int, "cmd": str, "params": {...}}
Response: {"id": int, "ok": true, "result": ...} | {"id": int, "ok": false, "error": str}
"""

import json

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9879


class ProtocolError(Exception):
    """Malformed message on the wire."""


class LiveError(Exception):
    """The Remote Script answered with ok=false."""


def encode_request(req_id: int, cmd: str, params: dict | None = None) -> bytes:
    msg = {"id": req_id, "cmd": cmd, "params": params or {}}
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


def decode_response(line: bytes) -> dict:
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError(f"invalid JSON from Live: {e}") from e
    if not isinstance(msg, dict) or "id" not in msg or "ok" not in msg:
        raise ProtocolError(f"malformed response: {msg!r}")
    return msg
