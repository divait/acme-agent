"""InterviewSession + SentimentMonitor: scoring stays off the audio and tool paths."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from google.adk.events import Event as AdkEvent
from test_session import (
    CREW,
    FAST,
    FakeWebSocket,
    audio,
    call,
    container,  # noqa: F401  (fixture)
    done,
    heard,
    make_session,
    run_to_end,
    said,
    stored,
)
from ulid import ULID

from acme_agent.analysis.sentiment import SentimentResult
from acme_agent.bootstrap import AppContainer
from acme_agent.domain.models import EndReason
from acme_agent.interview.controller import FRUSTRATION_NOTE, Phase
from acme_agent.web.session import InterviewSession, RunnerSetup

ANGRY = ["esto es una pérdida de tiempo", "qué pesado, otra vez lo mismo"]


class FakeSentimentModels:
    def __init__(self, delay: float = 0.0, frustrated: bool = True) -> None:
        self.delay = delay
        self.frustrated = frustrated
        self.calls = 0

    async def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.calls += 1
        await asyncio.sleep(self.delay)
        result = SentimentResult(
            score=-0.8 if self.frustrated else 0.5, frustration=self.frustrated, reason="r"
        )
        return SimpleNamespace(text=result.model_dump_json())


def fake_client(models: FakeSentimentModels) -> Any:
    return SimpleNamespace(aio=SimpleNamespace(models=models))


def session_with(
    ws: FakeWebSocket, app: AppContainer, script: Any, models: FakeSentimentModels
) -> Any:
    session = make_session(ws, app, script)
    # Same wiring the session does for itself, with the fake client.
    from acme_agent.analysis.sentiment import SentimentMonitor

    session._sentiment = SentimentMonitor(
        lambda: fake_client(models), app.settings, session._on_sentiment
    )
    return session


def consent(setup: RunnerSetup) -> None:
    setup.tools["record_field"]("consent_recording", "yes", "sí acepto")


async def test_slow_scoring_never_delays_tools_or_audio(container: AppContainer) -> None:  # noqa: F811
    models = FakeSentimentModels(delay=2.0)
    ws = FakeWebSocket()
    elapsed: list[float] = []

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        consent(setup)
        yield heard(ANGRY[0])
        t0 = time.monotonic()
        for name, value in CREW[:3]:
            yield call("record_field")
            result = setup.tools["record_field"](name, value, value)
            assert result is not None
        yield audio(b"\x09")
        yield said("De acuerdo.")
        yield done()
        elapsed.append(time.monotonic() - t0)
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = session_with(ws, container, script, models)
    ws.push_text({"type": "start", "locale": "es-ES"})
    t_start = time.monotonic()
    await run_to_end(session)
    assert models.calls == 1  # the call was made...
    assert elapsed[0] < 0.5 and b"\x09" in ws.audio  # ...but nothing waited for it
    assert time.monotonic() - t_start < 1.5  # and the session closed without its 2 s result


async def test_second_flag_within_four_turns_emits_exactly_one_note(
    container: AppContainer,  # noqa: F811
) -> None:
    models = FakeSentimentModels()
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        consent(setup)
        yield heard(ANGRY[0])
        await asyncio.sleep(0.05)
        assert FRUSTRATION_NOTE not in setup_sent(session)  # one flag: no note yet
        yield heard(ANGRY[1])
        await asyncio.sleep(0.05)
        yield heard("otra vez, qué pesado")
        await asyncio.sleep(0.05)
        setup.controller.end(EndReason.COMPLETED)
        yield said("Adiós.")
        yield done()

    def setup_sent(s: Any) -> list[str]:
        return list(s.sent_content)

    session = session_with(ws, container, script, models)
    ws.push_text({"type": "start", "locale": "es-ES"})
    await run_to_end(session)
    assert session.sent_content.count(FRUSTRATION_NOTE) == 1
    record = await stored(container, session)
    cand = [t for t in record.transcript if t.speaker.value == "candidate"]
    assert [t.sentiment for t in cand] == [-0.8, -0.8, -0.8]
    assert record.sentiment is not None
    assert record.sentiment.frustration_events == 3 and record.sentiment.min == -0.8


async def test_no_scoring_before_or_without_consent(container: AppContainer) -> None:  # noqa: F811
    models = FakeSentimentModels()
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield heard(ANGRY[0])  # consent not given yet
        await asyncio.sleep(0.02)
        setup.tools["record_field"]("consent_recording", "no", "no")
        setup.tools["record_field"]("consent_recording", "no", "no")  # confirm the refusal
        yield heard(ANGRY[1])
        await asyncio.sleep(0.02)
        setup.controller.end(EndReason.DECLINED_CONSENT)
        yield said("Adiós.")
        yield done()

    session = session_with(ws, container, script, models)
    ws.push_text({"type": "start", "locale": "es-ES"})
    await run_to_end(session)
    assert models.calls == 0
    assert FRUSTRATION_NOTE not in session.sent_content
    record = await stored(container, session)
    assert record.sentiment is None and record.transcript == []


async def test_no_note_once_the_call_is_closing(container: AppContainer) -> None:  # noqa: F811
    models = FakeSentimentModels(delay=0.05)
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        consent(setup)
        yield heard(ANGRY[0])
        yield heard(ANGRY[1])
        setup.controller.escalate("candidate_request")  # call is wrapping up
        await asyncio.sleep(0.2)
        setup.controller.end(EndReason.ESCALATED)
        yield said("Un reclutador te llamará.")
        yield done()

    session = session_with(ws, container, script, models)
    ws.push_text({"type": "start", "locale": "es-ES"})
    await run_to_end(session)
    assert FRUSTRATION_NOTE not in session.sent_content


async def test_constructor_wires_the_monitor_from_sentiment_client(
    container: AppContainer,  # noqa: F811
) -> None:
    models = FakeSentimentModels()
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        consent(setup)
        yield heard(ANGRY[0])
        await asyncio.sleep(0.05)
        yield heard(ANGRY[1])
        await asyncio.sleep(0.05)
        setup.controller.end(EndReason.COMPLETED)
        yield said("Adiós.")
        yield done()

    session = InterviewSession(
        ws,  # type: ignore[arg-type]
        f"c_{ULID()}",
        container,
        runner_factory=script,
        timings=FAST,
        sentiment_client=fake_client(models),
    )
    ws.push_text({"type": "start", "locale": "es-ES"})
    await run_to_end(session)
    assert models.calls == 2
    assert session.sent_content.count(FRUSTRATION_NOTE) == 1


async def _no_note_without_escalate(
    app: AppContainer, *, closing_phase: bool, goodbye: bool
) -> Any:
    models = FakeSentimentModels()
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        consent(setup)
        if closing_phase:
            setup.controller.phase = Phase.CLOSING
        yield heard(ANGRY[0])
        yield heard(ANGRY[1])
        await asyncio.sleep(0.1)
        setup.controller.end(EndReason.COMPLETED)
        yield said("Adiós.")
        yield done()

    session = session_with(ws, app, script, models)
    if goodbye:
        session._goodbye_noted = True
    ws.push_text({"type": "start", "locale": "es-ES"})
    await run_to_end(session)
    return session


async def test_no_note_in_closing_phase_without_escalation(
    container: AppContainer,  # noqa: F811
) -> None:
    session = await _no_note_without_escalate(container, closing_phase=True, goodbye=False)
    assert FRUSTRATION_NOTE not in session.sent_content


async def test_no_note_after_goodbye_without_escalation(
    container: AppContainer,  # noqa: F811
) -> None:
    session = await _no_note_without_escalate(container, closing_phase=False, goodbye=True)
    assert FRUSTRATION_NOTE not in session.sent_content
