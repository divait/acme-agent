"""InterviewController part 2: confirmation, escalation, ending, hooks, prefill, record."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest

from acme_agent.domain.models import (
    Availability,
    CandidateProfile,
    Day,
    EndReason,
    Event,
    ModelInfo,
    Role,
    ScreeningStatus,
    Shift,
    SlotName,
)
from acme_agent.domain.validators import ParseContext
from acme_agent.interview.controller import (
    CLOSE_DECLINED,
    CONFIRM_DECLINE_GOAL,
    CONFIRM_GOAL,
    ESCALATED_ASK_PHONE_GOAL,
    ESCALATED_GOAL,
    ESCALATED_NO_CONSENT_GOAL,
    FRUSTRATION_NOTE,
    HUMAN_REQUEST_NOTE,
    InterviewController,
    Phase,
)
from acme_agent.interview.slots import SLOT_BY_NAME

MakeCtx = Callable[..., ParseContext]
NOW = datetime(2026, 10, 18, 20, 30, tzinfo=UTC)
MODEL = ModelInfo(live="live-x", text="text-x", prompt_version="p1")

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


@pytest.fixture
def emitted() -> list[Event]:
    return []


@pytest.fixture
def c(make_ctx: MakeCtx, emitted: list[Event]) -> InterviewController:
    counter = iter(range(1000))
    return InterviewController(
        make_ctx(), lambda: NOW, lambda: f"T-{next(counter)}", emitted.append
    )


def phase(c: InterviewController) -> Phase:
    return c.phase  # avoids mypy narrowing across method calls


def fill_all(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    for field, value in CREW:
        c.record(field, value)


def at_confirmation(c: InterviewController) -> None:
    fill_all(c)
    assert c.phase is Phase.CONFIRMATION


# -- confirm_profile ---------------------------------------------------------------------


def test_confirm_profile_refused_before_confirmation(c: InterviewController) -> None:
    result = c.confirm_profile()
    assert "summary_for_readback" not in result
    assert result["error"]
    assert result["next_goal"]
    assert c.phase is not Phase.CLOSING


def test_confirm_profile_reads_back_risky_slots_only(c: InterviewController) -> None:
    at_confirmation(c)
    summary = str(c.confirm_profile()["summary_for_readback"])
    assert "[language: es]" in summary
    for expected in ("crew_member", "Laura Gil", "+34600123456", "2026-11-03", "Acme Burgers Sol"):
        assert expected in summary
    assert "weekly" not in summary
    assert "end_interview with reason completed" in summary
    assert c.phase is Phase.CLOSING


def test_confirm_profile_uses_language_marker(c: InterviewController) -> None:
    c.language = "en"
    at_confirmation(c)
    assert "[language: en]" in str(c.confirm_profile()["summary_for_readback"])


def test_confirm_profile_reports_unresolved_risky_slot(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    for field, value in CREW:
        if field == "phone":
            for _ in range(3):
                c.record("phone", "12")
        else:
            c.record(field, value)
    assert c.phase is Phase.CONFIRMATION
    assert "phone: not provided" in str(c.confirm_profile()["summary_for_readback"])


def test_goal_after_confirmation_is_to_close(c: InterviewController) -> None:
    at_confirmation(c)
    c.confirm_profile()
    result = c.record("weekly_hours", "25")  # same value: no correction
    assert result.status == "ok"
    assert "end_interview" in result.next_goal
    assert c.phase is Phase.CLOSING


def test_correction_after_confirmation_returns_to_confirmation(
    c: InterviewController, emitted: list[Event]
) -> None:
    at_confirmation(c)
    c.confirm_profile()
    result = c.record("phone", "611 222 333")
    assert result.status == "ok"
    assert result.next_goal == CONFIRM_GOAL
    assert c.phase is Phase.CONFIRMATION
    assert "field_corrected" in [e.type for e in emitted]
    again = str(c.confirm_profile()["summary_for_readback"])
    assert "611222333" in again
    assert phase(c) is Phase.CLOSING


def test_role_change_after_confirmation_returns_to_collecting(c: InterviewController) -> None:
    at_confirmation(c)
    c.confirm_profile()
    result = c.record("role", "delivery_rider")
    assert c.phase is Phase.COLLECTING
    assert "licence" in result.next_goal


# -- escalate / end ----------------------------------------------------------------------


def test_escalate(c: InterviewController, emitted: list[Event]) -> None:
    c.record("consent_recording", "yes")
    result = c.escalate("candidate_request")
    assert result["ticket_id"] == "T-0"
    assert result["next_goal"] == ESCALATED_ASK_PHONE_GOAL
    assert ESCALATED_ASK_PHONE_GOAL in str(result["message_for_candidate"])
    assert c.escalated
    assert c.phase is Phase.CLOSING
    assert c.next_goal() == ESCALATED_ASK_PHONE_GOAL
    assert c.record("full_name", "Laura Gil").next_goal == ESCALATED_ASK_PHONE_GOAL
    event = next(e for e in emitted if e.type == "escalated")
    assert event.payload == {"reason": "candidate_request", "ticket_id": "T-0"}


def test_phone_recorded_after_escalation_leads_to_goodbye(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    c.escalate("frustration")
    assert not c.has_phone
    result = c.record("phone", "612 345 678", "612 345 678")
    assert result.status == "ok"
    assert result.next_goal == ESCALATED_GOAL
    assert c.has_phone
    assert c.phase is Phase.CLOSING


def test_invalid_phone_after_escalation_is_reasked_then_unresolved(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    c.escalate("frustration")
    first = c.record("phone", "12", "12")
    assert first.status == "invalid"
    assert first.next_goal == ESCALATED_ASK_PHONE_GOAL
    c.record("phone", "12", "12")
    last = c.record("phone", "12", "12")
    assert last.status == "unresolved"
    assert last.next_goal == ESCALATED_GOAL
    assert not c.has_phone


def test_escalate_before_consent_does_not_ask_for_a_phone(c: InterviewController) -> None:
    result = c.escalate("candidate_request")
    assert result["next_goal"] == ESCALATED_NO_CONSENT_GOAL
    assert "search_faq" in ESCALATED_NO_CONSENT_GOAL
    assert c.record("phone", "612 345 678").status == "not_applicable"
    assert c.profile.phone is None
    assert not c.has_phone


def test_end_sets_reason_time_and_event(c: InterviewController, emitted: list[Event]) -> None:
    c.end(EndReason.ABANDONED)
    assert c.phase is Phase.ENDED
    assert c.end_reason is EndReason.ABANDONED
    assert c.ended_at == NOW
    assert emitted[-1].type == "interview_ended"
    assert emitted[-1].payload == {"reason": "abandoned"}
    count = len(emitted)
    c.end(EndReason.COMPLETED)  # no-op
    assert len(emitted) == count
    assert c.end_reason is EndReason.ABANDONED
    assert "ended" in c.next_goal()


def test_abandon_after_escalation_ends_escalated(c: InterviewController) -> None:
    c.escalate("candidate_request")
    c.end(EndReason.ABANDONED)
    assert c.end_reason is EndReason.ESCALATED


def test_escalate_after_end_keeps_phase(c: InterviewController, emitted: list[Event]) -> None:
    c.end(EndReason.COMPLETED)
    count = len(emitted)
    result = c.escalate("late")
    assert result == {"ticket_id": None, "message_for_candidate": "The interview has ended."}
    assert c.phase is Phase.ENDED
    assert not c.escalated
    assert len(emitted) == count


def test_escalate_is_idempotent(c: InterviewController, emitted: list[Event]) -> None:
    first = c.escalate("asked for a person")
    count = len(emitted)
    second = c.escalate("again")
    assert second == first
    assert len(emitted) == count
    assert [e.type for e in emitted].count("escalated") == 1


def test_record_after_end_changes_nothing(c: InterviewController, emitted: list[Event]) -> None:
    c.record("consent_recording", "yes")
    c.end(EndReason.ABANDONED)
    count, profile = len(emitted), c.profile.model_copy(deep=True)
    result = c.record("full_name", "Laura Gil")
    assert result.status == "not_applicable"
    assert result.hint == "The interview has ended."
    assert c.profile == profile
    assert len(emitted) == count
    assert SlotName.FULL_NAME not in c.slot_meta


def test_confirm_profile_after_end(c: InterviewController) -> None:
    at_confirmation(c)
    c.end(EndReason.ABANDONED)
    result = c.confirm_profile()
    assert result["error"] == "The interview has ended."
    assert "summary_for_readback" not in result


def test_second_confirm_profile_repeats_the_readback(c: InterviewController) -> None:
    at_confirmation(c)
    first = c.confirm_profile()
    assert c.confirm_profile() == first
    assert c.phase is Phase.CLOSING


# -- consent gating (ADR-009.4) ----------------------------------------------------------


def test_data_before_consent_is_not_stored(c: InterviewController, emitted: list[Event]) -> None:
    result = c.record("full_name", "Laura Gil", "me llamo Laura")
    assert result.status == "not_applicable"
    assert result.hint == "Consent has not been given yet; do not collect data."
    assert result.next_goal == SLOT_BY_NAME[SlotName.CONSENT_RECORDING].ask
    assert c.profile.full_name is None
    assert c.slot_meta == {}
    assert emitted == []
    c.record("consent_recording", "no", "no")
    assert c.profile.full_name is None
    assert SlotName.FULL_NAME not in c.build_record("x", NOW, MODEL, channel="text").slot_meta


def test_data_after_decline_is_not_stored(c: InterviewController, emitted: list[Event]) -> None:
    c.record("consent_recording", "no", "no gracias")
    c.record("consent_recording", "no", "no gracias")
    count = len(emitted)
    result = c.record("phone", "600 123 456", "mi telefono")
    assert result.status == "not_applicable"
    assert result.hint == "Consent was declined; do not collect data."
    assert result.next_goal == CLOSE_DECLINED
    assert c.profile.phone is None
    assert SlotName.PHONE not in c.slot_meta
    assert len(emitted) == count


def test_consent_withdrawn_clears_everything_else(c: InterviewController) -> None:
    c.record("consent_recording", "yes", "si")
    for field, value in CREW[:4]:
        c.record(field, value, f"said {field}")
    c.record("weekly_hours", "99")  # a validation_failed event for another field
    c.record("consent_recording", "no", "mejor no")
    assert c.profile == CandidateProfile(consent_recording=False)
    assert set(c.slot_meta) == {SlotName.CONSENT_RECORDING}
    kept = [
        e for e in c.events if e.type in ("slot_filled", "field_corrected", "validation_failed")
    ]
    assert all(e.payload["field"] == "consent_recording" for e in kept)
    record = c.build_record("x", NOW, MODEL, channel="text")
    assert record.candidate == CandidateProfile(consent_recording=False)
    assert set(record.slot_meta) == {SlotName.CONSENT_RECORDING}
    assert record.slot_meta[SlotName.CONSENT_RECORDING].raw is None
    assert "Laura" not in record.model_dump_json()


def test_consent_no_then_yes_resumes_collecting(c: InterviewController) -> None:
    c.record("consent_recording", "no")
    c.record("consent_recording", "no")
    assert c.phase is Phase.CLOSING
    c.record("consent_recording", "yes")
    assert phase(c) is Phase.COLLECTING
    assert c.record("full_name", "Laura Gil").status == "ok"
    for field, value in CREW:
        c.record(field, value)
    assert phase(c) is Phase.CONFIRMATION
    assert "summary_for_readback" in c.confirm_profile()


def test_next_goal_is_pure(c: InterviewController, emitted: list[Event]) -> None:
    c.start()
    for step in (
        lambda: c.record("consent_recording", "yes"),
        lambda: [c.record(f, v) for f, v in CREW],
        lambda: c.confirm_profile(),
        lambda: c.escalate("x"),
    ):
        step()
        phase_before, events_before = c.phase, list(emitted)
        goals = {c.next_goal() for _ in range(5)}
        assert len(goals) == 1
        assert c.phase is phase_before
        assert c.events == events_before


def test_start_moves_to_consent_once(c: InterviewController) -> None:
    assert c.start() == SLOT_BY_NAME[SlotName.CONSENT_RECORDING].ask
    assert c.phase is Phase.CONSENT
    c.start()
    assert [e.payload["to"] for e in c.events if e.type == "phase_changed"] == ["consent"]


# -- sentiment and human requests --------------------------------------------------------


def test_one_frustrated_turn_gives_no_note(c: InterviewController) -> None:
    assert c.on_sentiment(-0.8, True) is None


def test_two_of_last_four_gives_note_once_per_streak(c: InterviewController) -> None:
    assert c.on_sentiment(-0.5, True) is None
    assert c.on_sentiment(0.1, False) is None
    assert c.on_sentiment(-0.6, True) == FRUSTRATION_NOTE
    assert c.on_sentiment(-0.7, True) is None  # same streak
    assert c.on_sentiment(-0.7, True) is None
    assert c.on_sentiment(0.5, False) is None  # resets
    assert c.on_sentiment(-0.7, True) == FRUSTRATION_NOTE


def test_flags_older_than_four_turns_do_not_count(c: InterviewController) -> None:
    c.on_sentiment(-0.5, True)
    for _ in range(4):
        c.on_sentiment(0.5, False)
    assert c.on_sentiment(-0.5, True) is None


def test_note_text(c: InterviewController) -> None:
    assert FRUSTRATION_NOTE == (
        "[SYSTEM NOTE] The candidate seems frustrated. Offer a recruiter callback or to "
        "continue later."
    )


def test_no_frustration_note_after_escalation(c: InterviewController) -> None:
    c.on_sentiment(-0.5, True)
    c.escalate("x")
    assert c.on_sentiment(-0.5, True) is None
    assert c.on_sentiment(-0.5, True) is None


@pytest.mark.parametrize(
    "text",
    [
        "Quiero hablar con una persona, por favor",
        "quiero hablar con alguien",
        "Prefiero hablar con un humano",
        "¿Puedo hablar con una PERSONA?",
        "Can I talk to a human?",
        "I want a real person",
        "Let me speak to someone",
        "put me through to a recruiter",
        "quiero hablar con una persona",
        "pásame con un reclutador",
        "quiero hablar con un recruiter",
        "let me speak with a person",
        "can I talk to a real human",
        "talk to a recruiter please",
        "hablar con alguien",
    ],
)
def test_explicit_human_request(c: InterviewController, text: str) -> None:
    assert c.on_candidate_text(text) == HUMAN_REQUEST_NOTE


@pytest.mark.parametrize(
    "text",
    [
        "Me llamo Laura",
        "I can start on Monday",
        "",
        "I want to work as a recruiter",
        "quiero ser reclutador",
        "mi madre es una persona mayor",
        "I'm a people person",
        "I speak with customers every day",
        "hablo con clientes todo el día",
    ],
)
def test_ordinary_text_is_not_a_human_request(c: InterviewController, text: str) -> None:
    assert c.on_candidate_text(text) is None


def test_human_request_ignored_once_escalated(c: InterviewController) -> None:
    c.escalate("x")
    assert c.on_candidate_text("talk to a human") is None


# -- prefill -----------------------------------------------------------------------------


def test_prefill_sets_only_empty_slots(c: InterviewController, emitted: list[Event]) -> None:
    c.record("consent_recording", "yes")
    c.prefill({SlotName.FULL_NAME: "Ana Ruiz"})
    applied = c.prefill(
        {
            SlotName.FULL_NAME: "Other Name",
            SlotName.PHONE: "600 123 456",
            SlotName.CONSENT_RECORDING: True,
            SlotName.ROLE: Role.CREW_MEMBER,
            SlotName.WEEKLY_HOURS: 30,
            SlotName.START_DATE: date(2026, 11, 3),
            SlotName.AVAILABILITY: [Availability(day=Day.MON, shift=Shift.MORNING)],
            SlotName.LANGUAGES: ["es", "en"],
            SlotName.RIGHT_TO_WORK: True,
            SlotName.DRIVING_LICENCE: True,  # inactive for a crew member
            SlotName.EMAIL: "not an email",  # invalid: skipped
            SlotName.OWN_VEHICLE: None,
        }
    )
    assert c.profile.full_name == "Ana Ruiz"
    assert c.profile.consent_recording is True
    assert c.profile.phone == "+34600123456"
    assert c.profile.weekly_hours == 30
    assert c.profile.start_date == date(2026, 11, 3)
    assert c.profile.languages == ["es", "en"]
    assert c.profile.right_to_work is True
    assert c.profile.driving_licence is None
    assert c.profile.email is None
    assert SlotName.FULL_NAME not in applied and SlotName.PHONE in applied
    assert c.slot_meta[SlotName.PHONE].source == "prefill"
    filled = [e for e in emitted if e.type == "slot_filled" and e.payload["field"] == "phone"]
    assert filled[0].payload["source"] == "prefill"
    # prefilled slots are not asked again
    assert "phone" not in c.missing()


def test_prefill_role_activates_rider_slots_in_order(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    c.prefill({SlotName.DRIVING_LICENCE: "yes", SlotName.ROLE: "delivery_rider"})
    assert c.profile.driving_licence is True


def test_prefill_store_sets_country(make_ctx: MakeCtx, emitted: list[Event]) -> None:
    c = InterviewController(make_ctx(), lambda: NOW, lambda: "x", emitted.append)
    c.record("consent_recording", "yes")
    c.prefill({SlotName.PREFERRED_STORE_ID: "Polanco"})
    assert c.ctx.country == "MX"


def _only_consent(c: InterviewController) -> None:
    slots = c.snapshot()["slots"]
    assert isinstance(slots, dict)
    for name, info in slots.items():
        if name != "consent_recording":
            assert isinstance(info, dict) and "value" not in info
    assert set(c.slot_meta) <= {SlotName.CONSENT_RECORDING}
    assert not [e for e in c.events if e.payload.get("field") not in (None, "consent_recording")]


def test_prefill_before_consent_is_ignored(c: InterviewController) -> None:
    assert c.prefill({SlotName.FULL_NAME: "Ana Ruiz", SlotName.PHONE: "600 123 456"}) == []
    assert c.profile.full_name is None
    _only_consent(c)


def test_prefill_then_decline_leaves_only_consent(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    assert c.prefill({SlotName.FULL_NAME: "Ana Ruiz"}) == [SlotName.FULL_NAME]
    c.record("consent_recording", "no")
    _only_consent(c)
    assert c.profile.consent_recording is False
    assert c.prefill({SlotName.FULL_NAME: "Ana Ruiz"}) == []


def test_unresolved_consent_purges_data(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    c.prefill({SlotName.FULL_NAME: "Ana Ruiz"})
    c.profile.consent_recording = None
    c.slot_meta.pop(SlotName.CONSENT_RECORDING)
    for _ in range(3):
        c.record("consent_recording", "maybe")
    _only_consent(c)


# -- escalation reasons ------------------------------------------------------------------


def test_escalate_free_text_is_stored_as_other(
    c: InterviewController, emitted: list[Event]
) -> None:
    c.record("consent_recording", "yes")
    c.escalate("candidate said Juan Perez 600123456")
    event = next(e for e in emitted if e.type == "escalated")
    assert event.payload["reason"] == "other"
    record = c.build_record("c1", NOW, MODEL, channel="text")
    dumped = record.model_dump_json()
    assert "Juan" not in dumped and "600123456" not in dumped
    assert [e.payload["reason"] for e in record.events if e.type == "escalated"] == ["other"]


# -- snapshot ----------------------------------------------------------------------------


def test_snapshot_is_json_serialisable_and_complete(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    c.record("role", "crew_member")
    c.record("full_name", "Laura Gil")
    for _ in range(3):
        c.record("phone", "12")
    snap = c.snapshot()
    json.dumps(snap)
    assert snap["phase"] == "collecting"
    slots = snap["slots"]
    assert isinstance(slots, dict)
    assert slots["full_name"] == {"status": "filled", "value": "Laura Gil"}
    assert slots["phone"] == {"status": "unresolved"}
    assert slots["weekly_hours"] == {"status": "empty"}
    assert slots["driving_licence"] == {"status": "not_applicable"}
    assert set(slots) == {s.value for s in SlotName}
    assert snap["progress"] == c.progress()


def test_snapshot_values_are_json_types(c: InterviewController) -> None:
    fill_all(c)
    slots = c.snapshot()["slots"]
    assert isinstance(slots, dict)
    assert slots["start_date"] == {"status": "filled", "value": "2026-11-03"}
    assert slots["availability"] == {
        "status": "filled",
        "value": [{"day": "mon", "shift": "morning"}, {"day": "sat", "shift": "night"}],
    }


# -- build_record ------------------------------------------------------------------------


def test_build_record_completed_meets_requirements(c: InterviewController) -> None:
    at_confirmation(c)
    c.confirm_profile()
    c.end(EndReason.COMPLETED)
    record = c.build_record("conv-1", NOW, MODEL, channel="text")
    assert record.screening.status is ScreeningStatus.MEETS_REQUIREMENTS
    assert record.end_reason is EndReason.COMPLETED
    assert record.ended_at == NOW
    assert record.language.detected == "es"
    assert record.candidate.full_name == "Laura Gil"
    assert record.slot_meta[SlotName.PHONE].status == "filled"
    assert [e.type for e in record.events] == [e.type for e in c.events]
    assert record.conversation_id == "conv-1" and record.model == MODEL


def test_build_record_in_progress_needs_review(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    record = c.build_record("conv-1", NOW, MODEL, channel="text")
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    assert "REVIEW_INCOMPLETE_CALL" in record.screening.review_reasons


def test_build_record_escalated_and_unresolved(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    for _ in range(3):
        c.record("phone", "12")
    c.escalate("x")
    c.end(EndReason.ESCALATED)
    record = c.build_record("conv-1", NOW, MODEL, channel="text")
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    assert "REVIEW_ESCALATED" in record.screening.review_reasons
    assert "REVIEW_UNRESOLVED_SLOTS" in record.screening.review_reasons


def test_build_record_declined_consent_keeps_no_candidate_words(c: InterviewController) -> None:
    c.record("consent_recording", "no", said="prefiero que no")
    c.record("consent_recording", "no", said="prefiero que no")
    c.end(EndReason.DECLINED_CONSENT)
    meta = c.build_record("conv-1", NOW, MODEL, channel="text").slot_meta[
        SlotName.CONSENT_RECORDING
    ]
    assert meta.raw is None
    assert meta.cross_check is None and meta.cross_check_agrees is None
    assert meta.attempts == 2 and meta.status == "filled"


def test_build_record_knockout(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    c.record("right_to_work", "no")
    record = c.build_record("conv-1", NOW, MODEL, channel="text")
    assert record.screening.status is ScreeningStatus.MISSING_REQUIREMENTS


def test_build_record_is_a_snapshot_copy(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    record = c.build_record("conv-1", NOW, MODEL, channel="text")
    c.record("full_name", "Laura Gil")
    assert record.candidate.full_name is None
    assert SlotName.FULL_NAME not in record.slot_meta


def test_controller_text_names_only_real_tools() -> None:
    import re

    from acme_agent.interview import controller as mod

    real = {"record_field", "search_faq", "confirm_profile", "escalate_to_human", "end_interview"}
    texts = [v for k, v in vars(mod).items() if k.endswith(("_NOTE", "_GOAL", "_HINT"))]
    texts.append(inspect.getsource(mod.InterviewController))
    named = {m for t in texts if isinstance(t, str) for m in re.findall(r"call ([a-z_]+)", t)}
    assert named and named <= real, named - real


# -- read-back guarantee -----------------------------------------------------------------


def confirmed(c: InterviewController) -> InterviewController:
    at_confirmation(c)
    c.confirm_profile()
    return c


def test_confirm_profile_returns_say_and_sets_pending(c: InterviewController) -> None:
    at_confirmation(c)
    assert not c.readback_pending
    say = str(c.confirm_profile()["say"])
    assert say == (
        "Please confirm: role crew_member; name Laura Gil; phone +34 600 12 34 56; "
        "store Acme Burgers Sol (Madrid); start date 2026-11-03."
    )
    assert c.readback_pending


@pytest.mark.parametrize(
    "text",
    [
        "Laura Gil, tu puesto es crew, teléfono 600 12 34 56, tienda de Sol, "
        "empiezas el 3 de noviembre.",
        "Rol: mostrador; LAURA GIL; tel 6-00.12.34.56; Acme Burgers Sol; 3/11.",
        "Role crew, Laura Gil, phone ending 3456, Sol store, start November 3rd.",
        "crew, Laura Gil, 3456, SOL, 2026-11-03",
    ],
)
def test_readback_complete_true(c: InterviewController, text: str) -> None:
    confirmed(c)
    assert c.readback_complete(text)
    assert not c.readback_pending


@pytest.mark.parametrize(
    "text",
    [
        "crew, Laura, 3456, Sol, el 3 de noviembre",  # partial name
        "crew, Pedro Gil, 3456, Sol, el 3 de noviembre",  # wrong name
        "Para confirmar, tus datos son:",
        "I have the following details for you:",
        "Laura Gil, crew, 3456, Sol, empiezas en noviembre",  # no day
        "Laura Gil, crew, 3456, Sol, el 3 de diciembre",  # wrong month
        "Laura Gil, crew, 9999, Sol, el 3 de noviembre",  # wrong phone
        "Laura Gil, crew, 3456, Gràcia, el 3 de noviembre",  # wrong store
        "Laura Gil, 3456, Sol, el 3 de noviembre",  # no role
    ],
)
def test_readback_complete_false(c: InterviewController, text: str) -> None:
    confirmed(c)
    assert not c.readback_complete(text)
    assert c.readback_pending


def test_readback_store_accent_and_case_insensitive(make_ctx: MakeCtx) -> None:
    c = InterviewController(make_ctx(), lambda: NOW, lambda: "T", lambda e: None)
    c.record("consent_recording", "yes")
    for field, value in CREW:
        c.record(field, "Gràcia" if field == "preferred_store_id" else value)
    c.confirm_profile()
    assert c.readback_complete("Crew, láura GIL, 3456, GRACIA, 3 de noviembre")


def test_readback_skips_unresolved_slot(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    for field, value in CREW:
        if field == "phone":
            for _ in range(3):
                c.record("phone", "12")
        else:
            c.record(field, value)
    confirmed_say = c.confirm_profile()["say"]
    assert "phone not provided" in str(confirmed_say)
    assert c.readback_complete("crew, Laura Gil, Sol, el 3 de noviembre")


def test_readback_pending_cleared_on_correction_reopening(c: InterviewController) -> None:
    confirmed(c)
    assert c.readback_pending
    c.record("role", "delivery_rider")  # adds rider-only slots, reopens collecting
    assert phase(c) is Phase.COLLECTING
    assert not c.readback_pending


def test_readback_pending_cleared_on_escalate_and_end(
    make_ctx: MakeCtx, emitted: list[Event]
) -> None:
    for action in ("escalate", "end"):
        c = InterviewController(make_ctx(), lambda: NOW, lambda: "T", emitted.append)
        confirmed(c)
        assert c.readback_pending
        if action == "escalate":
            c.escalate("other")
        else:
            c.end(EndReason.COMPLETED)
        assert not c.readback_pending


def test_readback_role_matches_whole_words_only(c: InterviewController) -> None:
    confirmed(c)
    assert not c.readback_complete("Laura Gil, salario, 3456, Sol, el 3 de noviembre")
    assert c.readback_pending
    assert c.readback_complete("Laura Gil, sala, 3456, Sol, el 3 de noviembre")


def test_readback_table_covers_every_risky_slot() -> None:
    from acme_agent.interview.readback import READBACK
    from acme_agent.interview.slots import SLOTS

    assert {s.name for s in SLOTS if s.risky} <= set(READBACK)


def test_build_record_is_side_effect_free(c: InterviewController) -> None:
    c.record("consent_recording", "yes", "si")
    c.on_candidate_text("hola me llamo Laura")
    recent = list(c._recent_candidate)
    phase, events = c.phase, len(c.events)
    first = c.build_record("x", NOW, MODEL, channel="text")
    second = c.build_record("x", NOW, MODEL, channel="text")
    assert first == second
    assert list(c._recent_candidate) == recent
    assert (c.phase, len(c.events)) == (phase, events)


def test_withdrawal_clears_recent_candidate_text(c: InterviewController) -> None:
    c.record("consent_recording", "yes", "si")
    c.on_candidate_text("me llamo Laura")
    c.record("consent_recording", "no", "mejor no")
    assert not c._recent_candidate


# -- consent-decline confirmation (SPEC-018) ---------------------------------------------


def test_first_no_asks_for_confirmation(c: InterviewController) -> None:
    c.start()
    result = c.record("consent_recording", "no", "no")
    assert result.status == "confirm_decline"
    assert result.next_goal == CONFIRM_DECLINE_GOAL
    assert set(result.to_json()) >= {"status", "next_goal", "missing"}
    assert c.profile.consent_recording is None
    assert c.phase is Phase.CONSENT
    assert c.end_reason is None
    assert c.next_goal() == CONFIRM_DECLINE_GOAL  # pure, repeatable
    assert c.record("full_name", "Laura Gil").status == "not_applicable"


def test_second_no_declines_and_purges(c: InterviewController) -> None:
    c.start()
    c.record("consent_recording", "no", "no")
    result = c.record("consent_recording", "no", "no, quiero terminar")
    assert result.status == "ok"
    assert c.profile.consent_recording is False
    assert c.phase is Phase.CLOSING
    assert result.next_goal == CLOSE_DECLINED
    _only_consent(c)


def test_no_then_yes_starts_collecting(c: InterviewController) -> None:
    c.start()
    c.record("consent_recording", "no", "no")
    result = c.record("consent_recording", "yes", "bueno, sí")
    assert result.status == "ok"
    assert c.profile.consent_recording is True
    assert c.phase is Phase.COLLECTING
    assert c.next_goal() != CONFIRM_DECLINE_GOAL
    assert c.record("full_name", "Laura Gil").status == "ok"


def test_drop_while_decline_pending_stores_nothing(c: InterviewController) -> None:
    c.start()
    c.on_candidate_text("no quiero")
    c.record("consent_recording", "no", "no quiero")
    c.end(EndReason.ABANDONED)
    record = c.build_record("x", NOW, MODEL, channel="text")
    assert record.transcript == []
    assert record.candidate.consent_recording is None
    assert record.candidate == CandidateProfile()
    assert "no quiero" not in record.model_dump_json()


def test_invalid_answer_while_decline_pending_keeps_asking(c: InterviewController) -> None:
    c.start()
    c.record("consent_recording", "no", "no")
    assert c.record("consent_recording", "quizás").status == "invalid"
    assert c.next_goal() == CONFIRM_DECLINE_GOAL
    assert c.record("consent_recording", "no", "no").status == "ok"
    assert c.profile.consent_recording is False


def test_suppressed_note_does_not_consume_the_streak(c: InterviewController) -> None:
    assert c.on_sentiment(-0.5, True) is None
    c._readback_pending = True
    assert c.on_sentiment(-0.6, True) is None  # read-back pending: not now, not consumed
    c._readback_pending = False
    assert c.on_sentiment(-0.7, True) == FRUSTRATION_NOTE
    assert c.on_sentiment(-0.7, True) is None  # now it is consumed


def test_closing_phase_does_not_consume_the_note(c: InterviewController) -> None:
    c.on_sentiment(-0.5, True)
    c.phase = Phase.CLOSING
    assert c.on_sentiment(-0.6, True) is None
    c.phase = Phase.COLLECTING
    assert c.on_sentiment(-0.7, True) == FRUSTRATION_NOTE


def test_escalated_end_without_escalation_is_abandoned(
    c: InterviewController, emitted: list[Event]
) -> None:
    c.record("consent_recording", "yes")
    c.end(EndReason.ESCALATED)
    assert c.end_reason is EndReason.ABANDONED
    assert emitted[-1].payload == {"reason": "abandoned", "requested_reason": "escalated"}
    record = c.build_record("conv-1", NOW, MODEL, channel="text")
    assert "REVIEW_ESCALATED" not in record.screening.review_reasons


def test_declined_recruiter_offer_and_frustration_are_flagged(c: InterviewController) -> None:
    c.record("consent_recording", "yes")
    note = None
    for _ in range(2):
        note = c.on_sentiment(-0.8, True) or note
    assert note is not None
    c.end(EndReason.ABANDONED)
    record = c.build_record("conv-1", NOW, MODEL, channel="text")
    assert "FLAG_FRUSTRATION" in record.screening.flags
    assert "FLAG_RECRUITER_DECLINED" in record.screening.flags


def test_confirm_decline_goal_ends_with_direct_question() -> None:
    assert "Sí o no" in CONFIRM_DECLINE_GOAL
