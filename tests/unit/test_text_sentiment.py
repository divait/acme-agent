"""TextInterview + sentiment: scored between turns, note injected before the next model turn."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from test_text_interview import FakeLlm, say, user_texts

from acme_agent.agent.text import TextInterview
from acme_agent.analysis.sentiment import SentimentResult
from acme_agent.bootstrap import build_container
from acme_agent.config import Settings
from acme_agent.interview.controller import FRUSTRATION_NOTE

NOW = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)


class Models:
    def __init__(self, frustrated: bool) -> None:
        self.frustrated = frustrated
        self.calls = 0

    async def generate_content(self, **kw: Any) -> Any:
        self.calls += 1
        result = SentimentResult(
            score=-0.7 if self.frustrated else 0.3, frustration=self.frustrated
        )
        return SimpleNamespace(text=result.model_dump_json())


def make(settings: Settings, frustrated: bool = True) -> tuple[TextInterview, FakeLlm, Models]:
    llm = FakeLlm([[say("ok")]] * 6)
    models = Models(frustrated)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    ti = TextInterview(
        build_container(settings, clock=lambda: NOW),
        language="es",
        clock=lambda: NOW,
        model=llm,
        sentiment_client=client,  # type: ignore[arg-type]
    )
    return ti, llm, models


async def test_note_is_injected_on_the_second_flag_and_scores_are_stored(
    settings: Settings,
) -> None:
    ti, llm, _models = make(settings)
    await ti.start()
    ti.controller.record("consent_recording", "yes", "sí")
    await ti.send("esto es una pérdida de tiempo")
    assert FRUSTRATION_NOTE not in "\n".join(user_texts(llm.requests[-1]))
    await ti.send("qué pesado, otra vez")
    assert FRUSTRATION_NOTE in user_texts(llm.requests[-1])[-1]
    await ti.send("sigues con lo mismo")
    assert FRUSTRATION_NOTE not in user_texts(llm.requests[-1])[-1]  # once per streak
    record = await ti.close()
    assert [t.sentiment for t in record.transcript if t.speaker.value == "candidate"] == [-0.7] * 3
    assert record.sentiment is not None and record.sentiment.frustration_events == 3


async def test_no_model_call_without_consent(settings: Settings) -> None:
    ti, _llm, models = make(settings)
    await ti.start()
    await ti.send("esto es una pérdida de tiempo")
    record = await ti.close()
    assert models.calls == 0
    assert record.sentiment is None
