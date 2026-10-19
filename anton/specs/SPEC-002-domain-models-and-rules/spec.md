---
id: SPEC-002
title: Domain models and screening rules
status: verified
mode: full
origin_type: technical
origin: Recruiters need a validated JSON candidate record with transcript, summary and a routing status with reasons; a human always decides.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-001, ADR-016, ADR-006, ADR-009, ADR-014]
supersedes: []
superseded_by: null
depends_on: [SPEC-001]
touches: [src/acme_agent/domain/models.py, src/acme_agent/domain/rules.py, tests/unit/test_models.py, tests/unit/test_rules.py]
parent: null
---

# SPEC-002 — Domain models and screening rules

## Problem & Scope
Define the typed domain: enums, the `CandidateProfile`, the `ConversationRecord` stored as JSON, and the deterministic screening rules that turn a profile plus interview facts into a `screening_status` with reasons.

Shapes follow DESIGN §7.1–7.3.

## Non-goals
- Parsing raw spoken input (SPEC-003).
- Interview state machine (SPEC-005).
- Persistence (SPEC-006).

## Functional Requirements
- Enums: `Role` (`crew_member`, `kitchen`, `delivery_rider`), `Day` (`mon`..`sun`), `Shift` (`morning`, `afternoon`, `night`), `ScreeningStatus` (`meets_requirements`, `missing_requirements`, `needs_human_review`), `EndReason` (`completed`, `declined_consent`, `escalated`, `abandoned`), `Speaker` (`agent`, `candidate`), `SlotName` (one value per slot in DESIGN §7.1).
- Value types: `Availability(day, shift)`, `Store(id, name, city, area, country)`.
- `CandidateProfile`: all slots from DESIGN §7.1 as optional typed fields, with a `missing_required()` helper that accounts for rider-only fields.
- `ConversationRecord`: `schema_version="1.0"`, ids, timestamps, `end_reason`, `channel`, `language` (`detected`, `switches[]`), `model` (`live`, `text`, `prompt_version`), `candidate`, `slot_meta` (attempts, source `live_tool|post_call|prefill`, raw, corrected, status), `screening` (status, knockouts, flags, reconciliation_conflicts), `sentiment` (avg, min, frustration_events, trend), `summary` (headline, key_points, candidate_questions, recruiter_next_steps — nullable), `transcript[]` (turn, speaker, text, ts, sentiment?), `events[]` (ts, type, payload), `metrics` (dict), `previous_conversation_id`.
- `rules.evaluate(profile, facts) -> Screening` where `facts` carries `escalated`, `unresolved_slots`, `end_reason`, `reconciliation_conflicts`:
-  - knock-outs: `right_to_work is False`; `is_18_or_over is False`; rider with `driving_licence is False` → `missing_requirements`;
-  - `needs_human_review` when escalated, any unresolved/missing required slot, end_reason is not `completed`, or any conflict — takes precedence over `meets_requirements` but not over knock-outs (both reported);
-  - flags (informational, not knock-outs): rider without own vehicle, start date > 30 days away, weekly hours < 15;
-  - otherwise `meets_requirements`.
- Every result lists the rule ids that fired (e.g. `KO_NO_RIGHT_TO_WORK`, `REVIEW_ESCALATED`, `FLAG_NO_VEHICLE`).

## Technical Requirements
- Pure Pydantic v2 models in `domain/models.py`; `model_dump(mode="json")` produces the DESIGN §7.3 shape (dates ISO, enums as strings).
- `rules.py` has no I/O and no clock: anything time-related arrives via `facts`/arguments (e.g. `today`).
- mypy strict clean.
- The record must round-trip: `ConversationRecord.model_validate_json(r.model_dump_json()) == r`.

## Acceptance Criteria
- Unit tests cover every knock-out, every review trigger, every flag and the happy path, asserting both status and rule ids.
- Rider-only fields are required only when role is `delivery_rider` (`missing_required()` tests).
- A record built from the DESIGN §7.3 example JSON validates and round-trips unchanged.
- `rules.py` is the only module that constructs a `ScreeningStatus` value outside tests (grep).
- Coverage of `domain/models.py` and `domain/rules.py` ≥ 90 %; mypy strict passes.

## Dependencies & Risks
- Over-modelling the record early; keep optional fields nullable so later specs fill them without migrations (bump `schema_version` only on breaking changes).

## Plan
Write models first from the DESIGN JSON example (use it as a fixture), then rules test-first as a table of cases. Keep rule ids as string constants in `rules.py` so the summary and UI can reference them.

