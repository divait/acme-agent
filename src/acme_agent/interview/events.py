"""Tool results and domain events emitted by the interview controller."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, JsonValue

from acme_agent.domain.models import Event

Status = Literal[
    "ok", "invalid", "unresolved", "not_applicable", "unknown_field", "confirm_decline"
]

EventType = Literal[
    "slot_filled",
    "validation_failed",
    "slot_unresolved",
    "field_corrected",
    "phase_changed",
    "escalated",
    "interview_ended",
    "faq_answered",
    "faq_missed",
    "post_call_failed",
]


class EscalationReason(StrEnum):
    """Closed set of escalation reasons; free text never reaches the event log."""

    CANDIDATE_REQUEST = "candidate_request"
    FRUSTRATION = "frustration"
    TECHNICAL_ISSUE = "technical_issue"
    OTHER = "other"


# The controller calls `emit` once per event, synchronously, after appending it to its own
# list. Handlers must not raise or block (ADR-016.1).
Emit = Callable[[Event], None]


class ToolResult(BaseModel):
    """What `record_field` returns to the model (ADR-016.4). Always carries the next goal."""

    status: Status
    field: str
    normalized: JsonValue = None
    hint: str | None = None
    next_goal: str
    missing: list[str]
    progress: float

    def to_json(self) -> dict[str, JsonValue]:
        """JSON-serialisable dict for the tool response."""
        dumped: dict[str, JsonValue] = self.model_dump(mode="json")
        return dumped
