"""Embedding retriever: offline behaviour with the fake embedder, plus the live tuning test."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import pytest
import yaml

from acme_agent.config import Settings
from acme_agent.knowledge.embedder import FakeEmbedder
from acme_agent.knowledge.faq import FaqChunk, load_faq
from acme_agent.knowledge.retriever import (
    EmbeddingRetriever,
    FaqResult,
    LazyRetriever,
    NullRetriever,
    Retriever,
    faq_digest,
)

KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "faq_questions.yaml"


def _chunk(cid: str, lang: str, title: str, text: str) -> FaqChunk:
    return FaqChunk(id=cid, language=lang, title=title, text=text, source=f"faq_{lang}.md#{cid}")


CHUNKS = [
    _chunk("pay", "es", "salario pago repartidor", "cobran euros por hora"),
    _chunk("uniform", "es", "uniforme ropa", "te damos camiseta y gorra"),
    _chunk("pay", "en", "rider salary pay", "riders earn euros per hour"),
    _chunk("uniform", "en", "uniform clothes", "we give you a shirt and cap"),
]


async def _retriever(threshold: float = 0.3) -> EmbeddingRetriever:
    return await EmbeddingRetriever.build(FakeEmbedder(), CHUNKS, threshold)


async def test_protocol_and_top_hit() -> None:
    r: Retriever = await _retriever()
    result = await r.search("cuanto es el salario de repartidor", "es")
    assert result.found
    assert result.answers[0].source == "faq_es.md#pay"
    assert 0 < result.answers[0].score <= 1.0
    assert all(a.source.startswith("faq_es") for a in result.answers)


async def test_below_threshold_not_found() -> None:
    result = await (await _retriever()).search("zzz qqq xxx", "es")
    assert result.found is False
    assert result.answers == []


async def test_language_fallback_only_when_requested_language_misses() -> None:
    r = await _retriever()
    # English words, Spanish requested: nothing in ES passes, EN does.
    result = await r.search("rider salary pay", "es")
    assert result.found and result.answers[0].source == "faq_en.md#pay"
    # Requested-language hit wins even if the other language scores equally well.
    result = await r.search("uniforme ropa", "es")
    assert result.answers[0].source == "faq_es.md#uniform"


async def test_per_language_threshold() -> None:
    r = await EmbeddingRetriever.build(FakeEmbedder(), CHUNKS, {"es": 0.99, "en": 0.3})
    result = await r.search("salario pago repartidor", "es")
    # ES threshold is too strict for a partial match; EN has nothing relevant either.
    assert result.found is False


async def test_top_three_cap() -> None:
    chunks = [_chunk(f"c{i}", "es", "pago salario", f"pago salario {i}") for i in range(6)]
    r = await EmbeddingRetriever.build(FakeEmbedder(), chunks, 0.1)
    result = await r.search("pago salario", "es")
    assert len(result.answers) == 3


async def test_cache_hit_and_miss(tmp_path: Path) -> None:
    cache = tmp_path / "index.npz"
    files = [tmp_path / "faq_es.md"]
    files[0].write_text("## Q\n<!-- id: a -->\nx\n", encoding="utf-8")
    digest = faq_digest(files, "m1")
    e1 = FakeEmbedder()
    await EmbeddingRetriever.build(e1, CHUNKS, 0.3, cache_path=cache, digest=digest)
    assert cache.exists() and (len(CHUNKS), "RETRIEVAL_DOCUMENT") in e1.calls
    e2 = FakeEmbedder()
    r2 = await EmbeddingRetriever.build(e2, CHUNKS, 0.3, cache_path=cache, digest=digest)
    assert e2.calls == []  # served from the cache
    assert (await r2.search("rider salary pay", "en")).found
    # File change -> new digest -> miss; model change -> miss.
    files[0].write_text("## Q\n<!-- id: a -->\ny\n", encoding="utf-8")
    assert faq_digest(files, "m1") != digest
    assert faq_digest(files, "m2") != faq_digest(files, "m1")
    e3 = FakeEmbedder()
    await EmbeddingRetriever.build(
        e3, CHUNKS, 0.3, cache_path=cache, digest=faq_digest(files, "m1")
    )
    assert e3.calls


async def test_corrupt_cache_is_a_miss(tmp_path: Path) -> None:
    cache = tmp_path / "index.npz"
    cache.write_bytes(b"not an npz")
    e = FakeEmbedder()
    await EmbeddingRetriever.build(e, CHUNKS, 0.3, cache_path=cache, digest="d")
    assert e.calls


async def test_in_memory_search_is_fast() -> None:
    chunks = load_faq([KNOWLEDGE / "faq_es.md", KNOWLEDGE / "faq_en.md"])
    embedder = FakeEmbedder()
    r = await EmbeddingRetriever.build(embedder, chunks, 0.3)
    vector = (await embedder.embed(["cuánto pagan a los repartidores"], "RETRIEVAL_QUERY"))[0]
    start = time.perf_counter()
    for _ in range(100):
        r.rank(vector, "es")
    assert (time.perf_counter() - start) / 100 < 0.005


async def test_lazy_retriever_builds_once_and_degrades() -> None:
    builds = 0

    async def factory() -> Retriever:
        nonlocal builds
        builds += 1
        return await _retriever()

    lazy = LazyRetriever(factory)
    assert builds == 0
    await lazy.search("rider salary pay", "en")
    await lazy.search("rider salary pay", "en")
    assert builds == 1

    async def boom() -> Retriever:
        raise RuntimeError("no credentials")

    result = await LazyRetriever(boom).search("anything", "es")
    assert result.found is False


async def test_null_retriever() -> None:
    assert (await NullRetriever().search("x", "es")).found is False


def test_settings_thresholds() -> None:
    s = Settings(faq_threshold=0.6, faq_threshold_en=0.5)
    assert s.faq_thresholds == {"es": 0.6, "en": 0.5}
    assert Settings().faq_threshold == 0.55
    assert Settings().faq_timeout_s == 2.0
    with pytest.raises(ValueError):
        Settings(faq_threshold_es=1.5)
    with pytest.raises(ValueError):
        Settings(faq_timeout_s=0)


async def test_unknown_language_uses_default_threshold() -> None:
    r = await EmbeddingRetriever.build(FakeEmbedder(), CHUNKS, {"es": 0.9, "en": 0.9})
    assert r._limit("fr") == 0.55


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_lazy_search_times_out_without_cancelling_build() -> None:
    gate = asyncio.Event()
    started = 0

    async def slow() -> Retriever:
        nonlocal started
        started += 1
        await gate.wait()
        return await _retriever()

    lazy = LazyRetriever(slow, timeout_s=0.05)
    t0 = time.perf_counter()
    assert (await lazy.search("rider salary pay", "en")).found is False
    assert time.perf_counter() - t0 < 0.5
    assert (await lazy.search("rider salary pay", "en")).found is False
    assert started == 1  # shared build, still running
    assert lazy._build_task is not None and not lazy._build_task.done()
    gate.set()
    await lazy.warm()
    assert (await lazy.search("rider salary pay", "en")).found is True


async def test_lazy_slow_embedder_times_out() -> None:
    class Slow:
        async def search(self, question: str, language: str) -> FaqResult:
            await asyncio.sleep(5)
            return FaqResult(found=True)

    async def factory() -> Retriever:
        return Slow()

    lazy = LazyRetriever(factory, timeout_s=0.05)
    t0 = time.perf_counter()
    assert (await lazy.search("x", "es")).found is False
    assert time.perf_counter() - t0 < 0.5


async def test_lazy_failed_build_backs_off_then_retries() -> None:
    calls = 0
    clock = _Clock()

    async def boom() -> Retriever:
        nonlocal calls
        calls += 1
        raise RuntimeError("no credentials")

    lazy = LazyRetriever(boom, backoff_s=60, clock=clock)
    for _ in range(5):
        assert (await lazy.search("x", "es")).found is False
    assert calls == 1
    clock.now = 61
    assert (await lazy.search("x", "es")).found is False
    assert calls == 2
    assert (await lazy.search("x", "es")).found is False
    assert calls == 2


# --- live tuning (needs ADC) -------------------------------------------------------------


@pytest.mark.live
async def test_live_accuracy_and_off_topic(live_settings: Settings, tmp_path: Path) -> None:
    from acme_agent.knowledge.embedder import VertexEmbedder
    from acme_agent.llm import make_genai_client

    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    chunks = load_faq([KNOWLEDGE / "faq_es.md", KNOWLEDGE / "faq_en.md"])
    embedder = VertexEmbedder(make_genai_client(live_settings), live_settings.embedding_model)
    r = await EmbeddingRetriever.build(embedder, chunks, live_settings.faq_thresholds)

    async def top(question: str, language: str) -> tuple[str, float]:
        vector = (await embedder.embed([question], "RETRIEVAL_QUERY"))[0]
        scores = r._matrix @ (vector / np.linalg.norm(vector))
        idx = r._by_language[language]
        best = int(idx[int(np.argmax(scores[idx]))])
        return chunks[best].id, float(scores[best])

    hits = 0
    in_scores: list[float] = []
    for item in data["questions"]:
        got, score = await top(item["q"], item["lang"])
        ok = got == item["expect"]
        hits += ok
        in_scores.append(score)
        print(f"{'OK ' if ok else 'BAD'} {item['lang']} {score:.3f} {got:<22} <- {item['q']}")
    accuracy = hits / len(data["questions"])

    off_missed = 0
    off_scores: list[float] = []
    for item in data["off_topic"]:
        result = await r.search(item["q"], item["lang"])
        _, score = await top(item["q"], item["lang"])
        off_scores.append(score)
        off_missed += not result.found
        print(f"OFF {item['lang']} {score:.3f} found={result.found} <- {item['q']}")
    print(
        f"accuracy={accuracy:.2f} in-topic scores {min(in_scores):.3f}-{max(in_scores):.3f} "
        f"off-topic {min(off_scores):.3f}-{max(off_scores):.3f} "
        f"threshold={live_settings.faq_thresholds}"
    )
    assert accuracy >= 0.85
    assert off_missed >= 4
