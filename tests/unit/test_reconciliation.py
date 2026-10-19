"""Reconciliation (ADR-008.1/2) and `InterviewController.apply_reconciliation` (ADR-016.2)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from acme_agent.analysis.reconcile import reconcile
from acme_agent.analysis.schemas import ExtractionResult, SlotExtraction
from acme_agent.domain.models import CandidateProfile, EndReason, Role, SlotName, Store
from acme_agent.domain.validators import ParseContext
from acme_agent.interview.controller import Fill, InterviewController, ReconciliationResult

MakeCtx = Callable[..., ParseContext]
NOW = datetime(2026, 10, 18, 20, 30, tzinfo=UTC)

TURNS = {
    2: "me llamo Ana Lopez y mi correo es ana.lopez@example.com",
    4: "puedo trabajar treinta horas a la semana",
    6: "mi telefono es seis uno dos tres cuatro cinco seis siete ocho",
}


def item(slot: SlotName, value: str | None, said: str | None, turn: int | None) -> SlotExtraction:
    return SlotExtraction(slot=slot, value=value, said=said, turn=turn)


def run(live: CandidateProfile, ctx: ParseContext, *items: SlotExtraction):  # type: ignore[no-untyped-def]
    return reconcile(live, ExtractionResult(slots=list(items)), ctx, TURNS)


def test_agree_keeps_live(make_ctx: MakeCtx) -> None:
    live = CandidateProfile(weekly_hours=30)
    result = run(live, make_ctx(), item(SlotName.WEEKLY_HOURS, "30", "treinta horas", 4))
    assert result.fills == [] and result.conflicts == []


def test_live_empty_post_valid_fills(make_ctx: MakeCtx) -> None:
    result = run(
        CandidateProfile(),
        make_ctx(),
        item(SlotName.WEEKLY_HOURS, "30", "treinta horas", 4),
        item(SlotName.EMAIL, "ana.lopez@example.com", "ana.lopez@example.com", 2),
    )
    assert {f.slot: f.value for f in result.fills} == {
        SlotName.WEEKLY_HOURS: 30,
        SlotName.EMAIL: "ana.lopez@example.com",
    }
    assert result.conflicts == []


def test_disagree_keeps_live_and_reports_conflict(make_ctx: MakeCtx) -> None:
    live = CandidateProfile(weekly_hours=20)
    result = run(live, make_ctx(), item(SlotName.WEEKLY_HOURS, "30", "treinta horas", 4))
    assert result.fills == []
    assert [(c.slot, c.live, c.post_call) for c in result.conflicts] == [
        (SlotName.WEEKLY_HOURS, 20, 30)
    ]
    assert live.weekly_hours == 20  # pure: the input is untouched


def test_both_empty_stays_missing(make_ctx: MakeCtx) -> None:
    result = run(
        CandidateProfile(),
        make_ctx(),
        item(SlotName.WEEKLY_HOURS, None, None, None),
        item(SlotName.EMAIL, "  ", None, None),
    )
    assert result.fills == [] and result.conflicts == []


def test_invalid_phone_is_dropped_without_conflict(make_ctx: MakeCtx) -> None:
    turns = {**TURNS, 6: "mi telefono es 12345"}
    bad = item(SlotName.PHONE, "12345", "12345", 6)
    for live_phone in (None, "+34612345678"):
        live = CandidateProfile(phone=live_phone)
        result = reconcile(live, ExtractionResult(slots=[bad]), make_ctx(), turns)
        assert result.fills == [] and result.conflicts == []


def test_real_quote_with_invented_verbatim_value_is_dropped(make_ctx: MakeCtx) -> None:
    result = run(
        CandidateProfile(),
        make_ctx(),
        item(SlotName.EMAIL, "otra.persona@invented.org", "ana.lopez@example.com", 2),
        item(SlotName.PHONE, "+34699000111", "mi telefono es seis uno", 6),
    )
    assert result.fills == []


def test_store_is_reconciled_before_phone(make_ctx: MakeCtx, stores: list[Store]) -> None:
    turns = {
        2: "prefiero la tienda Roma Norte",
        4: "mi telefono es 55 1234 5678",
    }
    result = reconcile(
        CandidateProfile(),
        ExtractionResult(
            slots=[
                item(SlotName.PHONE, "55 1234 5678", "55 1234 5678", 4),
                item(SlotName.PREFERRED_STORE_ID, "Roma Norte", "tienda Roma Norte", 2),
            ]
        ),
        make_ctx(),
        turns,
    )
    fills = {f.slot: f.value for f in result.fills}
    assert fills[SlotName.PREFERRED_STORE_ID] == "cdmx-roma"
    assert fills[SlotName.PHONE] == "+525512345678"


def test_non_canonical_value_is_dropped(make_ctx: MakeCtx) -> None:
    result = run(
        CandidateProfile(), make_ctx(), item(SlotName.WEEKLY_HOURS, "treinta", "treinta horas", 4)
    )
    assert result.fills == []


def test_ungrounded_value_is_dropped(make_ctx: MakeCtx) -> None:
    live_empty = run(
        CandidateProfile(),
        make_ctx(),
        item(SlotName.WEEKLY_HOURS, "30", "quiero vacaciones pagadas", 4),
    )
    assert live_empty.fills == []
    live_value = run(
        CandidateProfile(weekly_hours=20),
        make_ctx(),
        item(SlotName.WEEKLY_HOURS, "30", "nunca dije esto", 4),
    )
    assert live_value.conflicts == []


def test_missing_said_is_ungrounded(make_ctx: MakeCtx) -> None:
    result = run(CandidateProfile(), make_ctx(), item(SlotName.WEEKLY_HOURS, "30", None, 4))
    assert result.fills == []


def test_wrong_turn_reference_still_grounded_in_any_turn(make_ctx: MakeCtx) -> None:
    result = run(
        CandidateProfile(), make_ctx(), item(SlotName.WEEKLY_HOURS, "30", "treinta horas", 99)
    )
    assert [f.slot for f in result.fills] == [SlotName.WEEKLY_HOURS]


def test_consent_is_never_reconciled(make_ctx: MakeCtx) -> None:
    result = run(
        CandidateProfile(consent_recording=True),
        make_ctx(),
        item(SlotName.CONSENT_RECORDING, "no", "puedo trabajar", 4),
    )
    assert result.fills == [] and result.conflicts == []


def test_rider_slots_follow_the_role(make_ctx: MakeCtx) -> None:
    licence = item(SlotName.DRIVING_LICENCE, "yes", "puedo trabajar", 4)
    crew = run(CandidateProfile(role=Role.CREW_MEMBER), make_ctx(), licence)
    assert crew.fills == []
    # a role filled post-call activates the rider-only slots in the same pass
    both = run(
        CandidateProfile(), make_ctx(), item(SlotName.ROLE, "delivery_rider", "Ana", 2), licence
    )
    assert [f.slot for f in both.fills] == [SlotName.ROLE, SlotName.DRIVING_LICENCE]


def test_list_values_compare_as_sets(make_ctx: MakeCtx) -> None:
    live = CandidateProfile(languages=["es", "en"])
    result = run(live, make_ctx(), item(SlotName.LANGUAGES, "en,es", "treinta horas", 4))
    assert result.fills == [] and result.conflicts == []


# -- InterviewController.apply_reconciliation -------------------------------------------------


def make_controller(ctx: ParseContext) -> InterviewController:
    ctl = InterviewController(ctx, lambda: NOW, lambda: "id", lambda event: None)
    ctl.start()
    ctl.record("consent_recording", "yes", "si")
    return ctl


def test_apply_fills_with_post_call_source_and_keeps_conflicts(make_ctx: MakeCtx) -> None:
    ctl = make_controller(make_ctx())
    ctl.record("weekly_hours", "20", "veinte")
    result = ReconciliationResult(
        fills=[Fill(SlotName.EMAIL, "ana@example.com", "ana@example.com")],
        conflicts=reconcile(
            ctl.profile,
            ExtractionResult(slots=[item(SlotName.WEEKLY_HOURS, "30", "treinta horas", 4)]),
            ctl.ctx,
            TURNS,
        ).conflicts,
    )
    assert ctl.apply_reconciliation(result) == [SlotName.EMAIL]
    assert ctl.profile.email == "ana@example.com"
    meta = ctl.slot_meta[SlotName.EMAIL]
    assert (meta.status, meta.source, meta.raw) == ("filled", "post_call", "ana@example.com")
    assert ctl.profile.weekly_hours == 20
    assert ctl.slot_meta[SlotName.WEEKLY_HOURS].source == "live_tool"
    assert [(c.slot, c.live, c.post_call) for c in ctl.reconciliation_conflicts] == [
        (SlotName.WEEKLY_HOURS, 20, 30)
    ]
    assert any(e.type == "slot_filled" and e.payload["source"] == "post_call" for e in ctl.events)


def test_apply_never_overwrites_a_filled_slot(make_ctx: MakeCtx) -> None:
    ctl = make_controller(make_ctx())
    ctl.record("weekly_hours", "20", "veinte")
    assert (
        ctl.apply_reconciliation(ReconciliationResult(fills=[Fill(SlotName.WEEKLY_HOURS, 30)]))
        == []
    )
    assert ctl.profile.weekly_hours == 20


def test_apply_ignores_inactive_slots_and_consent(make_ctx: MakeCtx) -> None:
    ctl = make_controller(make_ctx())
    ctl.record("role", "kitchen", "cocina")
    fills = [Fill(SlotName.DRIVING_LICENCE, True), Fill(SlotName.CONSENT_RECORDING, False)]
    assert ctl.apply_reconciliation(ReconciliationResult(fills=fills)) == []
    assert ctl.profile.driving_licence is None and ctl.profile.consent_recording is True


def test_apply_does_nothing_without_consent(make_ctx: MakeCtx) -> None:
    ctl = InterviewController(make_ctx(), lambda: NOW, lambda: "id", lambda event: None)
    ctl.start()
    ctl.record("consent_recording", "no", "no")
    fill = ReconciliationResult(fills=[Fill(SlotName.EMAIL, "a@b.co")])
    assert ctl.apply_reconciliation(fill) == []
    assert ctl.profile.email is None


def test_conflict_routes_to_human_review(make_ctx: MakeCtx) -> None:
    from acme_agent.domain.models import ModelInfo, ScreeningStatus

    ctl = make_controller(make_ctx())
    ctl.record("weekly_hours", "20", "veinte")
    conflict = reconcile(
        ctl.profile,
        ExtractionResult(slots=[item(SlotName.WEEKLY_HOURS, "30", "treinta horas", 4)]),
        ctl.ctx,
        TURNS,
    )
    ctl.apply_reconciliation(conflict)
    ctl.end(EndReason.COMPLETED)
    info = ModelInfo(live="l", text="t", prompt_version="p")
    record = ctl.build_record("c_1", NOW, info, channel="text")
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    assert "REVIEW_CONFLICT" in record.screening.review_reasons
    assert [c.slot for c in record.screening.reconciliation_conflicts] == [SlotName.WEEKLY_HOURS]


# -- false conflicts (SPEC-010) ---------------------------------------------------------

NAME_TURNS = {
    1: "me llamo Daniel Perez",
    2: "he trabajado en una cocina varios anos y en reparto",
    3: "mi nombre es Thiago",
    4: "mi correo es Ana.Lopez@Example.com",
}


def run_names(live: CandidateProfile, ctx: ParseContext, *items: SlotExtraction):  # type: ignore[no-untyped-def]
    return reconcile(live, ExtractionResult(slots=list(items)), ctx, NAME_TURNS)


def test_accent_difference_is_not_a_conflict(make_ctx: MakeCtx) -> None:
    live = CandidateProfile(full_name="Daniel Perez")
    result = run_names(
        live, make_ctx(), item(SlotName.FULL_NAME, "Daniel Pérez", "Daniel Perez", 1)
    )
    assert result.conflicts == []


def test_case_and_punctuation_are_ignored() -> None:
    from acme_agent.analysis.reconcile import _same

    assert _same("  DANIEL   perez. ", "daniel Pérez")
    assert _same("Ana.Lopez@Example.com", "ana.lopez@example.com")
    assert not _same("Diego", "Thiago")


def test_email_case_is_not_a_conflict(make_ctx: MakeCtx) -> None:
    live = CandidateProfile(email="ana.lopez@example.com")
    result = run_names(
        live,
        make_ctx(),
        item(SlotName.EMAIL, "Ana.Lopez@Example.com", "Ana.Lopez@Example.com", 4),
    )
    assert result.conflicts == []


def test_free_text_summary_never_conflicts(make_ctx: MakeCtx) -> None:
    live = CandidateProfile(experience_summary="Worked in a kitchen for years.")
    result = run_names(
        live,
        make_ctx(),
        item(SlotName.EXPERIENCE_SUMMARY, "Years of kitchen work", "una cocina varios anos", 2),
    )
    assert result.conflicts == [] and result.fills == []


def test_free_text_summary_fills_when_live_is_empty(make_ctx: MakeCtx) -> None:
    result = run_names(
        CandidateProfile(),
        make_ctx(),
        item(SlotName.EXPERIENCE_SUMMARY, "Years of kitchen work", "una cocina varios anos", 2),
    )
    assert [f.slot for f in result.fills] == [SlotName.EXPERIENCE_SUMMARY]


def test_real_difference_still_conflicts(make_ctx: MakeCtx) -> None:
    live = CandidateProfile(full_name="Diego")
    result = run_names(live, make_ctx(), item(SlotName.FULL_NAME, "Thiago", "Thiago", 3))
    assert [c.slot for c in result.conflicts] == [SlotName.FULL_NAME]


def _closed(ctl: InterviewController, *, confirm: bool) -> None:
    ctl.record("role", "crew_member", "crew")
    ctl.record("full_name", "Diego", "Diego")
    if confirm:
        ctl._confirmed = True
    ctl.end(EndReason.COMPLETED)


def _name_conflict(ctl: InterviewController) -> ReconciliationResult:
    return reconcile(
        ctl.profile,
        ExtractionResult(slots=[item(SlotName.FULL_NAME, "Thiago", "Thiago", 3)]),
        ctl.ctx,
        NAME_TURNS,
    )


def _reasons(ctl: InterviewController) -> list[str]:
    from acme_agent.domain.models import ModelInfo

    info = ModelInfo(live="l", text="t", prompt_version="p")
    return ctl.build_record("c_1", NOW, info, channel="text").screening.review_reasons


def test_conflict_on_confirmed_slot_is_informational(make_ctx: MakeCtx) -> None:
    ctl = make_controller(make_ctx())
    _closed(ctl, confirm=True)
    ctl.apply_reconciliation(_name_conflict(ctl))
    assert [c.confirmed_by_candidate for c in ctl.reconciliation_conflicts] == [True]
    assert "REVIEW_CONFLICT" not in _reasons(ctl)


def test_conflict_without_confirmation_still_routes_to_review(make_ctx: MakeCtx) -> None:
    ctl = make_controller(make_ctx())
    _closed(ctl, confirm=False)
    ctl.apply_reconciliation(_name_conflict(ctl))
    assert [c.confirmed_by_candidate for c in ctl.reconciliation_conflicts] == [False]
    assert "REVIEW_CONFLICT" in _reasons(ctl)


def test_old_conflict_records_load_as_unconfirmed() -> None:
    from acme_agent.domain.models import ReconciliationConflict

    c = ReconciliationConflict.model_validate({"slot": "full_name", "live": "a", "post_call": "b"})
    assert c.confirmed_by_candidate is False
