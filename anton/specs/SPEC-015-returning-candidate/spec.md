---
id: SPEC-015
title: Returning candidate continues an unfinished interview
status: ready
mode: full
origin_type: technical
origin: Candidates whose interview was cut off should continue where they left off instead of starting over.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-016, ADR-006, ADR-009]
supersedes: []
superseded_by: null
depends_on: [SPEC-005, SPEC-006, SPEC-007]
touches: [src/acme_agent/interview/controller.py, src/acme_agent/agent/tools.py, src/acme_agent/bootstrap.py, tests/unit/test_returning_candidate.py]
parent: null
---

# SPEC-015 — Returning candidate continues an unfinished interview

## Problem & Scope
When a valid phone is recorded and an unfinished (abandoned) record with that phone exists within the retention window, pre-fill the slots from it, tell the model to confirm instead of re-asking, and link the new record to the previous one.

## Non-goals
- Identity verification beyond phone match.
- Merging completed interviews or deduplicating across stores.

## Functional Requirements
- After `record_field(phone)` returns `ok`, the tool layer calls `repository.find_unfinished_by_phone`; on a hit, `controller.prefill(values, source="prefill")` sets only slots that are still empty, and the tool response includes `returning_candidate: true` and a `next_goal` asking Ana to confirm the pre-filled details in one turn.
- Pre-filled slots can be corrected like any other slot.
- `record.previous_conversation_id` is set; event `returning_candidate_detected`.
- Consent is never pre-filled (always asked in the new call).

## Technical Requirements
- Lookup is async and happens in the tool layer, not in the controller (ADR-016.1); it must finish within 200 ms or be skipped (timeout) to protect the hot path.
- Only records younger than `ACME_RETENTION_DAYS` are considered.

## Acceptance Criteria
- Unit tests: hit pre-fills empty slots only; consent not pre-filled; completed records ignored; timeout skips lookup; correction of a pre-filled slot works.
- Text-mode manual run: abandon an interview after the store question, start again, give the same phone, Ana confirms instead of re-asking; new record links to the old id (Verification).

## Dependencies & Risks
- Phone typos create false negatives — acceptable; a false positive requires an identical valid phone.

## Plan
Controller `prefill` behaviour tests first (method exists from SPEC-005), then the tool-layer lookup with timeout, then the manual run.

## Tasks
- [ ] Extend `record_field` tool path with lookup + timeout
- [ ] Ensure `prefill` semantics (empty only, no consent) + tests
- [ ] Set `previous_conversation_id` and event
- [ ] Manual returning-candidate run

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
