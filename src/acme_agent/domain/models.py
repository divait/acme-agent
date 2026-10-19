"""Domain models: enums, candidate profile and the stored conversation record."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

SCHEMA_VERSION: Literal["1.2"] = "1.2"


class Role(StrEnum):
    CREW_MEMBER = "crew_member"
    KITCHEN = "kitchen"
    DELIVERY_RIDER = "delivery_rider"


class Day(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


class Shift(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    NIGHT = "night"


class ScreeningStatus(StrEnum):
    MEETS_REQUIREMENTS = "meets_requirements"
    MISSING_REQUIREMENTS = "missing_requirements"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class EndReason(StrEnum):
    COMPLETED = "completed"
    DECLINED_CONSENT = "declined_consent"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"


class Speaker(StrEnum):
    AGENT = "agent"
    CANDIDATE = "candidate"


class SlotName(StrEnum):
    CONSENT_RECORDING = "consent_recording"
    ROLE = "role"
    FULL_NAME = "full_name"
    PHONE = "phone"
    EMAIL = "email"
    PREFERRED_STORE_ID = "preferred_store_id"
    AVAILABILITY = "availability"
    WEEKLY_HOURS = "weekly_hours"
    START_DATE = "start_date"
    RIGHT_TO_WORK = "right_to_work"
    IS_18_OR_OVER = "is_18_or_over"
    DRIVING_LICENCE = "driving_licence"
    OWN_VEHICLE = "own_vehicle"
    EXPERIENCE_MONTHS = "experience_months"
    EXPERIENCE_SUMMARY = "experience_summary"
    LANGUAGES = "languages"


class Availability(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: Day
    shift: Shift


class Store(BaseModel):
    id: str
    name: str
    city: str
    area: str
    country: str


ALWAYS_REQUIRED: tuple[SlotName, ...] = (
    SlotName.CONSENT_RECORDING,
    SlotName.ROLE,
    SlotName.FULL_NAME,
    SlotName.PHONE,
    SlotName.PREFERRED_STORE_ID,
    SlotName.AVAILABILITY,
    SlotName.WEEKLY_HOURS,
    SlotName.START_DATE,
    SlotName.RIGHT_TO_WORK,
    SlotName.IS_18_OR_OVER,
    SlotName.EXPERIENCE_MONTHS,
)
RIDER_REQUIRED: tuple[SlotName, ...] = (SlotName.DRIVING_LICENCE, SlotName.OWN_VEHICLE)


class CandidateProfile(BaseModel):
    """All slots are optional while the interview is in progress."""

    consent_recording: bool | None = None
    role: Role | None = None
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    preferred_store_id: str | None = None
    availability: list[Availability] = Field(default_factory=list)
    weekly_hours: int | None = None
    start_date: date | None = None
    right_to_work: bool | None = None
    is_18_or_over: bool | None = None
    driving_licence: bool | None = None
    own_vehicle: bool | None = None
    experience_months: int | None = None
    experience_summary: str | None = None
    languages: list[str] = Field(default_factory=list)

    def missing_required(self) -> list[SlotName]:
        """Required slots with no value; rider-only slots count only for delivery riders."""
        required = list(ALWAYS_REQUIRED)
        if self.role is Role.DELIVERY_RIDER:
            required.extend(RIDER_REQUIRED)
        missing: list[SlotName] = []
        for slot in required:
            value = getattr(self, slot.value)
            if value is None or value == []:
                missing.append(slot)
        return missing


class SwitchedLanguage(BaseModel):
    at_turn: int
    to: str


class LanguageInfo(BaseModel):
    detected: str | None = None
    switches: list[SwitchedLanguage] = Field(default_factory=list)


class ModelInfo(BaseModel):
    live: str
    text: str
    prompt_version: str


class SlotMeta(BaseModel):
    attempts: int = 0
    source: Literal["live_tool", "post_call", "prefill"] | None = None
    raw: str | None = None
    corrected: bool = False
    status: Literal["empty", "filled", "invalid", "unresolved", "not_applicable"] | None = None
    # Advisory natural-language reading of `raw`; never changes a value or the flow (ADR-015.5).
    cross_check: JsonValue | None = None
    cross_check_agrees: bool | None = None


class ReconciliationConflict(BaseModel):
    """A slot whose live value differs from the post-call extraction."""

    slot: SlotName
    live: JsonValue = None
    post_call: JsonValue = None
    # True when the slot was part of the read-back the candidate confirmed: informational only.
    confirmed_by_candidate: bool = False


class Screening(BaseModel):
    """Routing outcome. `knockouts`, `review_reasons` and `flags` hold rule ids."""

    status: ScreeningStatus
    knockouts: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    reconciliation_conflicts: list[ReconciliationConflict] = Field(default_factory=list)

    @property
    def rule_ids(self) -> list[str]:
        return [*self.knockouts, *self.review_reasons, *self.flags]


class Sentiment(BaseModel):
    avg: float | None = None
    min: float | None = None
    frustration_events: int = 0
    trend: str | None = None


class Summary(BaseModel):
    headline: str
    key_points: list[str] = Field(default_factory=list)
    candidate_questions: list[str] = Field(default_factory=list)
    recruiter_next_steps: list[str] = Field(default_factory=list)


class TranscriptTurn(BaseModel):
    turn: int
    speaker: Speaker
    text: str
    ts: datetime
    sentiment: float | None = None


class Event(BaseModel):
    ts: datetime
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ConversationRecord(BaseModel):
    schema_version: Literal["1.0", "1.1", "1.2"] = SCHEMA_VERSION
    conversation_id: str
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: EndReason | None = None
    channel: str
    language: LanguageInfo = Field(default_factory=LanguageInfo)
    model: ModelInfo
    candidate: CandidateProfile = Field(default_factory=CandidateProfile)
    slot_meta: dict[SlotName, SlotMeta] = Field(default_factory=dict)
    screening: Screening
    sentiment: Sentiment | None = None
    summary: Summary | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    previous_conversation_id: str | None = None
