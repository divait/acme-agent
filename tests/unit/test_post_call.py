"""PostCallFinalizer with a fake genai client: offline, no sleeping."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types

from acme_agent.analysis.post_call import PostCallFinalizer, transcript_text
from acme_agent.analysis.schemas import ExtractionResult, SlotExtraction, Summary
from acme_agent.config import Settings
from acme_agent.domain.models import (
    EndReason,
    ModelInfo,
    ScreeningStatus,
    SlotName,
    Speaker,
    TranscriptTurn,
)
from acme_agent.domain.validators import ParseContext
from acme_agent.interview.controller import InterviewController
from acme_agent.llm import make_genai_client
from acme_agent.storage.json_repo import make_repository

MakeCtx = Callable[..., ParseContext]
NOW = datetime(2026, 10, 18, 20, 30, tzinfo=UTC)
INFO = ModelInfo(live="live", text="text", prompt_version="p1")

CANDIDATE_LINES = {
    2: "Me llamo Ana Lopez, mi correo es ana.lopez@example.com",
    4: "Puedo trabajar treinta horas a la semana",
}


class FakeModels:
    """Answers generate_content by response_schema; `fail` makes every call raise."""

    def __init__(
        self,
        extraction: ExtractionResult | None = None,
        summary: Summary | None = None,
        fail: type[BaseException] | None = None,
        hang: bool = False,
    ) -> None:
        self.extraction = extraction or ExtractionResult()
        self.summary = summary
        self.fail = fail
        self.hang = hang
        self.calls: list[dict[str, Any]] = []

    async def generate_content(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> SimpleNamespace:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.hang:
            await asyncio.sleep(10)
        if self.fail:
            raise self.fail("boom")
        if config.response_schema is ExtractionResult:
            return SimpleNamespace(text=self.extraction.model_dump_json())
        assert self.summary is not None
        return SimpleNamespace(text=self.summary.model_dump_json())


def fake_client(models: FakeModels) -> Any:
    return SimpleNamespace(aio=SimpleNamespace(models=models))


GOOD_SUMMARY = Summary(
    headline="Ana Lopez, crew member, 30 h/week",
    key_points=["Wants crew work", "Available 30 hours", "Has some experience"],
    candidate_questions=["Is there a uniform?", "invented question"],
    recruiter_next_steps=["Call Ana to confirm hours"],
)
EXTRACTION = ExtractionResult(
    slots=[
        SlotExtraction(slot=SlotName.FULL_NAME, value="Ana Lopez", said="Ana Lopez", turn=2),
        SlotExtraction(
            slot=SlotName.EMAIL,
            value="ana.lopez@example.com",
            said="ana.lopez@example.com",
            turn=2,
        ),
        SlotExtraction(slot=SlotName.WEEKLY_HOURS, value="30", said="treinta horas", turn=4),
        SlotExtraction(slot=SlotName.PHONE, value="12345", said="12345", turn=4),  # invalid
    ]
)


def make_session(
    ctx: ParseContext, *, consent: str = "yes"
) -> tuple[InterviewController, list[TranscriptTurn]]:
    ctl = InterviewController(ctx, lambda: NOW, lambda: "id", lambda event: None)
    ctl.start()
    ctl.record("consent_recording", consent, "si" if consent == "yes" else "no")
    if consent == "no":
        ctl.record("consent_recording", consent, "no")  # a first "no" asks for confirmation
    transcript = [
        TranscriptTurn(turn=1, speaker=Speaker.AGENT, text="Hola, soy Ana", ts=NOW),
        TranscriptTurn(turn=2, speaker=Speaker.CANDIDATE, text=CANDIDATE_LINES[2], ts=NOW),
        TranscriptTurn(turn=3, speaker=Speaker.AGENT, text="Cuantas horas?", ts=NOW),
        TranscriptTurn(turn=4, speaker=Speaker.CANDIDATE, text=CANDIDATE_LINES[4], ts=NOW),
    ]
    return ctl, transcript


def finalizer(settings: Settings, models: FakeModels, **kw: Any) -> PostCallFinalizer:
    kw.setdefault("retry_base_delay", 0.0)
    return PostCallFinalizer(fake_client(models), settings, make_repository(settings), **kw)


async def run(fin: PostCallFinalizer, ctl: InterviewController, transcript: list[TranscriptTurn]):  # type: ignore[no-untyped-def]
    return await fin.finalize(
        ctl,
        transcript,
        conversation_id="c_01M58KVS9NHX20A4N2BXXR5AAE",
        started_at=NOW,
        model_info=INFO,
        channel="text",
        metrics={"duration_s": 12.5, "tool_calls": 3},
    )


def test_transcript_text_has_turns_and_speakers() -> None:
    turns = [
        TranscriptTurn(turn=1, speaker=Speaker.AGENT, text="Hola", ts=NOW),
        TranscriptTurn(turn=2, speaker=Speaker.CANDIDATE, text="Buenas", ts=NOW),
    ]
    assert transcript_text(turns) == "[turn 1] Agent: Hola\n[turn 2] Candidate: Buenas"


async def test_happy_path_fills_conflict_summary_saved(
    settings: Settings, make_ctx: MakeCtx
) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.record("weekly_hours", "20", "veinte")  # live disagrees with post-call (30)
    ctl.record("full_name", "Ana Lopez", "Ana Lopez")  # agrees
    ctl.note_faq("Is there a uniform?", found=False)
    ctl.note_faq("pay?", found=True, source="pay")
    ctl.end(EndReason.COMPLETED)
    models = FakeModels(extraction=EXTRACTION, summary=GOOD_SUMMARY)
    record = await run(finalizer(settings, models), ctl, transcript)

    assert [c["config"].temperature for c in models.calls] == [0.0, 0.3]
    assert all(c["model"] == settings.text_model for c in models.calls)
    assert "[turn 2] Candidate:" in models.calls[0]["contents"]
    assert "Is there a uniform?" in models.calls[1]["contents"]
    assert "REVIEW_CONFLICT" in models.calls[1]["contents"]
    assert record.candidate.email == "ana.lopez@example.com"
    assert record.slot_meta[SlotName.EMAIL].source == "post_call"
    assert record.candidate.weekly_hours == 20  # live wins
    assert record.candidate.phone is None  # invalid post value dropped
    assert [(c.slot, c.live, c.post_call) for c in record.screening.reconciliation_conflicts] == [
        (SlotName.WEEKLY_HOURS, 20, 30)
    ]
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    assert record.summary is not None
    assert record.summary.headline == GOOD_SUMMARY.headline
    assert record.summary.candidate_questions == GOOD_SUMMARY.candidate_questions
    m = record.metrics
    assert m["duration_s"] == 12.5 and m["tool_calls"] == 3  # session metrics preserved
    assert (m["post_call_fills"], m["post_call_conflicts"], m["post_call"]) == (1, 1, "ok")
    assert (m["faq_hits"], m["faq_misses"]) == (1, 1)
    assert m["invalid_attempts"] == {}
    stored = await make_repository(settings).get(record.conversation_id)
    assert stored is not None and stored.summary == record.summary
    assert stored.candidate.email == "ana.lopez@example.com"


async def test_invalid_attempts_counted_per_slot(settings: Settings, make_ctx: MakeCtx) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.record("weekly_hours", "lots", "mucho")
    ctl.record("weekly_hours", "lots", "mucho")
    ctl.end(EndReason.COMPLETED)
    record = await run(finalizer(settings, FakeModels(summary=GOOD_SUMMARY)), ctl, transcript)
    assert record.metrics["invalid_attempts"] == {"weekly_hours": 2}


async def test_candidate_questions_dropped_when_none_were_missed(
    settings: Settings, make_ctx: MakeCtx
) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.end(EndReason.COMPLETED)
    record = await run(finalizer(settings, FakeModels(summary=GOOD_SUMMARY)), ctl, transcript)
    assert record.summary is not None and record.summary.candidate_questions == []


async def test_failing_client_saves_live_data_without_summary(
    settings: Settings, make_ctx: MakeCtx
) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.record("weekly_hours", "20", "veinte")
    ctl.end(EndReason.COMPLETED)
    models = FakeModels(fail=RuntimeError)
    record = await run(finalizer(settings, models), ctl, transcript)

    assert len(models.calls) == 3  # first try + 2 retries; the summary is not attempted
    assert record.summary is None
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    assert "REVIEW_POST_CALL_FAILED" in record.screening.review_reasons
    assert record.candidate.weekly_hours == 20
    failed = [e for e in record.events if e.type == "post_call_failed"]
    assert [e.payload for e in failed] == [{"step": "extraction"}]
    assert record.metrics["post_call"] == "failed"
    stored = await make_repository(settings).get(record.conversation_id)
    assert stored is not None and stored.summary is None


async def test_failed_post_call_with_knockout_needs_review(
    settings: Settings, make_ctx: MakeCtx
) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.record("right_to_work", "no", "no puedo")
    ctl.end(EndReason.COMPLETED)
    record = await run(finalizer(settings, FakeModels(fail=RuntimeError)), ctl, transcript)
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    assert "KO_NO_RIGHT_TO_WORK" in record.screening.knockouts
    assert "REVIEW_POST_CALL_FAILED" in record.screening.review_reasons


async def test_missing_metrics_are_derived(settings: Settings, make_ctx: MakeCtx) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.end(EndReason.COMPLETED)
    record = await finalizer(settings, FakeModels()).finalize(
        ctl,
        transcript,
        conversation_id="c_01M58KVS9NHX20A4N2BXXR5AAE",
        started_at=NOW,
        model_info=INFO,
        channel="text",
    )
    assert record.metrics["candidate_turns"] == 2
    assert record.metrics["agent_turns"] == 2
    assert record.metrics["duration_s"] == 0.0


async def test_summary_failure_keeps_reconciled_data(settings: Settings, make_ctx: MakeCtx) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.end(EndReason.COMPLETED)
    models = FakeModels(extraction=EXTRACTION, summary=None)  # summary call asserts -> raises
    record = await run(finalizer(settings, models), ctl, transcript)
    assert len(models.calls) == 1 + 3
    assert record.candidate.email == "ana.lopez@example.com"
    assert record.summary is None
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    assert [e.payload for e in record.events if e.type == "post_call_failed"] == [
        {"step": "summary"}
    ]


async def test_invalid_structured_output_counts_as_failure(
    settings: Settings, make_ctx: MakeCtx
) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.end(EndReason.COMPLETED)
    too_long = Summary.model_construct(
        headline="x" * 200, key_points=["a"], candidate_questions=[], recruiter_next_steps=[]
    )
    models = FakeModels(summary=too_long)
    record = await run(finalizer(settings, models), ctl, transcript)
    assert record.summary is None and len(models.calls) == 1 + 3


async def test_timeouts_are_retried_then_fail(settings: Settings, make_ctx: MakeCtx) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.end(EndReason.COMPLETED)
    models = FakeModels(hang=True)
    fin = finalizer(settings, models, call_timeout=0.01)
    record = await run(fin, ctl, transcript)
    assert len(models.calls) == 3
    assert record.summary is None
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW


async def test_retry_recovers_after_a_transient_failure(
    settings: Settings, make_ctx: MakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctl, transcript = make_session(make_ctx())
    ctl.end(EndReason.COMPLETED)
    models = FakeModels(extraction=EXTRACTION, summary=GOOD_SUMMARY)
    real = models.generate_content
    state = {"n": 0}

    async def flaky(**kw: Any) -> SimpleNamespace:
        state["n"] += 1
        if state["n"] == 1:
            raise TimeoutError
        return await real(**kw)

    models.generate_content = flaky  # type: ignore[method-assign]
    sleeps: list[float] = []

    async def spy_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("acme_agent.analysis.post_call.asyncio.sleep", spy_sleep)
    record = await run(finalizer(settings, models, retry_base_delay=2.0), ctl, transcript)
    assert record.summary is not None and record.metrics["post_call"] == "ok"
    assert sleeps == [2.0]


async def test_exponential_backoff_delays(
    settings: Settings, make_ctx: MakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []

    async def spy_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("acme_agent.analysis.post_call.asyncio.sleep", spy_sleep)
    ctl, transcript = make_session(make_ctx())
    ctl.end(EndReason.COMPLETED)
    await run(
        finalizer(settings, FakeModels(fail=RuntimeError), retry_base_delay=1.5), ctl, transcript
    )
    assert sleeps == [1.5, 3.0]


async def test_declined_consent_makes_no_model_calls(settings: Settings, make_ctx: MakeCtx) -> None:
    ctl, transcript = make_session(make_ctx(), consent="no")
    ctl.end(EndReason.DECLINED_CONSENT)
    models = FakeModels(extraction=EXTRACTION, summary=GOOD_SUMMARY)
    record = await run(finalizer(settings, models), ctl, transcript)
    assert models.calls == []
    assert record.summary is None and record.transcript == []
    assert record.end_reason is EndReason.DECLINED_CONSENT
    assert record.candidate.consent_recording is False
    assert record.metrics["post_call"] == "skipped"


async def test_no_consent_answer_makes_no_model_calls(
    settings: Settings, make_ctx: MakeCtx
) -> None:
    ctl = InterviewController(make_ctx(), lambda: NOW, lambda: "id", lambda event: None)
    ctl.start()
    ctl.end(EndReason.ABANDONED)
    models = FakeModels()
    record = await run(finalizer(settings, models), ctl, [])
    assert models.calls == [] and record.transcript == []


async def test_empty_transcript_skips_analysis(settings: Settings, make_ctx: MakeCtx) -> None:
    ctl, _ = make_session(make_ctx())
    ctl.end(EndReason.ABANDONED)
    models = FakeModels()
    record = await run(finalizer(settings, models), ctl, [])
    assert models.calls == [] and record.summary is None


def test_response_schemas_build_a_valid_generate_config() -> None:
    for schema in (ExtractionResult, Summary):
        config = types.GenerateContentConfig(response_schema=schema, temperature=0)
        assert config.response_schema is schema
    schema_json = Summary.model_json_schema()
    assert schema_json["properties"]["headline"]["maxLength"] == 140
    assert schema_json["properties"]["key_points"]["minItems"] == 3
    assert schema_json["properties"]["key_points"]["maxItems"] == 6


def test_default_container_selects_post_call_without_touching_credentials(
    tmp_path: Any,
) -> None:
    from acme_agent.bootstrap import build_container

    settings = Settings(google_cloud_project="p", data_dir=tmp_path / "c")
    assert isinstance(build_container(settings).finalizer, PostCallFinalizer)
    off = Settings(google_cloud_project="p", data_dir=tmp_path / "c", post_call="off")
    assert not isinstance(build_container(off).finalizer, PostCallFinalizer)


@pytest.mark.live
async def test_live_fixture(live_settings: Settings, make_ctx: MakeCtx) -> None:
    """Real Gemini over a Spanish transcript: one live miss to fill, one disagreement."""
    path = Path(__file__).parent.parent / "fixtures" / "post_call_transcript_es.json"
    transcript = [
        TranscriptTurn(ts=NOW, **row) for row in json.loads(path.read_text(encoding="utf-8"))
    ]
    ctl = InterviewController(make_ctx(), lambda: NOW, lambda: "id", lambda event: None)
    ctl.start()
    ctl.record("consent_recording", "yes", "Sí, de acuerdo")
    ctl.record("full_name", "Marta López García", "Me llamo Marta López García")
    ctl.record("phone", "612 345 678", "612 345 678")
    ctl.record("weekly_hours", "15", "quince")  # the candidate said 25: a disagreement
    # the email was stated but never recorded live: post-call must fill it
    ctl.end(EndReason.COMPLETED)
    repo = make_repository(live_settings)
    fin = PostCallFinalizer(make_genai_client(live_settings), live_settings, repo)
    record = await fin.finalize(
        ctl,
        transcript,
        conversation_id="c_01M58KVS9NHX20A4N2BXXR5AAE",
        started_at=NOW,
        model_info=INFO,
        channel="text",
        metrics={"duration_s": 90.0},
    )
    print("\nHEADLINE:", record.summary.headline if record.summary else None)
    print("KEY POINTS:", record.summary.key_points if record.summary else None)
    assert record.metrics["post_call"] == "ok"
    assert record.summary is not None
    assert 0 < len(record.summary.headline) <= 140
    assert 3 <= len(record.summary.key_points) <= 6
    assert record.candidate.email == "marta.lopez@example.com"
    assert record.slot_meta[SlotName.EMAIL].source == "post_call"
    assert [(c.slot, c.live, c.post_call) for c in record.screening.reconciliation_conflicts] == [
        (SlotName.WEEKLY_HOURS, 15, 25)
    ]
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    stored = await repo.get(record.conversation_id)
    assert stored is not None and stored.summary == record.summary
