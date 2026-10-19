---
id: SPEC-005
title: Interview controller and slot specifications
status: verified
mode: full
origin_type: technical
origin: Candidates must complete a short voice screening interview with Ana: consent first, every required field collected or marked unresolved, corrections, barge-in, ~1-1.5 s responses.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-016, ADR-015, ADR-009, ADR-010, ADR-014]
supersedes: []
superseded_by: null
depends_on: [SPEC-002, SPEC-003]
touches: [src/acme_agent/interview/slots.py, src/acme_agent/interview/controller.py, src/acme_agent/interview/events.py, tests/unit/test_controller.py, tests/conversation/test_scripted_flows.py]
parent: null
---

# SPEC-005 — Interview controller and slot specifications

## Problem & Scope
Implement the deterministic `InterviewController`: data-driven slot specs, phases, next-goal selection, the `record` algorithm with retries and corrections, conditional slot activation, confirmation read-back, escalation and ending — emitting domain events and building the `ConversationRecord`.

Algorithms: TECHNICAL_DESIGN §5.

## Non-goals
- Any LLM, ADK or network code (SPEC-007/008).
- Sentiment scoring itself (SPEC-012) — only the hook to receive frustration signals.
- Returning-candidate lookup (SPEC-015) — only the `prefill` method.

## Functional Requirements
- `SLOTS` in `interview/slots.py`: one `SlotSpec(name, phase, order, required, parser, ask, when=None, risky=False)` per slot in DESIGN §7.1, in phase order consent → role → identity (name, phone, email) → location → availability (availability, weekly hours, start date) → eligibility (right to work, 18+, licence and vehicle if rider) → experience (months, summary, languages).
- `InterviewController(slots, ctx, clock)` with phase `greeting → consent → collecting → confirmation → closing → ended`.
- `record(field, raw) -> ToolResult` implements TECHNICAL_DESIGN §5.4: statuses `ok | invalid | unresolved | not_applicable | unknown_field`; 3 failed attempts → `unresolved`; overwrite → `corrected` + `field_corrected` event; role change activates/deactivates rider slots and clears values that no longer apply.
- Consent: `consent_recording=False` → phase `closing`, `next_goal` asks to say goodbye and call `end_interview(declined_consent)`.
- `next_goal()` per §5.3; when all required active slots are filled/unresolved → phase `confirmation`, goal "Call confirm_profile.".
- `confirm_profile() -> {summary_for_readback}` reads back only `risky` slots (phone, start date, store) plus role, in the interview language marker; after it, corrections return to `collecting`, otherwise the goal is to close.
- `escalate(reason) -> {ticket_id, message_for_candidate}`; `end(reason)`; `on_sentiment(score, frustration)` keeps the last 4 flags and returns a steering note when ≥ 2 are true (ADR-011.2); `on_candidate_text(text)` detects explicit requests for a person ("hablar con una persona", "talk to a human/person/recruiter") and returns the same steering note.
- `prefill(values, source="prefill")` for SPEC-015.
- `snapshot()` returns the UI progress (`progress` 0–1, slot statuses) used by the gateway.
- Every mutation emits an event (`slot_filled`, `validation_failed`, `slot_unresolved`, `field_corrected`, `phase_changed`, `escalated`, `interview_ended`) through an injected `emit` callback and appends to `record.events`.
- `build_record()` returns the current `ConversationRecord` with `candidate`, `slot_meta`, `events`, `end_reason`.

## Technical Requirements
- (ADR-015) `record(field, value, said)`: canonical slots are validated with `CANONICAL[field](value, ctx)`, verbatim slots parsed with `VERBATIM[field](value or said, ctx)`; `said` is stored as `slot_meta.raw` (ADR-015.4); for canonical slots with a `CROSS_CHECKS` entry, the cross-check result on `said` is stored in `slot_meta.cross_check` / `cross_check_agrees` and never affects value, status or goals (ADR-015.5).
- (ADR-015) `invalid` responses for canonical slots include the expected format in `hint`; `next_goal` texts name the canonical format of the slot being asked (e.g. "…then call record_field with value as YYYY-MM-DD").
- (ADR-015) `date_context()` returns the note sent at session start: today's date, weekday and timezone (ADR-015.6).
- Synchronous, no I/O (ADR-004.1): clock and id generator injected; `emit` is a plain callable.
- Only controller methods mutate slot state (ADR-004.2); no `if field == ...` except the documented role/phone hooks (ADR-004.5).
- `ToolResult` is a TypedDict/Pydantic model whose JSON contains `status`, `field`, `normalized`, `hint`, `next_goal`, `missing`, `progress` (ADR-004.4).
- Goals and notes are English instructions for the model; candidate-facing wording is left to the model.
- mypy strict clean.

