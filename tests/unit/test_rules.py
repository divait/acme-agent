from datetime import date, timedelta

import pytest

from acme_agent.domain import rules
from acme_agent.domain.models import (
    Availability,
    CandidateProfile,
    Day,
    EndReason,
    ReconciliationConflict,
    Role,
    ScreeningStatus,
    Shift,
    SlotName,
)
from acme_agent.domain.rules import Facts, evaluate

TODAY = date(2026, 10, 18)
CONFLICT = ReconciliationConflict(
    slot=SlotName.PHONE, live="+34600123456", post_call="+34600123457"
)


def profile(**over: object) -> CandidateProfile:
    base: dict[str, object] = {
        "consent_recording": True,
        "role": Role.KITCHEN,
        "full_name": "Laura Gómez",
        "phone": "+34600123456",
        "preferred_store_id": "vlc-ruzafa",
        "availability": [Availability(day=Day.MON, shift=Shift.MORNING)],
        "weekly_hours": 25,
        "start_date": TODAY + timedelta(days=7),
        "right_to_work": True,
        "is_18_or_over": True,
        "experience_months": 12,
    }
    base.update(over)
    return CandidateProfile.model_validate(base)


def rider(**over: object) -> CandidateProfile:
    return profile(role=Role.DELIVERY_RIDER, driving_licence=True, own_vehicle=True, **over)


def facts(**over: object) -> Facts:
    base: dict[str, object] = {"today": TODAY, "end_reason": EndReason.COMPLETED}
    base.update(over)
    return Facts.model_validate(base)


M, R, H = (
    ScreeningStatus.MEETS_REQUIREMENTS,
    ScreeningStatus.MISSING_REQUIREMENTS,
    ScreeningStatus.NEEDS_HUMAN_REVIEW,
)

CASES = [
    ("happy", profile(), facts(), M, []),
    ("happy_rider", rider(), facts(), M, []),
    ("ko_rtw", profile(right_to_work=False), facts(), R, [rules.KO_NO_RIGHT_TO_WORK]),
    ("ko_minor", profile(is_18_or_over=False), facts(), R, [rules.KO_UNDER_18]),
    (
        "ko_licence",
        profile(role=Role.DELIVERY_RIDER, driving_licence=False, own_vehicle=True),
        facts(),
        R,
        [rules.KO_NO_LICENCE],
    ),
    ("licence_ignored_non_rider", profile(driving_licence=False), facts(), M, []),
    (
        "ko_multiple",
        profile(right_to_work=False, is_18_or_over=False),
        facts(),
        R,
        [rules.KO_NO_RIGHT_TO_WORK, rules.KO_UNDER_18],
    ),
    ("review_escalated", profile(), facts(escalated=True), H, [rules.REVIEW_ESCALATED]),
    (
        "review_unresolved_facts",
        profile(),
        facts(unresolved_slots=[SlotName.PHONE]),
        H,
        [rules.REVIEW_UNRESOLVED_SLOTS],
    ),
    (
        "review_missing_required",
        profile(phone=None),
        facts(),
        H,
        [rules.REVIEW_UNRESOLVED_SLOTS],
    ),
    (
        "review_rider_missing_licence_answer",
        profile(role=Role.DELIVERY_RIDER, own_vehicle=True),
        facts(),
        H,
        [rules.REVIEW_UNRESOLVED_SLOTS],
    ),
    (
        "review_abandoned",
        profile(),
        facts(end_reason=EndReason.ABANDONED),
        H,
        [rules.REVIEW_INCOMPLETE_CALL],
    ),
    (
        "review_declined",
        profile(),
        facts(end_reason=EndReason.DECLINED_CONSENT),
        H,
        [rules.REVIEW_INCOMPLETE_CALL],
    ),
    (
        "review_no_end_reason",
        profile(),
        facts(end_reason=None),
        H,
        [rules.REVIEW_INCOMPLETE_CALL],
    ),
    (
        "review_conflict",
        profile(),
        facts(reconciliation_conflicts=[CONFLICT]),
        H,
        [rules.REVIEW_CONFLICT],
    ),
    (
        "review_post_call_failed",
        profile(),
        facts(post_call_failed=True),
        H,
        [rules.REVIEW_POST_CALL_FAILED],
    ),
    (
        "post_call_failed_beats_knockout",
        profile(right_to_work=False),
        facts(post_call_failed=True),
        H,
        [rules.KO_NO_RIGHT_TO_WORK, rules.REVIEW_POST_CALL_FAILED],
    ),
    (
        "ko_and_review_both_reported",
        profile(right_to_work=False),
        facts(escalated=True),
        R,
        [rules.KO_NO_RIGHT_TO_WORK, rules.REVIEW_ESCALATED],
    ),
    (
        "flag_no_vehicle",
        profile(role=Role.DELIVERY_RIDER, driving_licence=True, own_vehicle=False),
        facts(),
        M,
        [rules.FLAG_NO_VEHICLE],
    ),
    (
        "flag_late_start",
        profile(start_date=TODAY + timedelta(days=31)),
        facts(),
        M,
        [rules.FLAG_LATE_START],
    ),
    ("start_30_days_no_flag", profile(start_date=TODAY + timedelta(days=30)), facts(), M, []),
    ("flag_low_hours", profile(weekly_hours=14), facts(), M, [rules.FLAG_LOW_HOURS]),
    ("hours_15_no_flag", profile(weekly_hours=15), facts(), M, []),
    (
        "flags_with_review",
        profile(weekly_hours=10),
        facts(escalated=True),
        H,
        [rules.REVIEW_ESCALATED, rules.FLAG_LOW_HOURS],
    ),
]


@pytest.mark.parametrize(
    ("prof", "fct", "status", "ids"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_evaluate(
    prof: CandidateProfile, fct: Facts, status: ScreeningStatus, ids: list[str]
) -> None:
    result = evaluate(prof, fct)
    assert result.status is status
    assert result.rule_ids == ids


def test_conflicts_are_carried_into_result() -> None:
    result = evaluate(profile(), facts(reconciliation_conflicts=[CONFLICT]))
    assert result.reconciliation_conflicts == [CONFLICT]


def test_escalated_call_reports_escalated_and_incomplete() -> None:
    result = evaluate(profile(), facts(escalated=True, end_reason=EndReason.ESCALATED))
    assert result.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    assert rules.REVIEW_ESCALATED in result.review_reasons
    assert rules.REVIEW_INCOMPLETE_CALL in result.review_reasons


def test_frustration_flag_needs_two_events() -> None:
    assert rules.FLAG_FRUSTRATION not in evaluate(profile(), facts(frustration_events=1)).flags
    result = evaluate(profile(), facts(frustration_events=2))
    assert rules.FLAG_FRUSTRATION in result.flags
    assert result.status is ScreeningStatus.MEETS_REQUIREMENTS  # flags never change status


def test_recruiter_declined_flag_only_without_escalation() -> None:
    ended = facts(recruiter_offered=True, end_reason=EndReason.ABANDONED)
    assert rules.FLAG_RECRUITER_DECLINED in evaluate(profile(), ended).flags
    escalated = facts(recruiter_offered=True, escalated=True, end_reason=EndReason.ESCALATED)
    result = evaluate(profile(), escalated)
    assert rules.FLAG_RECRUITER_DECLINED not in result.flags
    assert rules.REVIEW_ESCALATED in result.review_reasons
    assert rules.FLAG_RECRUITER_DECLINED not in evaluate(profile(), facts()).flags
