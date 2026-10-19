---
id: SPEC-012
title: Sentiment monitor and escalation to a recruiter
status: verified
mode: full
origin_type: technical
origin: Frustrated candidates, or those asking for a person, must be offered a recruiter instead of being pushed through the interview.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-016, ADR-008, ADR-011, ADR-014]
supersedes: []
superseded_by: null
depends_on: [SPEC-008]
touches: [src/acme_agent/analysis/sentiment.py, src/acme_agent/web/session.py, src/acme_agent/agent/text.py, tests/unit/test_sentiment.py, tests/web/test_session_sentiment.py]
parent: null
---

# SPEC-012 — Sentiment monitor and escalation to a recruiter

## Problem & Scope
Score each final candidate turn for frustration in the background, attach scores to the transcript, feed the controller's escalation rule, steer Ana to offer a recruiter when the rule fires, and aggregate sentiment in the record. Works in live and text modes.

## Non-goals
- Using audio prosody.
- Changing Ana's voice or tone directly (affective dialog stays a model feature).

## Functional Requirements
- `SentimentMonitor(client, settings)` with `submit(turn_index, last_turns)`; output schema `{score: -1..1, frustration: bool, reason: str}` via structured output with `settings.sentiment_model`.
- At most one call in flight per session; a newer turn replaces a queued one; 3 s timeout; failures are logged and ignored (ADR-011.1).
- Results update `transcript[turn].sentiment` and call `controller.on_sentiment`; a returned steering note is sent to the model (`[SYSTEM NOTE] The candidate seems frustrated. Offer a recruiter callback or to continue later.`).
- `controller.on_candidate_text` explicit-request detection is called on every final candidate turn (no model call).
- Escalation accepted → `escalate_to_human` → end `escalated` → status `needs_human_review` (rules).
- Record `sentiment`: avg, min, frustration_events, trend (`improving|stable|worsening` from first vs last third).

## Technical Requirements
- Runs as an asyncio task owned by the session; never awaited by tool handlers or audio forwarding (ADR-011.1).
- Text mode: monitor runs between turns; steering note injected before the next model turn.
- Tests with a fake slow client (2 s) assert tool responses and audio forwarding are not delayed.

## Acceptance Criteria
- Unit tests: trend computation, replacement of queued requests, timeout handling, note emitted on the second frustration flag within four turns.
- Session test with fake runner + slow fake sentiment client: tool results are forwarded without waiting for sentiment.
- Text-mode manual run with an angry scripted candidate leads to the recruiter offer and an `escalated` record with `needs_human_review` (Verification).
- Record contains per-turn scores and the aggregate.

## Dependencies & Risks
- False positives on terse but calm candidates; require two flags and keep the threshold conservative.

## Plan
Monitor with fake client test-first, then session integration, then text-mode integration, then aggregate in the record.

## Tasks
- [x] Implement `analysis/sentiment.py` (monitor, schema, trend) + tests
- [x] Integrate with `InterviewSession` (task, steering) + session test
- [x] Integrate with `TextInterview`
- [x] Write sentiment aggregate into the record
- [ ] Manual escalation run in text and voice

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-19 12:57 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 82ead4a
- plan: one swe dispatch (monitor + schema + trend, session task + steering, text mode, record aggregate, live text escalation run), then tester, reviewer
- tech-lead notes: sentiment model calls only after consent is a clear yes (data minimisation, ADR-009; explicit "talk to a person" detection needs no model call and works before consent); the frustration note reuses the steering path and must not collide with the read-back / goodbye guards; on a declined consent no sentiment is stored (build_record redaction)

### 2026-10-19 13:03 [anton-team] iteration 1 — build
- swe (sonnet): done · commit 5006da3 · analysis/sentiment.py (`SentimentMonitor`: one in flight, newer replaces queued, 3 s timeout, failures ignored and logged by type only), domain/sentiment.py (pure `aggregate`, trend threshold 0.15), `controller.consented`, build_record stores the aggregate only with consent, session-owned monitor (submit after consent; note suppressed while closing / ended / goodbye guard / read-back pending), text mode bounded wait, setting `ACME_SENTIMENT` (off in test fixtures)
- tester: tech-lead re-run → 1081 passed · live angry candidate (text): scores −1.0 ("pérdida de tiempo"), −0.8 ("qué pesado"); offer "Puedo organizar que un reclutador se ponga en contacto contigo… ¿Te gustaría que lo hiciera?"; after "sí" → escalated, needs_human_review; aggregate avg −0.77, min −1.0, frustration_events 3, trend improving
- deviations: `aggregate` in domain (ADR-016.1 import boundary); `frustration_events` passed from the controller; monitor `on_result` / `wait_idle` additions; the consent turn itself is unscored (consent is recorded after it is submitted)
- pending: voice escalation run (human)

