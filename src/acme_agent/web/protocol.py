"""WebSocket text-frame protocol (docs/TECHNICAL_DESIGN.md section 2).

Binary frames carry audio and are not modelled here; only the JSON control frames are.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

AUDIO_MAX_BYTES = 16384
TEXT_MAX_BYTES = 2048

# Close codes used by the gateway.
CLOSE_POLICY = 1008
CLOSE_TOO_BIG = 1009
CLOSE_DUPLICATE = 4409


class _Frame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- client -> server -------------------------------------------------------------------


class StartMessage(_Frame):
    type: Literal["start"] = "start"
    locale: str = Field(default="es-ES", max_length=16)


class TextMessage(_Frame):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1)


class EndMessage(_Frame):
    type: Literal["end"] = "end"


class PingMessage(_Frame):
    type: Literal["ping"] = "ping"


ClientMessage = Annotated[
    StartMessage | TextMessage | EndMessage | PingMessage, Field(discriminator="type")
]
_CLIENT_ADAPTER: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


# --- server -> client -------------------------------------------------------------------


class TranscriptMessage(_Frame):
    type: Literal["transcript"] = "transcript"
    speaker: Literal["candidate", "agent"]
    text: str
    final: bool
    turn: int


class InterruptedMessage(_Frame):
    type: Literal["interrupted"] = "interrupted"


class SlotMessage(_Frame):
    type: Literal["slot"] = "slot"
    name: str
    status: Literal["filled", "invalid", "unresolved"]
    value: str | None = None
    display: str | None = None
    progress: float = Field(ge=0.0, le=1.0)


class FaqMessage(_Frame):
    type: Literal["faq"] = "faq"
    question: str
    source: str | None = None


class StateMessage(_Frame):
    type: Literal["state"] = "state"
    phase: str


class EndedMessage(_Frame):
    type: Literal["ended"] = "ended"
    reason: str


class CompletedMessage(_Frame):
    type: Literal["completed"] = "completed"
    summary: dict[str, Any] | None = None
    status: str
    reasons: list[str] = []  # rule ids behind the status; shown only in the recruiter panel
    end_reason: str | None = None  # recruiter panel only
    sentiment: dict[str, Any] | None = None  # avg / min / trend / frustration_events
    # Final profile, slot -> {value, display, status, required}; post-call fills included.
    profile: dict[str, dict[str, Any]] | None = None
    complete: bool = False  # all required slots filled and the interview ended as completed


class ErrorMessage(_Frame):
    type: Literal["error"] = "error"
    code: str
    message: str


class PongMessage(_Frame):
    type: Literal["pong"] = "pong"


ServerMessage = (
    TranscriptMessage
    | InterruptedMessage
    | SlotMessage
    | FaqMessage
    | StateMessage
    | EndedMessage
    | CompletedMessage
    | ErrorMessage
    | PongMessage
)


def dump_server_message(message: ServerMessage) -> str:
    """JSON text for a server frame (None-valued optional fields are kept as null)."""
    return message.model_dump_json()


# --- parsing ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtocolError:
    """A client frame that cannot be accepted. `code` is machine-readable."""

    code: Literal["too_large", "malformed", "unknown_type", "invalid"]
    message: str


def parse_client_message(
    text: str,
) -> StartMessage | TextMessage | EndMessage | PingMessage | ProtocolError:
    """Parse one client text frame; never raises."""
    if len(text.encode("utf-8", errors="replace")) > TEXT_MAX_BYTES:
        return ProtocolError("too_large", f"text frame exceeds {TEXT_MAX_BYTES} bytes")
    try:
        raw = TypeAdapter(dict[str, Any]).validate_json(text)
    except ValidationError:
        return ProtocolError("malformed", "frame is not a JSON object")
    kind = raw.get("type")
    if kind not in ("start", "text", "end", "ping"):
        return ProtocolError("unknown_type", "unknown message type")
    try:
        return _CLIENT_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"] if p != kind)
        return ProtocolError("invalid", f"invalid {kind} message: {loc or first['type']}")
