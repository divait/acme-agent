"""Composition root: wires settings, repository, retriever, parse context and finalizer."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import structlog
from google import genai

from acme_agent.analysis.post_call import PostCallFinalizer
from acme_agent.config import Settings
from acme_agent.domain.models import ConversationRecord, ModelInfo, Store, TranscriptTurn
from acme_agent.domain.validators import ParseContext
from acme_agent.interview.controller import InterviewController
from acme_agent.knowledge.embedder import VertexEmbedder
from acme_agent.knowledge.faq import load_faq
from acme_agent.knowledge.retriever import (
    EmbeddingRetriever,
    LazyRetriever,
    NullRetriever,
    Retriever,
    faq_digest,
)
from acme_agent.llm import make_genai_client
from acme_agent.storage.json_repo import make_repository
from acme_agent.storage.repository import ConversationRepository

DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
TIMEZONE = "Europe/Madrid"
Language = Literal["es", "en"]
FAQ_FILES = ("faq_es.md", "faq_en.md")
log = structlog.get_logger(__name__)


class SessionFinalizer(Protocol):
    async def finalize(
        self,
        controller: InterviewController,
        transcript: list[TranscriptTurn],
        *,
        conversation_id: str,
        started_at: datetime,
        model_info: ModelInfo,
        channel: str,
        metrics: dict[str, Any] | None = None,
    ) -> ConversationRecord:
        """Turn a finished session into its stored record."""
        ...


class SaveOnlyFinalizer:
    """Builds the record, saves (transcript only with consent) it; no post-call analysis."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    async def finalize(
        self,
        controller: InterviewController,
        transcript: list[TranscriptTurn],
        *,
        conversation_id: str,
        started_at: datetime,
        model_info: ModelInfo,
        channel: str,
        metrics: dict[str, Any] | None = None,
    ) -> ConversationRecord:
        record = controller.build_record(
            conversation_id,
            started_at,
            model_info,
            channel=channel,
            transcript=transcript,
            metrics=metrics,
        )
        await self._repository.save(record)
        return record


class ParseContextFactory(Protocol):
    def __call__(self, language: Language = "es") -> ParseContext: ...


class AppContainer:
    """Everything a session needs, built once from `Settings`."""

    def __init__(
        self,
        settings: Settings,
        repository: ConversationRepository,
        retriever: Retriever,
        parse_context_factory: ParseContextFactory,
        finalizer: SessionFinalizer,
        vocabulary: tuple[str, ...] = (),
    ) -> None:
        self.vocabulary = vocabulary
        self.settings = settings
        self.repository = repository
        self.retriever = retriever
        self.parse_context_factory = parse_context_factory
        self.finalizer = finalizer

    @cached_property
    def genai_client(self) -> genai.Client:
        """Created on first use, so construction never touches credentials or the network."""
        return make_genai_client(self.settings)


def load_stores(knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR) -> list[Store]:
    raw = json.loads((knowledge_dir / "stores.json").read_text(encoding="utf-8"))
    return [Store.model_validate(item) for item in raw]


def store_vocabulary(stores: list[Store]) -> tuple[str, ...]:
    """Brand, store names, cities and areas (deduplicated), as speech-recognition hints."""
    seen: dict[str, None] = {"Acme Burgers": None}
    for store in stores:
        for term in (store.name, store.city, store.area):
            if term:
                seen.setdefault(term)
    return tuple(seen)


def build_retriever(
    settings: Settings,
    client_factory: Callable[[], genai.Client],
    knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR,
) -> Retriever:
    """Embedding retriever over the FAQ files, built lazily (first search or `warm()`).

    Falls back to `NullRetriever` with a warning when the FAQ files are missing.
    """
    paths = [knowledge_dir / name for name in FAQ_FILES]
    if not all(p.is_file() for p in paths):
        log.warning("faq_files_missing", dir=str(knowledge_dir))
        return NullRetriever()

    async def factory() -> Retriever:
        chunks = await asyncio.to_thread(load_faq, paths)
        embedder = VertexEmbedder(client_factory(), settings.embedding_model)
        return await EmbeddingRetriever.build(
            embedder,
            chunks,
            settings.faq_thresholds,
            cache_path=settings.faq_index_path,
            digest=await asyncio.to_thread(faq_digest, paths, settings.embedding_model),
        )

    return LazyRetriever(factory, timeout_s=settings.faq_timeout_s)


def build_container(
    settings: Settings,
    *,
    clock: Callable[[], datetime] | None = None,
    knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR,
) -> AppContainer:
    now = clock or (lambda: datetime.now(UTC))
    stores = load_stores(knowledge_dir)

    def parse_context_factory(language: Language = "es") -> ParseContext:
        return ParseContext(
            today=now().astimezone(ZoneInfo(TIMEZONE)).date(),
            country="ES",
            stores=stores,
            language=language,
        )

    repository = make_repository(settings)
    container = AppContainer(
        settings=settings,
        repository=repository,
        retriever=NullRetriever(),
        parse_context_factory=parse_context_factory,
        finalizer=SaveOnlyFinalizer(repository),
        vocabulary=store_vocabulary(stores),
    )
    container.retriever = build_retriever(settings, lambda: container.genai_client, knowledge_dir)
    if settings.post_call == "on":
        # The client is resolved on first use, so building the container stays offline.
        container.finalizer = PostCallFinalizer(
            lambda: container.genai_client, settings, repository
        )
    return container