### 2026-10-19 13:18 [anton-team] iteration 2 — review round 1 fixes + live robustness
- reviewer (round 1): REVISE · [major] ACME_SENTIMENT undocumented · [major] ADR-011.2 a note suppressed during read-back / closing consumed the once-per-streak rule · minors: callable() client sniffing, constructor wiring untested; note: the log's start commit is the base commit before "SPEC-012: start" (050f5f7), as in earlier specs
- swe (sonnet): done · commit 5a1d00a · .env.example + DESIGN env block; "not now" moved into `controller.on_sentiment` (no arming while read-back pending / closing / ended; the next flag still offers); explicit `client_provider`; constructor-wiring and suppression tests
- tech-lead probe (live, 2 runs): offers and acceptance correct; one run the model escalated but never called end_interview → record `abandoned` · one live test run had the call over before acceptance
- swe (sonnet): done · commit 94c4123 · `controller.end()`: ABANDONED after escalation is recorded ESCALATED (covers close, session end, user End, watchdog); escalate_to_human only after explicit acceptance / request, never in the offer turn; prompt ana-v6; live test checks the offer across both replies
- tester: tech-lead re-run → 1089 passed · live angry-candidate test: swe 7/8, tech-lead 4/4 → 11/12 (one unanalysed failure, LLM-dependent)

### 2026-10-19 13:20 [anton-team] iteration 3 — review round 2
- reviewer (round 2): APPROVE · both round-1 majors fixed; `controller.end()` escalated rule respects ADR-016.6 / ADR-009.1; 1089 passed, coverage 98%
- tech-lead decision: a session failure after an escalation persists `escalated` (the callback still has to happen; the failure is logged) → ADR-003.3 and rubric R-021 wording amended ("abandoned, or escalated when a callback was already promised")
- notes: `frustration_events` counts flagged turns (not offers); trend compares first vs last third, so a short angry call that ends with acceptance can read "improving"; the live angry test is LLM-dependent (11/12) — candidate for a pass-rate eval in SPEC-014
- open task: voice escalation run (human) — not an acceptance criterion
- status: verified (on main, no PR)

### 2026-10-19 13:38 [anton-team] follow-up — human test — unclear classification
- human: complained twice, was offered a recruiter, said "terminemos ya"; the recruiter panel classification was unclear (record c_01M5APTWP22T2XNX6H4Y4G5YJH)
- findings (tech-lead): end_reason `escalated` without an escalation (model passed the reason); reasons showed only unresolved slots / incomplete call, nothing about frustration or the declined offer; the tone aggregate was stored but not shown; ambiguous consent ("No estoy de acuerdo, pero vale") recorded as yes
- swe (sonnet): done · commit 4ae698f · `controller.end()`: ESCALATED only when escalated (else ABANDONED, `requested_reason` in the event); rules flags FLAG_FRUSTRATION (≥ 2 frustration events) and FLAG_RECRUITER_DECLINED (offer made, ended without escalation); consent only on a clear unconditional yes, otherwise a direct "¿…? Sí o no." (prompt ana-v7, CONFIRM_DECLINE_GOAL); `completed` frame carries `end_reason` + `sentiment`; recruiter panel shows end reason and tone in plain language
- tester: tech-lead re-run → 1094 passed · live ambiguous-consent test 3/3

### 2026-10-19 14:07 [anton-team] follow-up — human — callback promised without a phone
- human: Ana promised a recruiter callback without having the phone number
- swe (sonnet): done · commit e32fbda · escalation with consent and no phone → next_goal asks for the phone first (record still accepts phone after escalation; unresolved after MAX_ATTEMPTS → goodbye); escalation before consent → no phone, point to the hiring-team contact via search_faq; `closing_line(reason, has_phone, consented)` promises a call only with a phone; prompt ana-v8 "never promise contact unless the tool response says so"
- tester: tech-lead re-run → 1101 passed · live escalation-with-phone test 3/3 ("…¿podrías darme tu número de teléfono?" → "Un reclutador te llamará al número que me has proporcionado.") · ~1 in 3 runs the model skips end_interview after the phone; `end()` still records escalated

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Unit tests: trend, replacement of queued requests, timeout handling, note on the second frustration flag within four turns | test | pass | `uv run pytest -q` → 1089 passed; tests/unit/test_sentiment.py::test_aggregate_trend, ::test_newer_submit_replaces_a_queued_one, ::test_never_more_than_one_call_in_flight, ::test_timeout_is_logged_and_ignored_then_next_submit_works, ::test_close_cancels_in_flight_and_drops_queued, ::test_note_only_on_second_flag_within_four_turns; tests/unit/test_controller_closing.py streak + suppression tests |
| Session test with fake runner + slow fake sentiment client: tool results forwarded without waiting | test | pass | tests/web/test_session_sentiment.py::test_slow_scoring_never_delays_tools_or_audio (2 s fake; tools and audio < 0.5 s) |
| Text-mode run with an angry scripted candidate → recruiter offer, `escalated` record, `needs_human_review` | live test | pass | tests/integration/test_text_mode.py::test_angry_candidate_is_offered_a_recruiter_and_escalated — 11/12 runs (iteration 2); scores −1.0 / −0.8, offer quoted in iteration 1 |
| Record contains per-turn scores and the aggregate | test | pass | test_second_flag_within_four_turns_emits_exactly_one_note, test_note_is_injected_on_the_second_flag_and_scores_are_stored, test_record_carries_scores_and_aggregate_with_consent, test_declined_consent_stores_no_sentiment |