## Acceptance Criteria
- Unit tests cover: every status of `record`; retry exhaustion; correction; role change to rider and back (licence/vehicle activated then cleared); consent declined path; confirmation and correction after confirmation; escalation; explicit human request; frustration rule (1 flag → nothing, 2 of last 4 → note).
- Scripted conversation tests (`tests/conversation/`) replay tool-call sequences for: happy-path rider (ES values), happy-path crew (EN values), multi-field first sentence, invalid phone twice then valid, store ambiguity resolved, declined consent — each asserting the final record against a JSON fixture.
- Every `record` response has `status`, `next_goal`, `missing` (ADR-004.4).
- Coverage of `interview/` ≥ 90 %; mypy strict; architecture test passes.

## Dependencies & Risks
- Goal text quality directly drives the model's questions; keep goals short and test them indirectly through SPEC-007 text-mode runs and SPEC-014 evals.

## Plan
Define slot specs as data, then build the controller test-first in the order: record/next_goal → phases → conditional slots → confirmation → escalation/sentiment hooks → record building. Add scripted flows last as regression fixtures.

## Tasks
- [x] Write `interview/slots.py` with all `SlotSpec`s and ask texts; take required/rider-only membership from the sets in `domain/models.py` (or add a test that both agree) so there is one source of truth (SPEC-002 review follow-up)
- [x] Implement `ToolResult`, events and `emit` contract in `interview/events.py`
- [x] Implement `record` + `next_goal` with tests
- [x] Implement phases, consent handling and conditional slots with tests
- [x] Implement `confirm_profile`, corrections after confirmation, `escalate`, `end` with tests
- [x] Implement `on_sentiment`, `on_candidate_text`, `prefill`, `snapshot` with tests
- [x] Implement `build_record`
- [x] Add scripted conversation tests and JSON fixtures
- [x] Run coverage, mypy strict, architecture test

- [x] (ADR-015) Route `record` through `CANONICAL`/`VERBATIM`, store `said`, run advisory cross-checks, add `date_context()` + tests (cross-check disagreement leaves value and flow unchanged)

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 13:59 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: ffb1e98
- plan/tasks: pre-existing; tech-lead decisions: (1) phone parser tries the session country then the other supported country and accepts only an unambiguous match; recording the store sets the session country (documented hook, ADR-004.5); (2) SlotSpec carries no parser — slot class and validator come from the ADR-015 registries, required/rider-only sets from domain/models.py

### 2026-10-18 14:08 [anton-team] iteration 1 — part 1 — slots, tool result, controller core, ADR-015 routing
- swe (sonnet): done · commit eda04c2 · files: src/acme_agent/interview/{slots,events,controller}.py, src/acme_agent/domain/validators/identity.py (phone tries session country, then the other supported one), tests/unit/{test_controller,test_slots}.py, tests/unit/test_validators.py
- tester: tech-lead pre-check `uv run pytest -q` → 720 passed; full tester run after part 2
- deviations / accepted calls: unresolved consent (3 failed attempts) treated as declined; optional slots (email, experience_summary, languages) recorded when volunteered, never asked; `missing` keeps unresolved slots, `progress` counts them

### 2026-10-18 14:08 [anton-team] iteration 1 — part 2 — confirmation, escalation, hooks, prefill, snapshot, record, scripted flows
- swe (sonnet): done · commit 8296b21 · files: interview/controller.py, interview/slots.py, domain/models.py (public `ALWAYS_REQUIRED`/`RIDER_REQUIRED`), pyproject.toml + uv.lock (`tzdata`), tests/unit/test_controller_closing.py, tests/conversation/test_scripted_flows.py + 6 fixtures
- tester: pending (covers parts 1–2)
- deviations: `build_record` takes `channel="voice"` (required by the record model); language detection deferred to SPEC-013; tech-lead recorded tzdata in tech-stack.md

### 2026-10-18 14:10 [anton-team] iteration 1 — tester run (parts 1–2)
- tester (sonnet, full): PASS · 763 passed without ADC; `make lint typecheck cov` clean, 99.44 %; every record status, hooks, consent/confirmation/correction/escalation/frustration paths, ADR-015 routing and cross-check advisory behaviour probed directly; 6 fixtures reviewed and correct; full next_goal walk-through clear and format-explicit
- findings routed to swe (minor): `on_candidate_text` false positive "I want to work as a recruiter" and misses ("pásame con un reclutador", "let me speak with a person", "real human"); declined-consent record keeps the candidate's words in `slot_meta.raw` (ADR-009.4: only metadata + consent answer)

### 2026-10-18 14:12 [anton-team] iteration 2 — tester findings
- swe (sonnet): done · commit 7dc3897 · files: interview/controller.py (request-verb + person-noun regex for human requests; declined consent nulls `raw`/cross-check on every slot_meta entry), tests/unit/test_controller_closing.py (7 must-trigger, 6 must-not-trigger, redaction test), tests/conversation/fixtures/declined_consent.json (regenerated, diff checked)
- tester: PASS (tech-lead re-run + check) · `uv run pytest -q` → 777 passed; declined-consent fixture: events carry only field/phase/reason, slot_meta raw/cross_check null

