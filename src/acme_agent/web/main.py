"""uvicorn factory entry point: `acme_agent.web.main:create_default_app`."""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from fastapi import FastAPI

from acme_agent.bootstrap import build_container
from acme_agent.config import get_settings
from acme_agent.knowledge.retriever import LazyRetriever
from acme_agent.logging import configure_logging
from acme_agent.web.app import create_app
from acme_agent.web.session import InterviewSession

log = structlog.get_logger(__name__)


def create_default_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)  # reload workers are fresh processes
    container = build_container(settings)
    app = create_app(container, session_factory=InterviewSession)
    retriever = container.retriever

    async def warm_faq_index() -> None:
        """Build/load the FAQ index in the background so the first question is fast."""
        if isinstance(retriever, LazyRetriever):
            app.state.faq_warmup = asyncio.create_task(_warm(retriever))

    async def stop_faq_warmup() -> None:
        task = getattr(app.state, "faq_warmup", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if isinstance(retriever, LazyRetriever):
            await retriever.close()

    app.router.add_event_handler("startup", warm_faq_index)
    app.router.add_event_handler("shutdown", stop_faq_warmup)
    return app


async def _warm(retriever: LazyRetriever) -> None:
    # A failed warm-up is logged; the next search after the backoff window retries.
    try:
        await retriever.warm()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("faq_index_warmup_failed", exc_info=True)
