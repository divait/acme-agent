"""InterviewController: record statuses, retries, hooks, goals and ADR-015 routing."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from acme_agent.domain.models import Event, Role, SlotName
from acme_agent.domain.validators import ParseContext
from acme_agent.interview.controller import (
    CLOSE_DECLINED,
    CONFIRM_GOAL,
    InterviewController,
    Phase,
)
from acme_agent.interview.slots import SLOT_BY_NAME

MakeCtx = Callable[..., ParseContext]
NOW = datetime(2026, 10, 18, 20, 30, tzinfo=UTC)  # Sunday 22:30 Madrid, Monday 05:30 Tokyo


class Harness:
    def __init__(self, ctx: ParseContext) -> None:
        self.emitted: list[Event] = []
        counter = iter(range(1000))
        self.controller = InterviewController(
            ctx, lambda: NOW, lambda: f"id-{next(counter)}", self.emitted.append
        )

    def types(self) -> list[str]:
        return [e.type for e in self.emitted]


@pytest.fixture
def h(make_ctx: MakeCtx) -> Harness:
    return Harness(make_ctx())


@pytest.fixture
def c(h: Harness) -> InterviewController:
    return h.controller


def country(c: InterviewController) -> str:
    return c.ctx.country


def phase(c: InterviewController) -> Phase:
    return c.phase


def consent(c: InterviewController) -> None:
    c.record("consent_recording", "yes", "sí claro")


# A full valid answer set for a crew member, in asking order.
CREW = [
    ("role", "crew_member"),
    ("full_name", "Laura Gil"),
    ("phone", "600 123 456"),
    ("preferred_store_id", "Sol"),
    ("availability", "mon:morning,sat:night"),
    ("weekly_hours", "25"),
    ("start_date", "2026-11-03"),
    ("right_to_work", "yes"),
    ("is_18_or_over", "yes"),
    ("experience_months", "18"),
]


def test_every_response_has_status_goal_and_missing(c: InterviewController) -> None:
    for field, value in [
        ("nope", "x"),
        ("driving_licence", "yes"),
        ("consent_recording", "maybe"),
        ("consent_recording", "yes"),
    ]:
        data = c.record(field, value).to_json()
        assert {"status", "field", "normalized", "hint", "next_goal", "missing", "progress"} <= set(
            data
        )
        assert data["next_goal"]
        assert isinstance(data["missing"], list)


def test_ok_status_and_normalized(c: InterviewController) -> None:
    result = c.record("consent_recording", "yes", "claro")
    assert result.status == "ok"
    assert result.normalized is True
    assert c.profile.consent_recording is True
    assert c.slot_meta[SlotName.CONSENT_RECORDING].raw == "claro"
    assert c.slot_meta[SlotName.CONSENT_RECORDING].source == "live_tool"
    assert phase(c) is Phase.COLLECTING


def test_unknown_field_lists_allowed(c: InterviewController) -> None:
    result = c.record("shoe_size", "42")
    assert result.status == "unknown_field"
    assert "full_name" in (result.hint or "")
    assert result.field == "shoe_size"


def test_inactive_conditional_slot_is_not_applicable(c: InterviewController) -> None:
    consent(c)
    c.record("role", "kitchen")
    result = c.record("driving_licence", "yes")
    assert result.status == "not_applicable"
    assert c.profile.driving_licence is None


def test_canonical_natural_language_is_invalid_with_format_hint(c: InterviewController) -> None:
    consent(c)
    result = c.record("start_date", "next monday", "next monday")
    assert result.status == "invalid"
    assert "YYYY-MM-DD" in (result.hint or "")
    assert c.profile.start_date is None


def test_verbatim_parsed_from_words_and_said_stored(c: InterviewController) -> None:
    consent(c)
    result = c.record("phone", "seis cero cero uno dos tres cuatro cinco seis", "seis cero cero")
    assert result.status == "ok"
    assert result.normalized == "+34600123456"
    assert c.slot_meta[SlotName.PHONE].raw == "seis cero cero"


def test_verbatim_falls_back_to_said_when_value_empty(c: InterviewController) -> None:
    consent(c)
    result = c.record("full_name", "", "me llamo laura gil")
    assert result.status == "ok"
    assert c.profile.full_name == "Laura Gil"


def test_retry_exhaustion_marks_unresolved(c: InterviewController, h: Harness) -> None:
    consent(c)
    first = c.record("email", "juan")
    second = c.record("email", "juan arroba")
    third = c.record("email", "juan@")
    assert [first.status, second.status, third.status] == ["invalid", "invalid", "unresolved"]
    assert c.slot_meta[SlotName.EMAIL].status == "unresolved"
    assert c.slot_meta[SlotName.EMAIL].attempts == 3
    assert h.types().count("validation_failed") == 3
    assert "slot_unresolved" in h.types()


def test_required_unresolved_is_skipped_by_goal(c: InterviewController) -> None:
    consent(c)
    c.record("role", "crew_member")
    for _ in range(3):
        c.record("full_name", "123")
    assert c.slot_meta[SlotName.FULL_NAME].status == "unresolved"
    assert "contact phone" in c.next_goal()
    assert "full_name" in c.missing()
    assert c.progress() == 0.27


def test_invalid_goal_includes_hint_and_failures_reset_on_success(c: InterviewController) -> None:
    consent(c)
    c.record("role", "crew_member")
    c.record("full_name", "Laura Gil")
    c.record("phone", "123")
    assert "not valid" in c.next_goal()
    c.record("phone", "600 123 456")
    c.record("phone", "600 123 457")  # valid change, counts as correction
    assert c.slot_meta[SlotName.PHONE].status == "filled"


def test_correction_overwrites_and_emits(c: InterviewController, h: Harness) -> None:
    consent(c)
    c.record("weekly_hours", "20")
    result = c.record("weekly_hours", "30")
    assert result.status == "ok"
    assert c.profile.weekly_hours == 30
    assert c.slot_meta[SlotName.WEEKLY_HOURS].corrected is True
    corrected = [e for e in h.emitted if e.type == "field_corrected"]
    assert len(corrected) == 1
    assert corrected[0].payload == {"field": "weekly_hours", "old": 20, "new": 30}


def test_same_value_is_not_a_correction(c: InterviewController, h: Harness) -> None:
    consent(c)
    c.record("weekly_hours", "20")
    c.record("weekly_hours", "20")
    assert not c.slot_meta[SlotName.WEEKLY_HOURS].corrected
    assert "field_corrected" not in h.types()


def test_failed_correction_keeps_stored_value(c: InterviewController) -> None:
    consent(c)
    c.record("weekly_hours", "20")
    for _ in range(4):
        result = c.record("weekly_hours", "99")
    assert result.status == "invalid"
    assert c.profile.weekly_hours == 20
    assert c.slot_meta[SlotName.WEEKLY_HOURS].status == "filled"


def test_role_change_to_rider_and_back(c: InterviewController) -> None:
    consent(c)
    c.record("role", "crew_member")
    assert "driving_licence" not in c.missing()
    c.record("role", "delivery_rider")
    assert {"driving_licence", "own_vehicle"} <= set(c.missing())
    assert c.record("driving_licence", "yes").status == "ok"
    assert c.record("own_vehicle", "no").status == "ok"
    assert c.profile.own_vehicle is False
    c.record("role", "kitchen")
    assert c.profile.role is Role.KITCHEN
    assert c.profile.driving_licence is None
    assert c.profile.own_vehicle is None
    assert SlotName.DRIVING_LICENCE not in c.slot_meta
    assert SlotName.OWN_VEHICLE not in c.slot_meta
    assert "driving_licence" not in c.missing()


def test_store_hook_sets_session_country(c: InterviewController) -> None:
    consent(c)
    assert country(c) == "ES"
    c.record("preferred_store_id", "Polanco")
    assert c.profile.preferred_store_id == "cdmx-polanco"
    assert country(c) == "MX"
    assert c.record("phone", "55 1234 5678").normalized == "+525512345678"
    c.record("preferred_store_id", "Sol")
    assert country(c) == "ES"


def test_phone_from_other_country_is_accepted(h: Harness, c: InterviewController) -> None:
    consent(c)
    assert c.record("phone", "55 1234 5678").normalized == "+525512345678"


def test_consent_declined_closes(c: InterviewController, h: Harness) -> None:
    assert c.record("consent_recording", "no", "no gracias").status == "confirm_decline"
    result = c.record("consent_recording", "no", "no gracias")
    assert result.status == "ok"
    assert phase(c) is Phase.CLOSING
    assert result.next_goal == CLOSE_DECLINED
    assert "declined_consent" in result.next_goal
    assert "phase_changed" in h.types()


def test_consent_unresolved_is_treated_as_declined(c: InterviewController) -> None:
    for _ in range(3):
        c.record("consent_recording", "quizás")
    assert phase(c) is Phase.CLOSING
    assert c.next_goal() == CLOSE_DECLINED


def test_next_goal_ordering_and_confirmation(c: InterviewController, h: Harness) -> None:
    assert phase(c) is Phase.GREETING
    assert "record" in c.start()
    assert phase(c) is Phase.CONSENT
    assert c.next_goal() == SLOT_BY_NAME[SlotName.CONSENT_RECORDING].ask
    consent(c)
    for field, value in CREW:
        expected = SLOT_BY_NAME[SlotName(field)].ask
        assert c.next_goal() == expected
        assert c.record(field, value).status == "ok"
    assert c.next_goal() == CONFIRM_GOAL
    assert phase(c) is Phase.CONFIRMATION
    assert c.missing() == []
    assert c.progress() == 1.0
    assert h.types().count("phase_changed") == 3  # greeting>consent>collecting>confirmation


def test_optional_slots_are_not_asked(c: InterviewController) -> None:
    consent(c)
    for field, value in CREW:
        c.record(field, value)
    assert c.next_goal() == CONFIRM_GOAL
    assert c.profile.email is None


def test_multi_field_first_sentence_skips_filled_slots(c: InterviewController) -> None:
    consent(c)
    c.record("role", "delivery_rider")
    c.record("full_name", "Laura Gil")
    c.record("preferred_store_id", "Ruzafa")
    c.record("availability", "mon:morning,tue:morning")
    assert c.next_goal() == SLOT_BY_NAME[SlotName.PHONE].ask


def test_role_change_after_confirmation_reopens_collecting(c: InterviewController) -> None:
    consent(c)
    for field, value in CREW:
        c.record(field, value)
    assert c.next_goal() == CONFIRM_GOAL
    c.record("role", "delivery_rider")
    assert c.next_goal() == SLOT_BY_NAME[SlotName.DRIVING_LICENCE].ask
    assert phase(c) is Phase.COLLECTING


def test_ended_phase_goal(c: InterviewController) -> None:
    c.phase = Phase.ENDED
    assert "ended" in c.next_goal()


def test_closing_goal_after_completion(c: InterviewController) -> None:
    consent(c)
    for field, value in CREW:
        c.record(field, value)
    c.next_goal()
    c.phase = Phase.CLOSING
    assert "end_interview" in c.next_goal()


def test_cross_check_disagreement_changes_nothing(c: InterviewController) -> None:
    consent(c)
    goal_before = c.next_goal()
    result = c.record("right_to_work", "yes", "no, no tengo permiso")
    meta = c.slot_meta[SlotName.RIGHT_TO_WORK]
    assert result.status == "ok"
    assert c.profile.right_to_work is True
    assert meta.cross_check is False
    assert meta.cross_check_agrees is False
    assert c.next_goal() == goal_before  # the advisory reading does not alter the flow
    assert "right_to_work" not in c.missing()


def test_cross_check_agreement_and_set_comparison(c: InterviewController) -> None:
    consent(c)
    c.record("languages", "en,es", "español e inglés")
    meta = c.slot_meta[SlotName.LANGUAGES]
    assert meta.cross_check_agrees is True
    c.record("availability", "sat:morning,sat:night", "los sábados por la mañana y por la noche")
    assert c.slot_meta[SlotName.AVAILABILITY].cross_check_agrees is True
    assert c.slot_meta[SlotName.AVAILABILITY].cross_check == [
        {"day": "sat", "shift": "morning"},
        {"day": "sat", "shift": "night"},
    ]


def test_cross_check_issue_is_recorded_as_code(c: InterviewController) -> None:
    consent(c)
    c.record("weekly_hours", "20", "banana")
    meta = c.slot_meta[SlotName.WEEKLY_HOURS]
    assert isinstance(meta.cross_check, dict)
    assert "issue" in meta.cross_check
    assert meta.cross_check_agrees is None


def test_no_cross_check_without_said(c: InterviewController) -> None:
    consent(c)
    c.record("weekly_hours", "20")
    meta = c.slot_meta[SlotName.WEEKLY_HOURS]
    assert meta.cross_check is None
    assert meta.cross_check_agrees is None


def test_events_are_kept_and_emitted(c: InterviewController, h: Harness) -> None:
    consent(c)
    c.record("weekly_hours", "20", "veinte")
    assert h.emitted == c.events
    assert c.events[-1].type == "slot_filled"
    assert c.events[-1].payload["field"] == "weekly_hours"
    assert c.events[-1].ts == NOW


def test_date_context(c: InterviewController) -> None:
    note = c.date_context()
    # 20:30 UTC is 22:30 in Madrid (CEST): still Sunday.
    assert "2026-10-18" in note
    assert "Sunday" in note
    assert "Europe/Madrid" in note


def test_date_context_uses_the_configured_timezone(make_ctx: MakeCtx) -> None:
    ctrl = InterviewController(make_ctx(), lambda: NOW, lambda: "x", lambda e: None, "Asia/Tokyo")
    note = ctrl.date_context()
    assert "2026-10-19" in note
    assert "Monday" in note
    assert "Asia/Tokyo" in note


def test_note_faq_emits_events_only(h: Harness) -> None:
    c = h.controller
    c.start()
    before = (c.phase, c.snapshot())
    c.note_faq("pay?", True, "faq_en#pay")
    c.note_faq("parking?", False)
    assert h.types()[-2:] == ["faq_answered", "faq_missed"]
    assert h.emitted[-2].payload == {"question": "pay?", "source": "faq_en#pay"}
    assert h.emitted[-1].payload == {"question": "parking?"}
    assert (c.phase, c.snapshot()) == before
