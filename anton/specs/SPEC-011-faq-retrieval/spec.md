---
id: SPEC-011
title: FAQ retrieval tool (RAG)
status: verified
mode: full
origin_type: technical
origin: Candidates ask job questions mid-call and must get answers grounded in Acme's FAQ, or a recruiter follow-up when the FAQ has no answer.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-002, ADR-007, ADR-012]
supersedes: []
superseded_by: null
depends_on: [SPEC-004, SPEC-007]
touches: [src/acme_agent/knowledge/faq.py, src/acme_agent/knowledge/retriever.py, src/acme_agent/bootstrap.py, tests/unit/test_faq.py, tests/unit/test_retriever.py, tests/fixtures/faq_questions.yaml]
parent: null
---

# SPEC-011 — FAQ retrieval tool (RAG)

## Problem & Scope
Replace the `NullRetriever` with an embeddings-based retriever over `knowledge/faq_{es,en}.md` so `search_faq` answers job questions from Acme's FAQ only, says when it does not know, and records the source.

Design: DESIGN §11, TECHNICAL_DESIGN §9.

## Non-goals
- Managed vector databases or Vertex RAG Engine.
- Retrieval over anything other than the FAQ files.

## Functional Requirements
- `load_faq(paths) -> list[FaqChunk(id, language, title, text, source)]` splitting on `## ` headings and reading `<!-- id: ... -->`.
- `EmbeddingRetriever(embedder, chunks, threshold)`: builds a normalised matrix at startup (`task_type=RETRIEVAL_DOCUMENT`), caches it to `data/index.npz` keyed by SHA-256 of the FAQ files, embeds queries with `task_type=RETRIEVAL_QUERY`, returns top-3 by cosine filtered to the requested language first, falling back to the other language.
- Below `threshold` (default 0.55, setting `ACME_FAQ_THRESHOLD`) → `found: false` (ADR-007.2).
- `search_faq` results: `{found, answers: [{text, source, score}]}`; events `faq_answered` with `source` or `faq_missed` (ADR-007.3).
- `bootstrap.py` builds the real retriever when FAQ files exist, else keeps `NullRetriever` with a warning.

## Technical Requirements
- `Embedder` protocol with `VertexEmbedder` (`google-genai` `embed_content`, model `settings.embedding_model`) and a deterministic `FakeEmbedder` for tests (bag-of-words hashing) (ADR-007.4).
- Retrieval is in memory, < 5 ms for the FAQ size; query embedding is the only network call.
- A labelled question set (`tests/fixtures/faq_questions.yaml`, ~20 ES/EN questions with expected section ids plus 5 off-topic) is used by a `live`-marked test to tune the threshold.
- Section-id parity test between `faq_es.md` and `faq_en.md` (ADR-012.1).

## Acceptance Criteria
- Offline unit tests: chunking, id parsing, cache hit/miss on file change, language fallback, below-threshold `found: false`.
- Parity test passes for the FAQ files.
- `pytest -m live tests/unit/test_retriever.py` reaches top-1 accuracy ≥ 0.85 on the labelled set and returns `found: false` for ≥ 4 of 5 off-topic questions.
- In text mode, asking "¿cuánto pagan a los repartidores?" yields an answer with the rider pay figure from the FAQ and a `faq_answered` event.

## Dependencies & Risks
- Threshold tuning differs between ES and EN; allow per-language thresholds if the labelled set shows a gap.

## Plan
FAQ loader and parity test first, then retriever with the fake embedder, then the Vertex embedder and cache, then wiring and tuning with the labelled set.

## Tasks
- [x] Implement `knowledge/faq.py` loader + tests + parity test
- [x] Implement `Embedder` protocol, `FakeEmbedder`, `VertexEmbedder`
- [x] Implement `EmbeddingRetriever` with cache and language fallback + tests
- [x] Wire into `bootstrap.py` and `search_faq`
- [x] Write labelled question set and live tuning test; set threshold

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 18:35 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 25aec91
- plan: one swe dispatch (loader + parity, Embedder protocol / Fake / Vertex, EmbeddingRetriever with npz cache + language fallback, bootstrap + search_faq wiring, labelled set + live tuning run, text-mode rider-pay check), then tester, reviewer
- notes: query embedding is on the tool path (one network call per `search_faq`) — measure it; FAQ file under knowledge/ at repo root (not src/acme_agent/knowledge/, which holds code)