## Tasks
- [x] Add enums and value types to `domain/models.py`
- [x] Add `CandidateProfile` with `missing_required()`
- [x] Add `ConversationRecord` and nested models; fixture from DESIGN §7.3 in `tests/fixtures/record_example.json`
- [x] Write round-trip test
- [x] Implement `domain/rules.py` (`evaluate`, rule id constants) test-first with a parametrised case table
- [x] Run coverage and mypy strict; switch the Makefile `cov` target to `--cov=acme_agent.domain --cov=acme_agent.interview --cov-fail-under=90` now that domain/ has code (SPEC-001 follow-up)
- [x] Fix tests/unit/test_architecture.py so `from .. import storage` (ImportFrom with `module=None`) resolves each imported name (`acme_agent.storage`) and is flagged from domain/; add a test (SPEC-001 review follow-up)

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 12:20 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: d5b0017
- plan/tasks: pre-existing (+2 follow-ups from SPEC-001)

### 2026-10-18 12:23 [anton-team] iteration 1 — T1–T7 domain models, rules, follow-ups (grouped dispatch)
- swe (sonnet): done · commit 7ac12e1 · files: src/acme_agent/domain/models.py, src/acme_agent/domain/rules.py, tests/fixtures/record_example.json, tests/unit/test_models.py, tests/unit/test_rules.py, tests/unit/test_architecture.py, Makefile
- tester (sonnet, full): PASS · `uv run pytest -q` → 53 passed without ADC; `make lint typecheck cov` clean, domain coverage 100 %; every knock-out, review trigger and flag probed directly
- deviations: swe report was empty, results taken from the commit and the tester run; record dump adds defaulted null/empty fields vs. the DESIGN §7.3 fixture (model-level round-trip is exact, no data lost); knock-out + review trigger → `missing_requirements` with both reason lists (as specified)

### 2026-10-18 12:25 [anton-team] review round 1
- reviewer: REVISE · R-006 fail [major] (`reconciliation_conflicts: list[str]` in models.py:168 / rules.py:35 cannot hold SPEC-010's `{slot, live, post_call}` entries → would force a schema_version bump) · minors: `Facts.unresolved_slots` should be `list[SlotName]`, `SlotMeta.status`/`slot_meta` keys untyped, `evaluate` docstring on precedence
- tech-lead: scrubbed a third-party company name from docs/DESIGN.md §7.3 and aligned the example with the code (`review_reasons`, `FLAG_NO_VEHICLE`); added SPEC-005 task to keep one source of truth for required slots

### 2026-10-18 12:26 [anton-team] iteration 2 — review round 1 fixes
- swe (sonnet): fixed findings 1–6 · commit 2a1184c · files: src/acme_agent/domain/models.py (`ReconciliationConflict` with `JsonValue`, typed `SlotMeta.status`, `slot_meta` keyed by `SlotName`), src/acme_agent/domain/rules.py (typed `Facts`, precedence docstring), tests/unit/test_rules.py, tests/unit/test_architecture.py (ADR-009.1 AST guard + negative case)
- tester: PASS (tech-lead re-run) · `uv run pytest -q` → 56 passed without ADC; `make lint typecheck cov` clean, coverage 100 %
- deviations: ADR-009.1 guard matches attribute access on the name `ScreeningStatus` only (aliased imports not caught) — acceptable for the PoC

### 2026-10-18 12:28 [anton-team] review round 2
- reviewer: APPROVE · round-1 findings fixed, nothing new · notes: DESIGN §7.3 events now nested under `payload` (tech-lead); single source for required-slot sets carried to SPEC-005

### 2026-10-18 12:28 [anton-team] implemented
- PR: not opened — project builds directly on `main` (commits d5b0017..HEAD); 56 tests, lint, mypy and coverage 100 % green

### 2026-10-18 12:28 [anton-team] verified (on main, no PR)


### 2026-10-18 14:30 [anton-team] judge
- judge: decisions repointed ADR-004 → ADR-016 (ADR-004 superseded on 2026-10-18; ADR-016.1–016.5 restate ADR-004.1–004.5, with the consent and store hooks added to 016.5 and the read-only goal query as 016.6); verified code already complies — no change to status or evidence
- source: user decision in chat (2026-10-18)

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Unit tests cover every knock-out, every review trigger, every flag and the happy path, asserting both status and rule ids. | test | pass | tests/unit/test_rules.py::test_evaluate (22 parametrised cases) + ::test_escalated_call_reports_escalated_and_incomplete; 56 passed |
| Rider-only fields are required only when role is `delivery_rider` (`missing_required()` tests). | test | pass | tests/unit/test_models.py::test_empty_profile_missing_non_rider_slots, ::test_rider_fields_not_required_for_other_roles, ::test_rider_fields_required_for_rider, ::test_complete_rider_has_nothing_missing |
| A record built from the DESIGN §7.3 example JSON validates and round-trips unchanged. | test | pass | tests/unit/test_models.py::test_fixture_validates_and_round_trips, ::test_dump_matches_fixture_shape |
| `rules.py` is the only module that constructs a `ScreeningStatus` value outside tests (grep). | command + test | pass | grep → member access only in domain/rules.py; tests/unit/test_architecture.py::test_only_rules_module_references_screening_status_members (+ negative case) |
| Coverage of `domain/models.py` and `domain/rules.py` ≥ 90 %; mypy strict passes. | command | pass | `make cov` → 100 %; `make typecheck` → no issues in 21 files |
