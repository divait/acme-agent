"""Structured-output schemas for post-call analysis (ADR-008.3, ADR-015.8).

A list of per-slot items with an enum slot name is used instead of a dict because the
Gemini response schema cannot express free-form object keys.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from acme_agent.domain.models import SlotName
from acme_agent.domain.models import Summary as RecordSummary

HEADLINE_MAX = 140


class SlotExtraction(BaseModel):
    """One slot as heard in the transcript. `value` is null when the candidate never said it."""

    slot: SlotName
    value: str | None = Field(
        default=None,
        description=(
            "Canonical value for canonical slots, or the candidate's own words for "
            "full_name, phone, email and preferred_store_id; null if not said."
        ),
    )
    said: str | None = Field(
        default=None, description="The candidate's exact words that support the value."
    )
    turn: int | None = Field(
        default=None, description="Turn number of the candidate message that contains it."
    )


class ExtractionResult(BaseModel):
    slots: list[SlotExtraction] = Field(default_factory=list)


class Summary(BaseModel):
    """Recruiter-facing English summary (response schema; stored as the record's `Summary`)."""

    headline: str = Field(max_length=HEADLINE_MAX)
    key_points: list[str] = Field(min_length=3, max_length=6)
    candidate_questions: list[str] = Field(default_factory=list)
    recruiter_next_steps: list[str] = Field(default_factory=list)

    def to_record(self) -> RecordSummary:
        return RecordSummary.model_validate(self.model_dump())
