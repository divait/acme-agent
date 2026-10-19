"""Agent tools: names, docstrings, output shapes, and controller side effects."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from acme_agent.agent.tools import build_tools
from acme_agent.domain.models import EndReason, Event
from acme_agent.domain.validators import ParseContext
from acme_agent.interview.closing import CLOSING_LINES, closing_line
from acme_agent.interview.controller import InterviewController, Phase
from acme_agent.knowledge.retriever import FaqAnswer, FaqResult, NullRetriever

NOW = datetime(2026, 10, 18, 20, 30, tzinfo=UTC)


class FoundRetriever:
    async def search(self, question: str, language: str) -> FaqResult:
        return FaqResult(
            found=True, answers=[FaqAnswer(text="Yes.", source="faq_en#uniform", score=0.9)]
        )


class Setup:
    def __init__(self, ctx: ParseContext, retriever: object | None = None) -> None:
        self.emitted: list[Event] = []
        counter = iter(range(1000))
        self.controller = InterviewController(
            ctx, lambda: NOW, lambda: f"t-{next(counter)}", self.emitted.append
        )
        self.tools = {
            t.__name__: t
            for t in build_tools(self.controller, retriever or NullRetriever())  # type: ignore[arg-type]
        }


@pytest.fixture
def s(make_ctx: Callable[..., ParseContext]) -> Setup:
    setup = Setup(make_ctx())
    setup.controller.start()
    return setup


def test_exactly_five_named_tools(s: Setup) -> None:
    assert list(s.tools) == [
        "record_field",
        "search_faq",
        "confirm_profile",
        "escalate_to_human",
        "end_interview",
    ]


def test_tools_are_not_shared_between_controllers(make_ctx: Callable[..., ParseContext]) -> None:
    a, b = Setup(make_ctx()), Setup(make_ctx())
    a.controller.start()
    b.controller.start()
    assert a.tools["record_field"] is not b.tools["record_field"]
    before = (b.controller.snapshot(), len(b.controller.events), b.controller.phase)
    assert a.tools["record_field"]("consent_recording", "yes", "sure")["status"] == "ok"
    assert a.controller.phase is Phase.COLLECTING
    assert (b.controller.snapshot(), len(b.controller.events), b.controller.phase) == before


def test_docstrings_list_formats_and_reasons(s: Setup) -> None:
    doc = s.tools["record_field"].__doc__ or ""
    for text in (
        "YYYY-MM-DD",
        "day:shift",
        "mon:morning",
        "crew_member | kitchen | delivery_rider",
        '"yes" or "no"',
        "integer",
        "ISO codes",
        "unchanged",
        "full_name, phone, email, preferred_store_id",
        "consent_recording",
    ):
        assert text in doc
    esc_doc = " ".join((s.tools["escalate_to_human"].__doc__ or "").split())
    assert "candidate_request | frustration | technical_issue | other" in esc_doc
    end_doc = " ".join((s.tools["end_interview"].__doc__ or "").split())
    assert "completed | declined_consent | escalated | abandoned" in end_doc


def test_parameters_are_plain_str(s: Setup) -> None:
    for name, fn in s.tools.items():
        hints = {k: v for k, v in fn.__annotations__.items() if k != "return"}
        assert all(v in ("str", str) for v in hints.values()), name


def test_record_field_returns_tool_result_json(s: Setup) -> None:
    out = s.tools["record_field"]("consent_recording", "yes", "sure")
    json.dumps(out)
    assert out["status"] == "ok"
    assert set(out) == {"status", "field", "normalized", "hint", "next_goal", "missing", "progress"}
    assert s.controller.phase is Phase.COLLECTING


def test_record_field_unknown_field(s: Setup) -> None:
    assert s.tools["record_field"]("shoe_size", "9", "")["status"] == "unknown_field"


async def test_search_faq_null_retriever_logs_miss(s: Setup) -> None:
    out = await s.tools["search_faq"]("how much do riders earn", "en")
    assert out["found"] is False and out["answers"] == []
    miss = [e for e in s.emitted if e.type == "faq_missed"]
    assert len(miss) == 1 and miss[0].payload["question"] == "how much do riders earn"


async def test_search_faq_found_logs_source(make_ctx: Callable[..., ParseContext]) -> None:
    setup = Setup(make_ctx(), FoundRetriever())
    out = await setup.tools["search_faq"]("uniform?", "en")
    json.dumps(out)
    assert out["found"] is True and out["answers"][0]["source"] == "faq_en#uniform"
    ev = [e for e in setup.emitted if e.type == "faq_answered"]
    assert ev[0].payload["source"] == "faq_en#uniform"


def test_confirm_profile_not_ready_returns_error(s: Setup) -> None:
    out = s.tools["confirm_profile"]()
    json.dumps(out)
    assert "error" in out and "next_goal" in out


def test_escalate_closed_reason_and_free_text(s: Setup) -> None:
    out = s.tools["escalate_to_human"]("I hate this, give me a manager")
    json.dumps(out)
    assert out["ticket_id"] == "t-0"
    esc = [e for e in s.emitted if e.type == "escalated"]
    assert esc[0].payload["reason"] == "other"


def test_escalate_after_end_gives_null_ticket(s: Setup) -> None:
    s.tools["end_interview"]("abandoned")
    out = s.tools["escalate_to_human"]("frustration")
    assert out["ticket_id"] is None and "message_for_candidate" in out


def test_end_interview_ok(s: Setup) -> None:
    out = s.tools["end_interview"]("abandoned")
    assert (out["status"], out["reason"]) == ("ended", "abandoned")
    assert out["say"] == closing_line(EndReason.ABANDONED)
    assert s.controller.phase is Phase.ENDED


@pytest.mark.parametrize("reason", [r.value for r in EndReason])
def test_end_interview_says_a_closing_line_per_reason(reason: str, s: Setup) -> None:
    out = s.tools["end_interview"](reason)
    assert out["say"] and out["say"] == closing_line(EndReason(reason), False, False)


def test_closing_lines_content() -> None:
    assert "hiring team" in CLOSING_LINES[EndReason.COMPLETED]
    assert "nothing" in CLOSING_LINES[EndReason.DECLINED_CONSENT]
    assert "recruiter will call" in CLOSING_LINES[EndReason.ESCALATED]


def test_closing_line_never_promises_a_callback_without_a_phone() -> None:
    with_phone = closing_line(EndReason.ESCALATED, True, True)
    assert "recruiter will call them at the number they gave" in with_phone
    for has_phone, consented in [(False, True), (False, False), (True, False)]:
        line = closing_line(EndReason.ESCALATED, has_phone, consented)
        assert "will call" not in line and "hiring team" in line
    assert "nothing" in closing_line(EndReason.ESCALATED, False, False)
    for reason in (EndReason.ABANDONED, None):
        assert "contact you" not in closing_line(reason, True, True)
        assert "recruiter" not in closing_line(reason, True, True)
    assert closing_line(EndReason.COMPLETED, True, True) == CLOSING_LINES[EndReason.COMPLETED]


def test_end_interview_escalated_line_depends_on_phone(s: Setup) -> None:
    s.tools["record_field"]("consent_recording", "yes", "sí")
    s.tools["escalate_to_human"]("frustration")
    s.tools["record_field"]("phone", "612 345 678", "612 345 678")
    out = s.tools["end_interview"]("escalated")
    assert "will call them at the number they gave" in str(out["say"])


def test_end_interview_escalated_without_phone_has_no_callback(s: Setup) -> None:
    s.tools["record_field"]("consent_recording", "yes", "sí")
    s.tools["escalate_to_human"]("frustration")
    out = s.tools["end_interview"]("escalated")
    assert "will call" not in str(out["say"])


def test_end_interview_doc_asks_for_the_goodbye(s: Setup) -> None:
    doc = " ".join((s.tools["end_interview"].__doc__ or "").split())
    assert "Say the goodbye from `say`" in doc


async def test_search_faq_returns_pending_question_and_resume_instruction(
    make_ctx: Callable[..., ParseContext],
) -> None:
    setup = Setup(make_ctx(), FoundRetriever())
    setup.controller.start()
    setup.tools["record_field"]("consent_recording", "yes", "yes")
    before = (setup.controller.phase, len(setup.controller.events))
    out = await setup.tools["search_faq"]("uniform?", "en")
    goal = setup.controller.next_goal()
    assert out["next_goal"] == goal
    assert out["then"].endswith(goal)
    assert "one or two short sentences" in out["then"]
    assert (setup.controller.phase, len(setup.controller.events) - 1) == before  # only faq event


def test_end_interview_bad_reason_changes_nothing(s: Setup) -> None:
    before = (s.controller.phase, len(s.controller.events))
    out = s.tools["end_interview"]("because")
    assert out["allowed"] == ["completed", "declined_consent", "escalated", "abandoned"]
    assert "error" in out
    assert (s.controller.phase, len(s.controller.events)) == before
    assert s.controller.end_reason is None


def test_confirm_profile_ready_returns_summary_and_say(s: Setup) -> None:
    rf = s.tools["record_field"]
    rf("consent_recording", "yes", "yes")
    for field, value in (
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
    ):
        rf(field, value, value)
    out = s.tools["confirm_profile"]()
    json.dumps(out)
    assert set(out) == {"summary_for_readback", "say"}
    assert "say" in (s.tools["confirm_profile"].__doc__ or "")
