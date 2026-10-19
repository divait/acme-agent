---
id: SPEC-010
title: Post-call extraction, reconciliation, summary and metrics
status: verified
mode: full
origin_type: technical
origin: Recruiters need a validated JSON candidate record with transcript, summary and a routing status with reasons; a human always decides.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-002, ADR-015, ADR-006, ADR-008, ADR-009, ADR-014]
supersedes: []
superseded_by: null
depends_on: [SPEC-007]
touches: [src/acme_agent/analysis/post_call.py, src/acme_agent/interview/controller.py, src/acme_agent/web/session.py, src/acme_agent/web/static/app.js, src/acme_agent/web/static/index.html, src/acme_agent/analysis/schemas.py, src/acme_agent/bootstrap.py, src/acme_agent/cli.py, tests/unit/test_post_call.py, tests/unit/test_reconciliation.py]
parent: null
---

# SPEC-010 — Post-call extraction, reconciliation, summary and metrics

## Problem & Scope
Turn a finished interview into the final record: re-extract raw values from the full transcript with Gemini Flash structured output, normalise them with the same parsers, reconcile with live slots, compute the screening status with `domain/rules.py`, generate a structured English summary, aggregate metrics, and persist. Plugs in as the `SessionFinalizer` for both text and live sessions. Adds `acme-agent stats`.

Pipeline: TECHNICAL_DESIGN §8.

## Non-goals
- Re-confirming post-call values with the candidate.
- Recruiter UI.

## Functional Requirements
- `PostCallFinalizer(genai_client, settings, repository)` implements `SessionFinalizer`; selected by default in `bootstrap.py`.
- Extraction: prompt + `response_schema=ExtractionResult` (per slot: `raw` value or null, `turn` it came from); temperature 0.
- Every extracted raw value goes through `PARSERS` (ADR-008.1).
- Reconciliation per slot (ADR-008.2): agree → keep; live empty and post valid → fill with `source: post_call`; disagree → keep live, add `{slot, live, post_call}` to `reconciliation_conflicts`; both empty → missing. Applied through `InterviewController.apply_reconciliation`.
- Status from `rules.evaluate` with facts from the controller (ADR-009.1).
- Summary: `response_schema=Summary` (`headline` ≤ 140 chars, `key_points` 3–6, `candidate_questions`, `recruiter_next_steps`), English, temperature 0.3; prompt includes profile, status reasons and missed FAQ questions.
- Declined consent: skip extraction and summary entirely; store the minimal record (ADR-009.4).
- Failures: 30 s timeout per call, 2 retries with exponential back-off; on final failure keep live data, `summary: null`, status `needs_human_review`, event `post_call_failed` (ADR-008.4).
- Metrics added to `record.metrics`: duration, turns, tool calls, tool errors, invalid attempts per slot, FAQ hits/misses, post-call fills, conflicts.
- `acme-agent stats` aggregates stored records: count, completion rate, status distribution, median duration, most-failed slots, post-call fill rate.

## Technical Requirements
- `summary.candidate_questions` is derived from the `faq_missed` events (payload `question`) recorded by `controller.note_faq` (moved here from SPEC-007); the summary prompt receives them.
- (ADR-015.8) `ExtractionResult` asks, per slot, for the canonical value (canonical slots) or the candidate's words (verbatim slots) plus the quoted words and turn; values go through the same `CANONICAL` / `VERBATIM` registries before reconciliation.
- Structured output only, no regex/`json.loads` on free text (ADR-008.3); schemas in `analysis/schemas.py`.
- `google-genai` async client (`client.aio.models.generate_content`) with model `settings.text_model`.
- Runs as a background task after the live part ends; the session sends `completed` when done if the socket is still open.
- Unit tests use a fake client returning canned structured responses; one `live`-marked test runs extraction + summary on a fixture transcript.

## Acceptance Criteria
- Reconciliation unit tests cover the four cases and assert sources and conflicts.
- An extracted invalid phone is not stored and does not create a conflict (test).
- A fake failing client yields a saved record with `summary: null` and `needs_human_review` (test).
- Declined-consent sessions make no model calls (test with a spy client).
- `pytest -m live tests/unit/test_post_call.py::test_live_fixture` produces a valid summary for the fixture transcript.
- `acme-agent stats` prints the aggregate on a temp data dir with fixture records (CLI test).

