---
id: ADR-007
title: Lightweight RAG over a job FAQ
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-007 — Lightweight RAG over a job FAQ

## Context
Candidates ask questions mid-interview (pay, shifts, uniforms, stores, process). Answers
must come from Acme's knowledge and never be invented. The FAQ is ~30 short sections.

## Decision
`knowledge/faq_{es,en}.md` chunked per `##` section, embedded with Vertex
`text-embedding-005`, searched in memory (numpy cosine top-3 with a threshold), exposed
to the model only via the `search_faq` tool. Index cached on disk keyed by file hash.

## Rules
- **ADR-007.1** — FAQ content is never included in the system instruction; the model gets
  it only through `search_faq` results.
  _Check:_ grep `interview/prompts.py` for FAQ text; prompt test asserts no FAQ section titles.
- **ADR-007.2** — When the best similarity is below the configured threshold,
  `search_faq` returns `found: false` and no answers.
  _Check:_ retriever unit test with an off-topic query.
- **ADR-007.3** — Every answered FAQ query is logged as an event with its `source` section.
  _Check:_ tool test asserts a `faq_answered` event with `source`.
- **ADR-007.4** — The retriever is used behind a `Retriever` protocol so tests use a fake
  embedder and need no network.
  _Check:_ `knowledge/retriever.py` defines the protocol; unit tests run offline.

## Consequences
- One embedding call per chunk at startup (cached).
- Vertex RAG Engine is listed as a future improvement for larger knowledge bases.

## Alternatives considered
- **Whole FAQ in the prompt** — rejected: bloats every turn, no traceability, does not scale per tenant.
- **Vertex AI RAG Engine / Vector Search** — rejected for ~30 chunks: managed infra without benefit.
