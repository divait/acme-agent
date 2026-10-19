---
id: ADR-006
title: Storage: JSON files behind a repository interface
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-006 — Storage: JSON files behind a repository interface

## Context
Conversations and extracted data must be stored as JSON. The PoC runs locally and
optionally on Cloud Run, whose filesystem is ephemeral.

## Decision
A `ConversationRepository` protocol with a **JSON file implementation** (default,
`data/conversations/{id}.json`) and an optional **GCS implementation** selected by
`ACME_STORAGE=json|gcs`.

## Rules
- **ADR-006.1** — Conversation records are read and written only through
  `ConversationRepository`; no other module opens files under the data directory or calls GCS.
  _Check:_ grep `open(`, `write_text`, `google.cloud.storage` outside `storage/`.
- **ADR-006.2** — The JSON implementation writes atomically (temp file + `os.replace`).
  _Check:_ read `storage/json_repo.py`; test that a failed write leaves the previous file intact.
- **ADR-006.3** — Every record carries `schema_version`; changing the record shape bumps it.
  _Check:_ `ConversationRecord.schema_version` exists; diff review of `domain/models.py`.

## Consequences
- Human-readable records, zero setup, easy to show in a demo.
- No cross-conversation querying beyond scanning (fine at PoC scale).

## Alternatives considered
- **SQLite/Postgres** — rejected for the PoC: setup without benefit at this scale.
- **Firestore** — deferred: the natural production store; the interface keeps it a drop-in.
