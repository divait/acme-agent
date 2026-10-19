"""SentimentMonitor with a fake genai client, plus the pure aggregate."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from acme_agent.analysis.sentiment import SentimentMonitor, SentimentResult
from acme_agent.config import Settings
from acme_agent.domain.models import ScreeningStatus, Speaker, TranscriptTurn
from acme_agent.domain.sentiment import aggregate
from acme_agent.interview.controller import FRUSTRATION_NOTE, InterviewController

NOW = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)


class FakeModels:
    def __init__(self, delay: float = 0.0, fail: type[Exception] | None = None) -> None:
        self.delay = delay
        self.fail = fail
        self.prompts: list[str] = []
        self.configs: list[Any] = []
        self.models: list[str] = []

    async def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.prompts.append(contents)
        self.configs.append(config)
        self.models.append(model)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail("secret candidate text")
        frustrated = "pesado" in contents.splitlines()[-1]
        result = SentimentResult(score=-0.8 if frustrated else 0.4, frustration=frustrated)
        return SimpleNamespace(text=result.model_dump_json())


def client(models: FakeModels) -> Any:
    return SimpleNamespace(aio=SimpleNamespace(models=models))


def turns(*texts: str) -> list[TranscriptTurn]:
    return [
        TranscriptTurn(
            turn=i + 1,
            speaker=Speaker.CANDIDATE if i % 2 == 0 else Speaker.AGENT,
            text=t,
            ts=NOW,
        )
        for i, t in enumerate(texts)
    ]


def scored(*scores: float | None) -> list[TranscriptTurn]:
    return [
        TranscriptTurn(turn=i + 1, speaker=Speaker.CANDIDATE, text="x", ts=NOW, sentiment=s)
        for i, s in enumerate(scores)
    ]


def monitor(
    settings: Settings, models: FakeModels, got: list[tuple[int, SentimentResult]], **kw: Any
) -> SentimentMonitor:
    return SentimentMonitor(lambda: client(models), settings, lambda i, r: got.append((i, r)), **kw)


# -- aggregate ---------------------------------------------------------------------------


def test_aggregate_without_scores_is_none() -> None:
    assert aggregate(scored(None, None)) is None
    assert aggregate([]) is None


@pytest.mark.parametrize(
    ("scores", "trend"),
    [
        ([-0.6, -0.2, 0.3], "improving"),
        ([0.5, 0.1, -0.4], "worsening"),
        ([0.2, 0.25, 0.3], "stable"),  # +0.1 < threshold
        ([0.0, 0.5], "stable"),  # fewer than 3 scores
        ([0.5, 0.4, 0.5, 0.4, 0.1, 0.0], "worsening"),  # thirds: 0.45 -> 0.05
        ([0.0, 0.0, 0.0, 0.0, 0.4, 0.4, 0.4], "improving"),
        ([0.0, 0.15, 0.3], "improving"),  # exactly at the threshold
    ],
)
def test_aggregate_trend(scores: list[float], trend: str) -> None:
    assert aggregate(scored(*scores)) is not None
    assert aggregate(scored(*scores)).trend == trend  # type: ignore[union-attr]


def test_aggregate_avg_min_and_events_ignore_unscored_and_agent_turns() -> None:
    ts = [*scored(0.5, None, -0.5, 0.0), *turns("agent line", "agent")[1:]]
    ts[-1].sentiment = -1.0  # an agent turn's score must never count
    result = aggregate(ts, frustration_events=2)
    assert result is not None
    assert (result.avg, result.min, result.frustration_events) == (0.0, -0.5, 2)


# -- monitor -----------------------------------------------------------------------------


async def test_result_is_delivered_with_the_last_three_turns(settings: Settings) -> None:
    models = FakeModels()
    got: list[tuple[int, SentimentResult]] = []
    mon = monitor(settings, models, got)
    mon.submit(4, turns("uno", "dos", "tres", "cuatro", "qué pesado"))
    await mon.wait_idle()
    assert got and got[0][0] == 4 and got[0][1].frustration is True
    lines = models.prompts[0].splitlines()
    assert len(lines) == 3 and lines[-1].endswith("qué pesado")
    assert models.models == [settings.sentiment_model]
    assert models.configs[0].temperature == 0.0
    assert models.configs[0].response_schema is SentimentResult
    await mon.close()


async def test_newer_submit_replaces_a_queued_one(settings: Settings) -> None:
    models = FakeModels(delay=0.05)
    got: list[tuple[int, SentimentResult]] = []
    mon = monitor(settings, models, got)
    mon.submit(1, turns("a"))
    await asyncio.sleep(0.01)  # call 1 is in flight
    mon.submit(3, turns("b"))
    mon.submit(5, turns("c"))  # replaces turn 3
    await mon.wait_idle()
    assert [i for i, _ in got] == [1, 5]
    assert len(models.prompts) == 2
    await mon.close()


async def test_never_more_than_one_call_in_flight(settings: Settings) -> None:
    class Counting(FakeModels):
        active = peak = 0

        async def generate_content(self, **kw: Any) -> Any:
            Counting.active += 1
            Counting.peak = max(Counting.peak, Counting.active)
            try:
                return await super().generate_content(**kw)
            finally:
                Counting.active -= 1

    models = Counting(delay=0.02)
    got: list[tuple[int, SentimentResult]] = []
    mon = monitor(settings, models, got)
    for i in range(1, 6):
        mon.submit(i, turns("x"))
        await asyncio.sleep(0.005)
    await mon.wait_idle()
    assert Counting.peak == 1
    await mon.close()


async def test_timeout_is_logged_and_ignored_then_next_submit_works(settings: Settings) -> None:
    models = FakeModels(delay=1.0)
    got: list[tuple[int, SentimentResult]] = []
    mon = monitor(settings, models, got, timeout=0.02)
    with capture_logs() as logs:
        mon.submit(1, turns("x"))
        await mon.wait_idle()
    assert got == []
    assert [entry["error"] for entry in logs if entry["event"] == "sentiment_failed"] == [
        "TimeoutError"
    ]
    models.delay = 0.0
    mon.submit(3, turns("y"))
    await mon.wait_idle()
    assert [i for i, _ in got] == [3]
    await mon.close()


async def test_failure_is_ignored_and_logs_no_candidate_text(settings: Settings) -> None:
    models = FakeModels(fail=RuntimeError)
    got: list[tuple[int, SentimentResult]] = []
    mon = monitor(settings, models, got)
    with capture_logs() as logs:
        mon.submit(1, turns("x"))
        await mon.wait_idle()
    assert got == []
    assert "secret candidate text" not in repr(logs)
    assert any(entry["error"] == "RuntimeError" for entry in logs)
    await mon.close()


async def test_garbage_structured_output_is_ignored(settings: Settings) -> None:
    class Garbage(FakeModels):
        async def generate_content(self, **kw: Any) -> Any:
            return SimpleNamespace(text="not json at all")

    got: list[tuple[int, SentimentResult]] = []
    mon = monitor(settings, Garbage(), got)
    mon.submit(1, turns("x"))
    await mon.wait_idle()
    assert got == []
    await mon.close()


async def test_close_cancels_in_flight_and_drops_queued(settings: Settings) -> None:
    models = FakeModels(delay=5)
    got: list[tuple[int, SentimentResult]] = []
    mon = monitor(settings, models, got)
    mon.submit(1, turns("x"))
    await asyncio.sleep(0.01)
    mon.submit(3, turns("y"))
    await asyncio.wait_for(mon.close(), 1)
    mon.submit(5, turns("z"))  # ignored once closed
    await asyncio.sleep(0.02)
    assert got == [] and len(models.prompts) == 1


# -- controller rule end to end ----------------------------------------------------------


def test_note_only_on_second_flag_within_four_turns(make_ctx: Any) -> None:
    c = InterviewController(make_ctx(), lambda: NOW, lambda: "T-1", lambda e: None)
    c.start()
    assert c.on_sentiment(-0.7, True) is None
    assert c.on_sentiment(0.2, False) is None
    assert c.on_sentiment(-0.8, True) == FRUSTRATION_NOTE
    assert c.on_sentiment(-0.9, True) is None  # once per streak


def test_escalation_accepted_ends_escalated_for_human_review(make_ctx: Any) -> None:
    c = InterviewController(make_ctx(), lambda: NOW, lambda: "T-1", lambda e: None)
    c.start()
    c.escalate("candidate_request")
    from acme_agent.domain.models import EndReason

    c.end(EndReason.ESCALATED)
    record = c.build_record("c_01M58KVS9NHX20A4N2BXXR5AAE", NOW, _info(), "text")
    assert record.end_reason is EndReason.ESCALATED
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW


def _info() -> Any:
    from acme_agent.domain.models import ModelInfo

    return ModelInfo(live="l", text="t", prompt_version="p")


# -- record redaction --------------------------------------------------------------------


def _scored_session(
    make_ctx: Any, consent: str
) -> tuple[InterviewController, list[TranscriptTurn]]:
    c = InterviewController(make_ctx(), lambda: NOW, lambda: "T-1", lambda e: None)
    c.start()
    c.record("consent_recording", consent, "si" if consent == "yes" else "no")
    if consent == "no":
        c.record("consent_recording", consent, "no")
    ts = scored(-0.8, -0.9)
    c.on_sentiment(-0.8, True)
    c.on_sentiment(-0.9, True)
    return c, ts


def test_record_carries_scores_and_aggregate_with_consent(make_ctx: Any) -> None:
    c, ts = _scored_session(make_ctx, "yes")
    record = c.build_record("c_01M58KVS9NHX20A4N2BXXR5AAE", NOW, _info(), "text", transcript=ts)
    assert [t.sentiment for t in record.transcript] == [-0.8, -0.9]
    assert record.sentiment is not None
    assert record.sentiment.frustration_events == 2 and record.sentiment.min == -0.9


def test_declined_consent_stores_no_sentiment(make_ctx: Any) -> None:
    c, ts = _scored_session(make_ctx, "no")
    record = c.build_record("c_01M58KVS9NHX20A4N2BXXR5AAE", NOW, _info(), "text", transcript=ts)
    assert record.sentiment is None
    assert record.transcript == []
