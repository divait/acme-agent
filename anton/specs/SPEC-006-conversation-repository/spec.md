---
id: SPEC-006
title: Conversation repository with atomic JSON storage
status: verified
mode: full
origin_type: technical
origin: Recruiters need a validated JSON candidate record with transcript, summary and a routing status with reasons; a human always decides.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-006, ADR-014]
supersedes: []
superseded_by: null
depends_on: [SPEC-002]
touches: [src/acme_agent/storage/repository.py, src/acme_agent/storage/json_repo.py, src/acme_agent/cli.py, tests/unit/test_json_repo.py]
parent: null
---

# SPEC-006 — Conversation repository with atomic JSON storage

## Problem & Scope
Persist and load `ConversationRecord`s through a `ConversationRepository` protocol with a JSON-file implementation, plus CLI commands to inspect and purge records.

## Non-goals
- GCS implementation (SPEC-016).
- Querying beyond what the PoC needs (list, get, find unfinished by phone, purge by age).

## Functional Requirements
- `ConversationRepository` protocol (async): `save(record)`, `get(conversation_id) -> record | None`, `list(limit=None) -> list[RecordSummary]`, `find_unfinished_by_phone(e164) -> record | None`, `purge_older_than(days) -> int`.
- `JsonConversationRepository(data_dir)` stores `{data_dir}/{conversation_id}.json` (pretty-printed, UTF-8, `ensure_ascii=False`).
- `find_unfinished_by_phone` returns the most recent record whose `end_reason` is `abandoned` (or null) with matching `candidate.phone`.
- CLI: `acme-agent show <id>` prints the record (pretty JSON or a short human view with `--summary`); `acme-agent list` prints id, date, role, status, end reason; `acme-agent purge --older-than DAYS` (defaults to `ACME_RETENTION_DAYS`) with a confirmation flag `--yes`.
- `make_repository(settings)` factory chooses by `ACME_STORAGE` (`json` now; `gcs` raises a clear "not available until SPEC-016" error).

## Technical Requirements
- Atomic write: temp file in the same directory, `flush` + `os.fsync`, `os.replace` (ADR-006.2).
- File I/O runs in a thread (`asyncio.to_thread`) so it never blocks the event loop.
- Conversation ids are ULIDs; reject ids that are not valid ULIDs to prevent path traversal.
- Corrupted files are skipped by `list` with a warning log, never crash it.
- Only `storage/` touches record files (ADR-006.1).

## Acceptance Criteria
- Save/get round-trip test; list ordering by `started_at` desc; purge removes only old files.
- A simulated failure during write (monkeypatched `os.replace`) leaves the previous file intact and no temp file behind.
- `get("../etc/passwd")` raises `ValueError`.
- `find_unfinished_by_phone` ignores completed records and returns the most recent abandoned one.
- `acme-agent list` and `show` work on a temp data dir in a CLI test (typer `CliRunner`).

## Dependencies & Risks
- Scanning files for phone lookup is O(n); acceptable for the PoC and documented as scale-up work.

## Plan
Protocol first, JSON implementation test-first, then CLI commands wired through `make_repository`.

## Tasks
- [x] Define `ConversationRepository` and `RecordSummary` in `storage/repository.py`
- [x] Implement `JsonConversationRepository` with atomic writes + tests
- [x] Implement `find_unfinished_by_phone` and `purge_older_than` + tests
- [x] Add `make_repository(settings)` factory
- [x] Add CLI `list`, `show`, `purge` + CLI tests

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 13:48 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: c7ad1b4
- plan/tasks: pre-existing

### 2026-10-18 13:52 [anton-team] iteration 1 — T1–T5 repository, JSON store, lookup, factory, CLI
- swe (sonnet): done · commit ef9ba9f · files: src/acme_agent/storage/repository.py, src/acme_agent/storage/json_repo.py, src/acme_agent/cli.py, tests/unit/test_json_repo.py
- tester (sonnet, full): PASS · 671 passed; storage+cli coverage 97 %; every criterion probed (atomic write under failing `os.replace`, path-traversal ids, lookup semantics, CLI exit codes, gcs error) · observations routed to swe: `purge` never deletes unreadable files (retention/GDPR gap), `get` on a corrupt file raises `ValidationError` (CLI traceback), dry-run purge uses `datetime.now()` instead of the repository clock
- deviations: swe report was empty; results taken from the commit and the tester run

