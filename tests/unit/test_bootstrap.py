"""Composition root: offline wiring, lazy client, finalizer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import acme_agent.bootstrap as bootstrap
from acme_agent.bootstrap import SaveOnlyFinalizer, build_container
from acme_agent.config import Settings
from acme_agent.domain.models import ModelInfo, Speaker, TranscriptTurn
from acme_agent.interview.controller import InterviewController
from acme_agent.knowledge.retriever import LazyRetriever, NullRetriever

NOW = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)  # already Monday 01:30 in Madrid


def test_container_wiring(settings: Settings) -> None:
    c = build_container(settings, clock=lambda: NOW)
    assert c.settings is settings
    assert isinstance(c.retriever, LazyRetriever)  # built lazily, offline until first search
    assert isinstance(c.finalizer, SaveOnlyFinalizer)
    assert c.repository is not None


def test_parse_context_factory(settings: Settings) -> None:
    c = build_container(settings, clock=lambda: NOW)
    ctx = c.parse_context_factory("en")
    assert ctx.today.isoformat() == "2026-10-19"
    assert ctx.country == "ES" and ctx.language == "en"
    assert len(ctx.stores) == 12
    assert c.parse_context_factory().language == "es"


def test_genai_client_is_lazy(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Settings] = []

    def fake(s: Settings) -> object:
        calls.append(s)
        return object()

    monkeypatch.setattr(bootstrap, "make_genai_client", fake)
    c = build_container(settings)
    assert calls == []
    first = c.genai_client
    assert c.genai_client is first and len(calls) == 1


async def test_save_only_finalizer_saves_with_transcript(settings: Settings) -> None:
    c = build_container(settings, clock=lambda: NOW)
    ctrl = InterviewController(
        c.parse_context_factory("es"), lambda: NOW, lambda: "x", lambda e: None
    )
    ctrl.start()
    ctrl.record("consent_recording", "yes", "sí claro")
    turn = TranscriptTurn(turn=1, speaker=Speaker.AGENT, text="Hola", ts=NOW)
    info = ModelInfo(live="l", text="t", prompt_version="ana-v1")
    cid = "01J9ZZZZZZZZZZZZZZZZZZZZZZ"
    record = await c.finalizer.finalize(
        ctrl, [turn], conversation_id=cid, started_at=NOW, model_info=info, channel="text"
    )
    assert record.transcript == [turn]
    stored = await c.repository.get(cid)
    assert stored is not None and stored.transcript[0].text == "Hola"
    assert stored.model.prompt_version == "ana-v1"


def test_container_does_not_read_unknown_knowledge_dir(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_container(settings, knowledge_dir=tmp_path)


async def test_finalizer_redacts_transcript_without_consent(settings: Settings) -> None:
    c = build_container(settings, clock=lambda: NOW)
    info = ModelInfo(live="l", text="t", prompt_version="ana-v1")
    turn = TranscriptTurn(
        turn=1, speaker=Speaker.CANDIDATE, text="No acepto. Me llamo Laura Gil", ts=NOW
    )
    metrics = {"candidate_turns": 1, "said_unverified": ["full_name"]}

    def fresh() -> InterviewController:
        ctrl = InterviewController(
            c.parse_context_factory("es"), lambda: NOW, lambda: "x", lambda e: None
        )
        ctrl.start()
        ctrl.on_candidate_text(turn.text)
        return ctrl

    declined = fresh()
    declined.record("consent_recording", "no", "no acepto")
    declined.record("consent_recording", "no", "no acepto")  # confirmed
    abandoned = fresh()
    for n, ctrl in enumerate((declined, abandoned)):
        record = await c.finalizer.finalize(
            ctrl,
            [turn],
            conversation_id=f"01J9ZZZZZZZZZZZZZZZZZZZZZ{n}",
            started_at=NOW,
            model_info=info,
            channel="text",
            metrics=metrics,
        )
        assert record.transcript == []
        assert record.metrics == {"candidate_turns": 1}
    assert not declined._recent_candidate


def test_missing_faq_files_fall_back_to_null_retriever(settings: Settings, tmp_path: Path) -> None:
    (tmp_path / "stores.json").write_text(
        (bootstrap.DEFAULT_KNOWLEDGE_DIR / "stores.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    c = build_container(settings, knowledge_dir=tmp_path)
    assert isinstance(c.retriever, NullRetriever)
