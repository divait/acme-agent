"""The web app warms the FAQ index in the background and shuts down cleanly."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from acme_agent.bootstrap import AppContainer, build_container
from acme_agent.config import Settings
from acme_agent.knowledge.retriever import LazyRetriever, Retriever
from acme_agent.web import main


def test_failed_warmup_is_logged_and_shutdown_is_clean(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    calls: list[int] = []

    async def boom() -> Retriever:
        calls.append(1)
        raise RuntimeError("no credentials")

    real = build_container

    def build(s: Settings) -> AppContainer:
        container = real(s)
        container.retriever = LazyRetriever(boom)
        return container

    warnings: list[str] = []

    def record_warning(event: str, **_: Any) -> None:
        warnings.append(event)

    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "configure_logging", lambda level: None)
    monkeypatch.setattr(main, "build_container", build)
    monkeypatch.setattr(main.log, "warning", record_warning)
    app = main.create_default_app()
    with TestClient(app) as client:
        task = cast("asyncio.Task[None]", app.state.faq_warmup)
        assert client.portal is not None
        client.portal.call(_wait, task)
    assert "faq_index_warmup_failed" in warnings
    assert len(calls) == 1


async def _wait(task: asyncio.Task[None]) -> None:
    await asyncio.wait([task])