### 2026-10-18 18:40 [anton-team] iteration 1 — build
- swe (sonnet): done · commit 52e7732 · knowledge/{faq,embedder}.py, EmbeddingRetriever (npz cache keyed by SHA-256 of files + model, atomic write, corrupt = miss), `LazyRetriever` (sync offline `build_container`; web startup warms in background; build failure → found false + warning), settings `ACME_FAQ_THRESHOLD` (+ optional per-language), `faq_search` log (language, found, top_score, embed_ms — no query text), labelled set (20 + 5 off-topic), live tests
- tester: tech-lead re-run → 1026 passed · live retriever: top-1 19/20 = 0.95 (miss: es "¿cuánto tarda… hasta empezar?" → start-date vs hiring-timeline, ambiguous), off-topic 5/5 found false; in-topic scores 0.626–0.776, off-topic 0.376–0.501 → threshold 0.55 kept, single value for both languages · query embedding ≈ 230–250 ms (one 438 ms) · cold index build 3.3 s for 52 chunks · live text mode: "¿cuánto pagan a los repartidores?" → reply with 10,50 and 12,50, `faq_answered` source faq_es.md#pay-rider
- deviations: parity already covered by tests/unit/test_knowledge_content.py::test_faq_ids_match_across_languages (not duplicated); `LazyRetriever` instead of building at bootstrap (keeps the offline container sync); tools.py unchanged (already emitted events)

### 2026-10-18 18:46 [anton-team] iteration 2 — review round 1 fixes
- reviewer (round 1): REVISE · [major] R-012 search_faq unbounded (no timeout on the query embedding, inline cold build under the lock, failed build retried on every search) · [major] R-004 startup warm-up swallowed exceptions and was never cancelled · minors: sync file I/O in the async build, unbounded per-language thresholds, cache path from data_dir.parent, undocumented `_limit` fallback
- swe (sonnet): done · commit 007cd47 · `ACME_FAQ_TIMEOUT_S` (2 s) per search → `faq_search_timeout` + found false; one shared shielded build task; 60 s backoff after a failed build; `faq_index_warmup_failed` logged; warm task cancelled on shutdown + `LazyRetriever.close()`; `acme-agent chat` warms in the background; to_thread file I/O; bounds; `ACME_FAQ_INDEX_PATH` (default data/index.npz)
- tester: tech-lead re-run → 1031 passed · live retriever 1 passed (cold build 2.4 s, query embed 245–295 ms) · live text-mode rider pay: first run without warm-up hit the 2 s timeout (degrade path works live: found false); with warm-up (as `chat` now does) passed, embed 752 ms, score 0.78
- known limit: with a cold cache, a question asked before the background build finishes (~2.4 s after start) gets found false → Ana offers a recruiter follow-up; the greeting and consent take longer than that, so it is unlikely in practice

### 2026-10-18 19:02 [anton-team] iteration 3 — review round 2
- reviewer (round 2): APPROVE · all 6 round-1 findings fixed; 1031 passed, ruff/mypy clean
- minor fixed · swe commit daf4ebc · warm-up test uses the offline `settings` fixture (no real .env), typed helpers
- follow-up: backoff (60 s) hard-coded at the bootstrap call site — make it a setting if it needs tuning
- status: verified (on main, no PR)

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Offline unit tests: chunking, id parsing, cache hit/miss on file change, language fallback, below-threshold found false | test | pass | `uv run pytest -q` → 1032 passed; tests/unit/test_faq.py::test_splits_and_parses_ids, ::test_missing_id_raises; tests/unit/test_retriever.py::test_cache_hit_and_miss, ::test_corrupt_cache_is_a_miss, ::test_language_fallback_only_when_requested_language_misses, ::test_below_threshold_not_found, ::test_per_language_threshold, ::test_lazy_search_times_out_without_cancelling_build, ::test_lazy_failed_build_backs_off_then_retries |
| Parity test passes for the FAQ files | test | pass | tests/unit/test_knowledge_content.py::test_faq_ids_match_across_languages; tests/unit/test_faq.py::test_load_real_files (26 es / 26 en) |
| `pytest -m live tests/unit/test_retriever.py`: top-1 ≥ 0.85, ≥ 4/5 off-topic found false | live test | pass | iteration 1: 19/20 = 0.95, off-topic 5/5, in-topic 0.626–0.776 vs off-topic 0.376–0.501, threshold 0.55; iteration 2 re-run passed |
| Text mode "¿cuánto pagan a los repartidores?" → rider pay figure + faq_answered | live test | pass | tests/integration/test_text_mode.py::test_rider_pay_question_is_answered_from_faq → 10,50 and 12,50, source faq_es.md#pay-rider |
