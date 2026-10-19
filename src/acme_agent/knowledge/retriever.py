"""FAQ retrieval (ADR-007): the `Retriever` port, `NullRetriever` and `EmbeddingRetriever`."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import structlog
from pydantic import BaseModel, Field

from acme_agent.knowledge.embedder import Embedder
from acme_agent.knowledge.faq import FaqChunk

log = structlog.get_logger(__name__)
TOP_K = 3
DEFAULT_THRESHOLD = 0.55


class FaqAnswer(BaseModel):
    text: str
    source: str
    score: float


class FaqResult(BaseModel):
    found: bool
    answers: list[FaqAnswer] = Field(default_factory=list)


class Retriever(Protocol):
    async def search(self, question: str, language: str) -> FaqResult:
        """Return the best FAQ passages for the question, or `found=False`."""
        ...


class NullRetriever:
    """Retriever that never finds anything; every question is left for a recruiter."""

    async def search(self, question: str, language: str) -> FaqResult:
        return FaqResult(found=False, answers=[])


def faq_digest(paths: Sequence[Path], model: str) -> str:
    """SHA-256 over the FAQ files' bytes and the embedding model name (cache key)."""
    h = hashlib.sha256(model.encode("utf-8"))
    for path in sorted(paths, key=lambda p: p.name):
        h.update(path.name.encode("utf-8"))
        h.update(path.read_bytes())
    return h.hexdigest()


def _chunk_input(chunk: FaqChunk) -> str:
    return f"{chunk.title}\n{chunk.text}"


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    normalised: np.ndarray = (matrix / norms).astype(np.float32)
    return normalised


class EmbeddingRetriever:
    """Cosine top-3 over an in-memory normalised matrix of FAQ chunk embeddings."""

    def __init__(
        self,
        embedder: Embedder,
        chunks: list[FaqChunk],
        matrix: np.ndarray,
        threshold: float | Mapping[str, float] = 0.55,
    ) -> None:
        if len(chunks) != matrix.shape[0]:
            raise ValueError("matrix rows must match chunks")
        self._embedder = embedder
        self._chunks = chunks
        self._matrix = _normalise(matrix)
        self._threshold = threshold
        self._by_language: dict[str, np.ndarray] = {}
        for language in {c.language for c in chunks}:
            self._by_language[language] = np.array(
                [i for i, c in enumerate(chunks) if c.language == language], dtype=np.int64
            )

    @classmethod
    async def build(
        cls,
        embedder: Embedder,
        chunks: list[FaqChunk],
        threshold: float | Mapping[str, float] = 0.55,
        *,
        cache_path: Path | None = None,
        digest: str = "",
    ) -> EmbeddingRetriever:
        """Embed the chunks (task RETRIEVAL_DOCUMENT), or load the matrix from the cache."""
        matrix = (
            await asyncio.to_thread(_load_cache, cache_path, digest, len(chunks))
            if cache_path and digest
            else None
        )
        if matrix is None:
            started = time.perf_counter()
            matrix = await embedder.embed([_chunk_input(c) for c in chunks], "RETRIEVAL_DOCUMENT")
            log.info(
                "faq_index_built",
                chunks=len(chunks),
                ms=round((time.perf_counter() - started) * 1000),
            )
            if cache_path and digest:
                await asyncio.to_thread(_save_cache, cache_path, digest, matrix)
        else:
            log.info("faq_index_cache_hit", chunks=len(chunks))
        return cls(embedder, chunks, matrix, threshold)

    def _limit(self, language: str) -> float:
        if isinstance(self._threshold, Mapping):
            # A language without its own entry (not es/en) uses the default threshold.
            return self._threshold.get(language, DEFAULT_THRESHOLD)
        return self._threshold

    def rank(self, query_vector: np.ndarray, language: str) -> FaqResult:
        """In-memory search for an already-embedded query."""
        query = _normalise(query_vector.reshape(1, -1))[0]
        scores = self._matrix @ query
        order = [language] + [lang for lang in self._by_language if lang != language]
        for lang in order:
            idx = self._by_language.get(lang)
            if idx is None or idx.size == 0:
                continue
            lang_scores = scores[idx]
            top = np.argsort(-lang_scores)[:TOP_K]
            limit = self._limit(lang)
            answers = [
                FaqAnswer(
                    text=self._chunks[int(idx[t])].text,
                    source=self._chunks[int(idx[t])].source,
                    score=round(float(lang_scores[t]), 4),
                )
                for t in top
                if float(lang_scores[t]) >= limit
            ]
            if answers:
                return FaqResult(found=True, answers=answers)
        return FaqResult(found=False, answers=[])

    async def search(self, question: str, language: str) -> FaqResult:
        started = time.perf_counter()
        vectors = await self._embedder.embed([question], "RETRIEVAL_QUERY")
        embed_ms = (time.perf_counter() - started) * 1000
        result = self.rank(vectors[0], language)
        log.info(
            "faq_search",
            language=language,
            found=result.found,
            top_score=result.answers[0].score if result.answers else None,
            embed_ms=round(embed_ms, 1),
        )
        return result


