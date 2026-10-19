"""Receive one client frame from a WebSocket, enforcing the size limits (TECH DESIGN 2.3)."""

from __future__ import annotations

from fastapi import WebSocket

from acme_agent.web.protocol import (
    AUDIO_MAX_BYTES,
    ClientMessage,
    ProtocolError,
    parse_client_message,
)


class FrameTooLargeError(Exception):
    """A frame exceeded its limit; the caller closes the socket with code 1009."""


async def receive_frame(ws: WebSocket) -> bytes | ClientMessage | ProtocolError | None:
    """Next frame: audio bytes, a parsed control message, a ProtocolError, or None on disconnect.

    Raises FrameTooLargeError for oversized audio or text frames.
    """
    message = await ws.receive()
    if message["type"] == "websocket.disconnect":
        return None
    data = message.get("bytes")
    if data is not None:
        if len(data) > AUDIO_MAX_BYTES:
            raise FrameTooLargeError("audio frame too large")
        return bytes(data)
    text = message.get("text")
    if text is None:
        return ProtocolError("malformed", "empty frame")
    parsed = parse_client_message(text)
    if isinstance(parsed, ProtocolError) and parsed.code == "too_large":
        raise FrameTooLargeError(parsed.message)
    return parsed