### 2026-10-18 14:16 [anton-team] review round 1
- reviewer: REVISE · [blocker] R-045 ADR-009.4: declined-consent record keeps candidate values/events, and `record` accepts data after a decline; [major] consent no→yes correction leaves phase `closing`, read-back skipped; [major] `escalate` not idempotent (new ticket per call, even after end); [major] `record` mutates the profile after `ended` · minors: second `confirm_profile` message wrong, `progress` unrounded, frustration "one note per streak" not logged · notes: `next_goal()` has side effects (phase changes) — trap for SPEC-007/008; ADR-004.5 text lists only role/phone hooks (consent and store hooks added)
- tech-lead: decisions — data before consent is rejected (not stored; model told to ask consent first); `next_goal()` becomes side-effect-free; deviation recorded: frustration note fires once per frustrated streak (re-armed by a calm turn), not on every turn with ≥ 2 of the last 4 — avoids repeating the same offer every turn; ADR-004.5 hook list to be raised with the human

### 2026-10-18 14:19 [anton-team] iteration 3 — review round 1 fixes
- swe (sonnet): done · commit 90d37ee · files: interview/controller.py (consent gating before/after consent, True→False correction clears other slots and their events, build_record minimal on refusal, no→yes reopens collecting, idempotent `escalate`, end guards on record/confirm/escalate, repeatable `confirm_profile`, explicit `start()`, side-effect-free `next_goal()`, progress rounded), tests/unit/test_controller.py, tests/unit/test_controller_closing.py
- tester: PASS (tech-lead re-run) · `uv run pytest -q` → 787 passed without ADC; `make lint typecheck cov` clean, 99.39 %; fixtures unchanged on regeneration
- accepted call: `prefill` not gated on consent (SPEC-015 prefill happens after the phone, i.e. after consent; `build_record` strips everything if consent is refused) · follow-up added to SPEC-008: persister and final save must write `build_record()` output only

### 2026-10-18 14:24 [anton-team] review round 2
- reviewer: APPROVE · all round-1 findings fixed, no regressions (out-of-order and repeated tool calls, consent yes→no→yes, next_goal purity in every phase) · notes: prefill before consent stayed visible in snapshot after a decline; free-text escalation reason could carry candidate words into a declined record; null ticket after end for SPEC-007; ADR-004.5 hook list (consent/store hooks) is a decision for the human

### 2026-10-18 14:24 [anton-team] iteration 4 — post-review privacy hardening
- swe (sonnet): done · commit 0fd29c3 · files: interview/controller.py (prefill only after consent; any decline purges other slots), interview/events.py (`EscalationReason` closed set; free text → `other`), tests
- tester: PASS (tech-lead re-run + probe) · 791 passed; prefill before consent → []; snapshot after decline shows only consent; free-text reason stored as `other`
- deviations: swe report was empty; verified from the commit and probes · follow-up added to SPEC-007 (start(), escalation reasons, null ticket)

### 2026-10-18 14:24 [anton-team] implemented
- PR: not opened — project builds directly on `main` (commits ffb1e98..HEAD); 791 tests, lint, mypy and coverage 99.46 % green

### 2026-10-18 14:24 [anton-team] verified (on main, no PR)


### 2026-10-18 14:30 [anton-team] judge
- judge: decisions repointed ADR-004 → ADR-016 (ADR-004 superseded on 2026-10-18; ADR-016.1–016.5 restate ADR-004.1–004.5, with the consent and store hooks added to 016.5 and the read-only goal query as 016.6); verified code already complies — no change to status or evidence
- source: user decision in chat (2026-10-18)

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Unit tests cover: every status of `record`; retry exhaustion; correction; role change to rider and back (licence/vehicle activated then cleared); consent declined path; confirmation and correction after confirmation; escalation; explicit human request; frustration rule (1 flag → nothing, 2 of last 4 → note). | test + reviewer probe | pass | tests/unit/test_controller.py, tests/unit/test_controller_closing.py; 791 passed; reviewer probes round 2 (probe_r2.py, probe_r2b.py) |
| Scripted conversation tests (`tests/conversation/`) replay tool-call sequences for: happy-path rider (ES values), happy-path crew (EN values), multi-field first sentence, invalid phone twice then valid, store ambiguity resolved, declined consent — each asserting the final record against a JSON fixture. | test | pass | tests/conversation/test_scripted_flows.py + 6 fixtures (reviewed by tester and reviewer) |
| Every `record` response has `status`, `next_goal`, `missing` (ADR-004.4). | test + code read | pass | single `_result()` constructor in interview/controller.py; ::test_every_response_has_status_goal_and_missing |
| Coverage of `interview/` ≥ 90 %; mypy strict; architecture test passes. | command | pass | `make lint typecheck cov` → 99.46 %, mypy no issues in 47 files, architecture test green |