def _load_cache(path: Path, digest: str, rows: int) -> np.ndarray | None:
    try:
        with np.load(path, allow_pickle=False) as data:
            if str(data["digest"]) != digest:
                return None
            matrix = np.asarray(data["matrix"], dtype=np.float32)
    except (OSError, KeyError, ValueError):
        return None
    return matrix if matrix.shape[0] == rows else None


def _save_cache(path: Path, digest: str, matrix: np.ndarray) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp.npz")
        np.savez(tmp, digest=np.array(digest), matrix=matrix)
        tmp.replace(path)
    except OSError:
        log.warning("faq_index_cache_write_failed")


class LazyRetriever:
    """Builds the real retriever on first use (or `warm()`), so startup never blocks.

    The build runs in one shared background task that searches await through `asyncio.shield`,
    so a search that times out never cancels it. Each search is bounded by `timeout_s`; on
    timeout or build failure it degrades to `found=False`. After a failed build, searches
    return `found=False` immediately for `backoff_s`, then one retry is allowed.
    """

    def __init__(
        self,
        factory: Callable[[], Awaitable[Retriever]],
        *,
        timeout_s: float = 2.0,
        backoff_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory = factory
        self._timeout_s = timeout_s
        self._backoff_s = backoff_s
        self._clock = clock
        self._inner: Retriever | None = None
        self._build_task: asyncio.Task[None] | None = None
        self._failed_at: float | None = None

    def _in_backoff(self) -> bool:
        return self._failed_at is not None and self._clock() - self._failed_at < self._backoff_s

    async def _build(self) -> None:
        try:
            self._inner = await self._factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._failed_at = self._clock()
            raise

    @staticmethod
    def _consume(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()  # mark retrieved; callers that await it still see it

    async def warm(self) -> None:
        """Wait for the (shared) build; raises if it fails. A no-op during the backoff window."""
        if self._inner is not None or self._in_backoff():
            return
        if self._build_task is None or self._build_task.done():
            self._build_task = asyncio.create_task(self._build())
            self._build_task.add_done_callback(self._consume)
        await asyncio.shield(self._build_task)

    async def close(self) -> None:
        """Cancel a running build (shutdown)."""
        task = self._build_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def search(self, question: str, language: str) -> FaqResult:
        miss = FaqResult(found=False, answers=[])
        if self._inner is None and self._in_backoff():
            return miss
        try:
            async with asyncio.timeout(self._timeout_s):
                await self.warm()
                if self._inner is None:  # warm() was skipped by a concurrent backoff
                    return miss
                return await self._inner.search(question, language)
        except TimeoutError:
            log.warning("faq_search_timeout", timeout_s=self._timeout_s)
        except Exception:
            log.warning("faq_index_unavailable", exc_info=True)
        return miss