## Dependencies & Risks
- Extraction hallucinating values not in the transcript: require `turn` references and drop values whose turn text does not contain any token of the raw value (cheap grounding check).

## Plan
Schemas first, then reconciliation as a pure function (test-first), then the finalizer with a fake client, then summary, then the stats CLI, then wire into `bootstrap.py` and run end-to-end in text mode.

## Tasks
- [x] Define `ExtractionResult` and `Summary` schemas
- [x] Implement pure `reconcile(live, extracted, parsers, ctx)` + tests
- [x] Add `InterviewController.apply_reconciliation` (coordinate with SPEC-005 code) + tests
- [x] Implement extraction call with grounding check, retries and timeouts
- [x] Implement summary call
- [x] Implement metrics aggregation into the record
- [x] Implement `PostCallFinalizer` and select it in `bootstrap.py`
- [x] Implement `acme-agent stats` + CLI test
- [x] Add live-marked fixture test

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 17:56 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 34bc269
- plan: dispatch 1 — schemas, pure `reconcile`, `InterviewController.apply_reconciliation`, extraction (grounding via `said` + `said_in_transcript`), summary, retries/timeouts, metrics, `PostCallFinalizer` selected in bootstrap, consent-refusal short-circuit; dispatch 2 — `acme-agent stats`, live fixture test, client shows the English recruiter summary only in the demo recruiter panel; then tester, reviewer
- carried over from SPEC-009 review: the summary is recruiter-facing (English, may mention status reasons) → the candidate view never shows headline/key points; they render inside "Demo: recruiter view" (touches extended: web/static/app.js, index.html; also interview/controller.py, web/session.py)
- registries: ADR-015.8 supersedes the "PARSERS" wording in the Functional Requirements — use `CANONICAL` / `VERBATIM`

### 2026-10-18 18:02 [anton-team] iteration 1 — part 1 — post-call core
- swe (sonnet): done · commits 204e450, 21495c2 · analysis/{schemas,reconcile,post_call}.py, `InterviewController.apply_reconciliation` + `note_post_call_failed`, `PostCallFinalizer` default in bootstrap (lazy client; `ACME_POST_CALL=off` → SaveOnlyFinalizer, used by the test settings fixture), `completed` frame carries summary + status · tests: test_reconciliation (17), test_post_call (15)
- tester: tech-lead re-run → 996 passed
- deviations: post-call failure status via a new deterministic rule (`Facts.post_call_failed` → reason REVIEW_POST_CALL_FAILED) so `rules.evaluate` stays the only status source (ADR-009.1/.2); extraction failure skips the summary call; grounding needs a non-empty `said`, checked per candidate turn; strict Summary schema (over-long headline = failed attempt, retried)
- problem → part 2: `ended` is now sent only after post-call finishes (up to minutes on failure), so the client sits in "live" — must send `ended` as soon as the live part ends, run post-call, then `completed` (spec: "runs as a background task after the live part ends")
- pre-existing: mypy on tests/web/test_static.py:28 unused type: ignore

### 2026-10-18 18:09 [anton-team] iteration 2 — part 2 — order, stats, live test, client
- swe (sonnet): done · commit a2f95dc · session sends error → ended → (post-call) → completed; `CompletedMessage.reasons` (rule ids) added; `acme-agent stats [--json]` via repository (`compute_stats`, fill rate = share of records with post_call_fills > 0); live fixture test; recruiter summary only inside "Demo: recruiter view"; mypy tests clean
- tester: tech-lead re-run → 1000 passed · live `test_live_fixture` → 1 passed (10.9 s; 4 fills, 1 weekly_hours conflict 15 vs 25, needs_human_review, valid summary) · browser (Chromium, served, real Gemini, typed answers, End after 3 turns): "Processing…" right after End, summary ~10 s later; candidate view neutral line only; recruiter panel: neutral pill "Needs human review", headline, 5 key points, next steps · stored record: post_call "ok", screening review_reasons [REVIEW_UNRESOLVED_SLOTS, REVIEW_INCOMPLETE_CALL], median turn latency 2072 ms
- findings: [minor] recruiter panel shows raw rule ids as reasons ("REVIEW_UNRESOLVED_SLOTS") — needs readable labels

