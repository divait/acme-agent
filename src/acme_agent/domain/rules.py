"""Deterministic screening rules (ADR-009). No I/O, no clock: `today` arrives via facts."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from .models import (
    CandidateProfile,
    EndReason,
    ReconciliationConflict,
    Role,
    Screening,
    ScreeningStatus,
    SlotName,
)

KO_NO_RIGHT_TO_WORK = "KO_NO_RIGHT_TO_WORK"
KO_UNDER_18 = "KO_UNDER_18"
KO_NO_LICENCE = "KO_NO_LICENCE"

REVIEW_ESCALATED = "REVIEW_ESCALATED"
REVIEW_UNRESOLVED_SLOTS = "REVIEW_UNRESOLVED_SLOTS"
REVIEW_INCOMPLETE_CALL = "REVIEW_INCOMPLETE_CALL"
REVIEW_CONFLICT = "REVIEW_CONFLICT"
REVIEW_POST_CALL_FAILED = "REVIEW_POST_CALL_FAILED"

FLAG_NO_VEHICLE = "FLAG_NO_VEHICLE"
FLAG_LATE_START = "FLAG_LATE_START"
FLAG_LOW_HOURS = "FLAG_LOW_HOURS"
FLAG_FRUSTRATION = "FLAG_FRUSTRATION"
FLAG_RECRUITER_DECLINED = "FLAG_RECRUITER_DECLINED"

LATE_START_DAYS = 30
LOW_HOURS = 15
FRUSTRATION_FLAG_EVENTS = 2


class Facts(BaseModel):
    """Interview facts that are not part of the candidate profile."""

    today: date
    end_reason: EndReason | None = None
    escalated: bool = False
    frustration_events: int = 0
    recruiter_offered: bool = False
    unresolved_slots: list[SlotName] = Field(default_factory=list)
    reconciliation_conflicts: list[ReconciliationConflict] = Field(default_factory=list)
    post_call_failed: bool = False


def evaluate(profile: CandidateProfile, facts: Facts) -> Screening:
    """A failed post-call analysis always gives `needs_human_review` (ADR-008.4), even with
    knock-outs. Otherwise knock-outs give `missing_requirements`; else any review trigger
    gives `needs_human_review`; else `meets_requirements`. All reason lists
    (knockouts, review_reasons, flags) are always reported."""
    knockouts: list[str] = []
    if profile.right_to_work is False:
        knockouts.append(KO_NO_RIGHT_TO_WORK)
    if profile.is_18_or_over is False:
        knockouts.append(KO_UNDER_18)
    is_rider = profile.role is Role.DELIVERY_RIDER
    if is_rider and profile.driving_licence is False:
        knockouts.append(KO_NO_LICENCE)

    review: list[str] = []
    if facts.escalated:
        review.append(REVIEW_ESCALATED)
    if facts.unresolved_slots or profile.missing_required():
        review.append(REVIEW_UNRESOLVED_SLOTS)
    if facts.end_reason is not EndReason.COMPLETED:
        review.append(REVIEW_INCOMPLETE_CALL)
    if any(not c.confirmed_by_candidate for c in facts.reconciliation_conflicts):
        review.append(REVIEW_CONFLICT)
    if facts.post_call_failed:
        review.append(REVIEW_POST_CALL_FAILED)

    flags: list[str] = []
    if is_rider and profile.own_vehicle is False:
        flags.append(FLAG_NO_VEHICLE)
    if profile.start_date is not None and (profile.start_date - facts.today).days > LATE_START_DAYS:
        flags.append(FLAG_LATE_START)
    if profile.weekly_hours is not None and profile.weekly_hours < LOW_HOURS:
        flags.append(FLAG_LOW_HOURS)
    if facts.frustration_events >= FRUSTRATION_FLAG_EVENTS:
        flags.append(FLAG_FRUSTRATION)
    if facts.recruiter_offered and not facts.escalated and facts.end_reason is not None:
        flags.append(FLAG_RECRUITER_DECLINED)

    if facts.post_call_failed:
        status = ScreeningStatus.NEEDS_HUMAN_REVIEW
    elif knockouts:
        status = ScreeningStatus.MISSING_REQUIREMENTS
    elif review:
        status = ScreeningStatus.NEEDS_HUMAN_REVIEW
    else:
        status = ScreeningStatus.MEETS_REQUIREMENTS
    return Screening(
        status=status,
        knockouts=knockouts,
        review_reasons=review,
        flags=flags,
        reconciliation_conflicts=list(facts.reconciliation_conflicts),
    )