### 2026-10-18 13:54 [anton-team] iteration 2 — tester observations
- swe (sonnet): done · commits ef3f96a (purge unreadable files by mtime, `CorruptRecordError` + CLI exit 3, `purge_candidates` shared by dry run and delete) and 66abe13 (fix mypy error introduced in ef3f96a: builtin `list` shadowed in an annotation)
- tester: PASS (tech-lead re-run) · `uv run pytest -q` → 674 passed without ADC; `make lint typecheck cov` clean; storage+cli coverage 95 %
- deviations: stray `.tmp-*.json` files from a crashed write are treated as unreadable and purged by age (desirable for retention)

### 2026-10-18 13:56 [anton-team] review round 1
- reviewer: APPROVE · all criteria met; atomic write, id validation, PII-free logs verified · notes: temp files `.tmp-*.json` match the record glob (spurious warnings; a 0-day purge could delete an in-flight write); foreign `*.json` in the data dir would be purged; no directory fsync; protocol methods undocumented; `CorruptRecordError` shares `ValueError` with invalid ids; concurrent persister vs final save is a SPEC-008 obligation; GCS conflict error is a SPEC-016 obligation
- tech-lead: added the persister/final-save ordering to SPEC-008 acceptance criteria and `ConflictError` to SPEC-016 technical requirements; data-safety notes routed to swe before closing

### 2026-10-18 13:58 [anton-team] iteration 3 — post-review hardening
- swe (sonnet): done · commit 7b550e5 · files: storage/json_repo.py (`.<random>.tmp` temp files, record filter = `*.json` with a valid id stem, stale-temp cleanup > 1 h by injected clock, directory fsync), storage/repository.py (`RepositoryError`, `InvalidConversationIdError(ValueError)`, `CorruptRecordError(RepositoryError)`, protocol docstrings), cli.py, tests/unit/test_json_repo.py (`data_dir` fixture, foreign/in-flight files, stale tmp, error types)
- tester: PASS (tech-lead re-run + probe) · `uv run pytest -q` → 678 passed without ADC; `make lint typecheck cov` clean; storage+cli 92 %; `purge --older-than 0 --yes` on a dir with notes.json, README.md and an in-flight `.tmp` → 0 deleted, all three files kept, `list` → none

### 2026-10-18 13:58 [anton-team] implemented
- PR: not opened — project builds directly on `main` (commits c7ad1b4..HEAD); 678 tests, lint, mypy and coverage green

### 2026-10-18 13:58 [anton-team] verified (on main, no PR)


## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Save/get round-trip test; list ordering by `started_at` desc; purge removes only old files. | test | pass | tests/unit/test_json_repo.py::test_round_trip_and_utf8, ::test_list_order_limit_and_corrupt, ::test_purge_only_old, ::test_purge_corrupt_by_mtime; 678 passed |
| A simulated failure during write (monkeypatched `os.replace`) leaves the previous file intact and no temp file behind. | test | pass | ::test_failed_replace_keeps_previous_file (bytes unchanged, directory holds only the record file) |
| `get("../etc/passwd")` raises `ValueError`. | test | pass | ::test_invalid_id_raises (5 traversal/garbage ids; `InvalidConversationIdError` is a `ValueError`) |
| `find_unfinished_by_phone` ignores completed records and returns the most recent abandoned one. | test | pass | ::test_find_unfinished_by_phone, ::test_find_unfinished_accepts_no_end_reason |
| `acme-agent list` and `show` work on a temp data dir in a CLI test (typer `CliRunner`). | test | pass | ::test_cli_list_show_purge, ::test_cli_list_empty, ::test_cli_show_corrupt (exit 3) |