### 2026-10-18 18:16 [anton-team] iteration 3 — review round 1 fixes
- reviewer (round 1): REVISE · [major] R-041/ADR-008.4 knock-out + post-call failure gave missing_requirements instead of needs_human_review · [major] text-mode records lacked duration/turn/tool metrics · minors: premature "answers saved" error text, §2 `completed` lacked `reasons`, dead branch in reconcile, verbatim value not grounded (only `said`), store reconciled after phone (country), raw rule ids in recruiter panel, mixed-language panel headings; notes: additive event type without schema bump
- swe (sonnet): done · commit e71ad0b · post_call_failed forces needs_human_review (knock-outs still listed); text mode passes the session metric keys + `_derived()` fallback in post-call; "We are saving your answers so far."; §2 updated; verbatim value grounding (digits / email parts / tokens); role → store → rest order; readable en/es rule labels; `schema_version` 1.1 (1.0 still loads, ADR-006.3)
- tester: tech-lead re-run → 1007 passed; live `test_live_fixture` → 1 passed (15.8 s); `node --check app.js` ok

### 2026-10-18 18:18 [anton-team] iteration 4 — review round 2
- reviewer (round 2): APPROVE · all 7 round-1 findings fixed and tested; 1007 passed, ruff/mypy clean
- follow-ups (minor, not blocking): `reconcile._with_store_country` repeats the controller's country list (shared domain helper); app.js rule labels repeat the 30-day / 15-hour thresholds (drop numbers or send labels from the server); post-call failure now outranks a knock-out per ADR-008.4 (amend the ADR if knock-outs should win); "Demo: recruiter view" in the candidate client is demo-only — revisit before any real deployment (SPEC-016)
- status: verified (on main, no PR)

### 2026-10-19 14:16 [anton-team] follow-up — human — false 'live and post-call answers differ'
- human: REVIEW_CONFLICT ("Respuestas en vivo y posteriores no coinciden") on almost every call; stored conflicts: "Daniel Perez" vs "Daniel Pérez", two phrasings of experience_summary, "Diego" vs "Thiago" (name confirmed by the candidate)
- swe (sonnet): commit 1d63609 · free-text slots never conflict; text compared normalised (casefold, accents, punctuation, spaces), emails casefolded; `ReconciliationConflict.confirmed_by_candidate` — conflicts on read-back-confirmed slots are informational and don't raise REVIEW_CONFLICT; schema_version 1.2 (1.0 / 1.1 load) · commit fccdeb2 (SPEC-007) · the name is now part of the read-back (FULL_NAME risky), so "confirmed" is true
- tester: tech-lead re-run → 1113 passed; live read-back test passed

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Reconciliation unit tests cover the four cases and assert sources and conflicts | test | pass | tests/unit/test_reconciliation.py::test_agree_keeps_live, ::test_live_empty_post_valid_fills, ::test_disagree_keeps_live_and_reports_conflict, ::test_both_empty_stays_missing, ::test_apply_fills_with_post_call_source_and_keeps_conflicts, ::test_apply_never_overwrites_a_filled_slot; `uv run pytest -q` → 1007 passed |
| An extracted invalid phone is not stored and does not create a conflict | test | pass | tests/unit/test_reconciliation.py::test_invalid_phone_is_dropped_without_conflict; tests/unit/test_post_call.py::test_happy_path_fills_conflict_summary_saved |
| A fake failing client yields a saved record with summary null and needs_human_review | test | pass | tests/unit/test_post_call.py::test_failing_client_saves_live_data_without_summary, ::test_failed_post_call_with_knockout_needs_review, ::test_timeouts_are_retried_then_fail, ::test_summary_failure_keeps_reconciled_data; tests/unit/test_rules.py case post_call_failed_beats_knockout |
| Declined-consent sessions make no model calls | test (spy client) | pass | tests/unit/test_post_call.py::test_declined_consent_makes_no_model_calls, ::test_no_consent_answer_makes_no_model_calls |
| `pytest -m live tests/unit/test_post_call.py::test_live_fixture` produces a valid summary | live test | pass | iteration 2: 1 passed (10.9 s; 4 fills, weekly_hours conflict 15 vs 25, needs_human_review, headline ≤ 140, 3–6 key points); iteration 3 re-run: 1 passed (15.8 s) |
| `acme-agent stats` prints the aggregate on a temp data dir with fixture records | CLI test | pass | tests/unit/test_stats_cli.py::test_stats_json, ::test_stats_text_and_empty |
