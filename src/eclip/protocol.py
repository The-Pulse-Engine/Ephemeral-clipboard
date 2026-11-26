"""Wire protocol shared by the relay and the client. The spec is docs/PROTOCOL.md."""

import json
from enum import StrEnum
from typing import Any

VERSION = 1
MAX_MESSAGE = 64 * 1024  # bytes in one WebSocket frame, envelope included


class Error(StrEnum):
    INVALID_JSON = "invalid-json"
    INVALID_MESSAGE = "invalid-message"
    UNSUPPORTED_VERSION = "unsupported-version"
    UNKNOWN_ACTION = "unknown-action"
    ALREADY_IN_ROOM = "already-in-room"
    RELAY_FULL = "relay-full"
    ROOM_NOT_FOUND = "room-not-found"
    ROOM_FULL = "room-full"
    NOT_IN_ROOM = "not-in-room"
    NO_RECEIVER_YET = "no-receiver-yet"
    TOO_MANY_CONNECTIONS = "too-many-connections"
    EXPIRED = "expired"


def error(code: Error) -> str:
    return json.dumps({"type": "error", "error": code, "version": VERSION})


def parse(raw: str | bytes) -> dict[str, Any] | Error:
    """Parse one client message, or return the error code to send back."""
    try:
        message = json.loads(raw)
    # ValueError covers bad UTF-8 and huge ints, RecursionError deep nesting
    except (ValueError, RecursionError):
        return Error.INVALID_JSON
    if (
        not isinstance(message, dict)
        or not isinstance(message.get("action"), str)
        or not isinstance(message.get("nameplate"), str | None)
    ):
        return Error.INVALID_MESSAGE
    version = message.get("version")
    # type() check, because True == 1 and 1.0 == 1 in Python
    if message["action"] in ("claim", "join") and not (type(version) is int and version == VERSION):
        return Error.UNSUPPORTED_VERSION
    return message
