---
id: SPEC-018
title: Guaranteed goodbye, consent-decline confirmation and return to the pending question
status: verified
mode: full
origin_type: technical
origin: Candidates must complete a short voice screening interview with Ana: consent first, every required field collected or marked unresolved, corrections, barge-in, ~1-1.5 s responses.
primary_story: null
related_stories: []
created_at: 2026-10-19
updated_at: 2026-10-19
decisions: [ADR-016, ADR-009, ADR-007, ADR-002]
supersedes: []
superseded_by: null
depends_on: [SPEC-008, SPEC-011]
touches: [src/acme_agent/interview/controller.py, src/acme_agent/interview/prompts.py, src/acme_agent/agent/tools.py, src/acme_agent/agent/text.py, src/acme_agent/web/session.py, tests/unit/, tests/web/test_session.py, tests/integration/test_text_mode.py]
parent: null
---

# SPEC-018 — Guaranteed goodbye, consent-decline confirmation and return to the pending question

## Problem & Scope
Three behaviours found in human testing:
1. The call sometimes closes with no last message: the model calls `end_interview` without speaking, and the session ends on that turn's `turn_complete`.
2. A first "no" to consent ends the call at once. The candidate should hear that the interview cannot go on without consent and be asked whether they are sure, before the call ends.
3. After answering a candidate question (FAQ or off-topic) Ana does not always return to the question she was asking.

## Non-goals
- New tools (ADR-016.3: still at most five).
- Changing what is stored on a declined consent (ADR-009.4 purge stays as is).
- Sentiment-based escalation (SPEC-012).

## Functional Requirements
- **Goodbye guarantee.** `end_interview` returns a `say` closing line for its reason (completed → thanks, a person from the hiring team reviews the application and will contact them; declined_consent → nothing was stored, they can contact the hiring team at any time; escalated → a recruiter will contact them; abandoned → short thanks). In the live session, when the phase becomes ENDED and the agent has not spoken since the end, the session sends one `[SYSTEM NOTE]` asking Ana to say the closing line now and closes on the next `turn_complete`, or after a bounded timeout if none comes. Text mode does the same (one re-prompt, then end).
- **Consent-decline confirmation.** A first "no" to consent does not fill the slot or end the call: the controller answers `status: "confirm_decline"` with a `next_goal` telling Ana to explain that without consent the interview cannot continue and to ask whether they want to end the call. A second "no" declines (existing purge + closing goal); a "yes" fills consent and starts collecting. Nothing is stored in between (ADR-009.4). This stays inside the consent hook (ADR-016.5).
- **Return to the pending question.** `search_faq` responses include `next_goal` (the pending question from `controller.next_goal()`, side-effect-free per ADR-016.6) and a short instruction to answer in one or two sentences and then ask it again. The prompt covers off-topic questions: decline politely in one sentence and go back to the pending question.
- Prompt version bumped (`ana-v5`).

## Technical Requirements
- The consent confirmation lives in the documented consent hook; no other per-field branch is added (ADR-016.5). `next_goal()` stays pure.
- The goodbye guard reuses the read-back guard pattern in `web/session.py` (one note per end, never a loop); the timeout is a `Timings` value.
- Closing lines are English steering text for the model to translate (like `next_goal`), not candidate-facing copy in code.

## Acceptance Criteria
- Controller tests: first "no" → `confirm_decline`, consent still empty, phase still consent, nothing stored if the call drops here; second "no" → declined and purged; "no" then "yes" → collecting.
- Session test (fake runner): model ends without speaking → exactly one goodbye `[SYSTEM NOTE]`, the session closes after the next `turn_complete`; model says goodbye then ends → no note; no second turn → session closes after the timeout.
- Tool test: `search_faq` response carries `next_goal` and the resume instruction; `end_interview` returns `say` for every reason.
- Live text-mode test: a "no" to consent gets an "are you sure" style question (no `interview_ended` yet); a second "no" ends with a spoken goodbye. A mid-flow FAQ question is answered and the next agent turn asks the pending question again.
- Manual voice check: completed and declined calls always end with an audible goodbye.

## Dependencies & Risks
- The model may still skip the closing line; the session guard is the safety net.
- A confirmation turn adds one exchange to declined calls; acceptable for clarity.

## Plan
Controller consent confirmation test-first, then tool responses, then the session and text-mode goodbye guard, then the prompt (ana-v5) and the live checks.

## Tasks
- [x] Consent-decline confirmation in the consent hook + tests
- [x] `end_interview` `say` per reason; `search_faq` `next_goal` + resume instruction + tests
- [x] Goodbye guard in the live session and text mode + tests
- [x] Prompt ana-v5 (consent confirmation, goodbye, off-topic and FAQ resume)
- [x] Live text-mode checks and manual voice check

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-19 11:33 [anton-team] started
- origin: human test feedback (2026-10-19) — "send a last message before closing the call", "tell the user that without consent we cannot proceed and ask if they are sure", "if the user asks questions, answer and get back to the questions"
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 8f139e2
- plan: one swe dispatch (controller consent confirmation, tool responses, session + text goodbye guard, prompt ana-v5, live text checks), then tester, reviewer

### 2026-10-19 11:40 [anton-team] iteration 1 — build
- swe (sonnet): done · commit 291fe31 · interview/closing.py (closing lines per reason, goodbye note), consent-decline confirmation in the consent hook (`confirm_decline` status, `_decline_pending`; withdrawal after a yes stays immediate), `end_interview` returns `say`, `search_faq` adds `next_goal` + `then`, goodbye guard in the live session (`Timings.goodbye_s` 8 s, one note) and text mode, prompt ana-v5; existing single-"no" tests and the declined_consent conversation fixture updated to the two-step decline
- tester: tech-lead re-run → 1050 passed · live text mode 4 passed, live audio 1 passed · agent turns: first "no" → explains the interview cannot continue without consent and asks "¿Te gustaría finalizar la llamada?"; second "no" → goodbye "No se ha guardado ninguna información… Puedes contactar al equipo…", declined_consent; mid-flow "¿Dan uniforme?" → FAQ answer then re-asks the role question
- pending: manual voice check (human)

### 2026-10-19 11:45 [anton-team] iteration 2 — review
- reviewer: APPROVE · consent confirmation stays in the consent gate/hook (ADR-016.5), read methods pure (ADR-016.6), nothing stored while pending (ADR-009.4), withdrawal/unresolved/escalation paths intact; 1050 passed, coverage 98.4%
- minors fixed · swe commit ce02c05 · goodbye deadline extends while Ana's audio flows (cap 3× goodbye_s), ordered-frames test (audio before `ended`), user End during the wait closes at once, stale comment, DESIGN / TECHNICAL_DESIGN list `confirm_decline`, `say`, `next_goal`/`then`
- tester: tech-lead re-run → 1052 passed
- status: implemented; verified after the human voice check

### 2026-10-19 12:01 [anton-team] iteration 3 — human request — completed goodbye, unasked rows
- human: on a completed interview Ana should say she has all the information and the team will be in touch; email / languages are never asked, so remove them
- swe (sonnet): done · commit e156bb0 · COMPLETED closing line, CLOSE_GOAL and the read-back follow-up all ask for "you now have all the information… the hiring team will review it and be in touch soon"; panel hides the optional unasked rows (email, languages, experience_summary) unless filled; progress was already required-only
- tester: tech-lead re-run → 1052 passed, static forbidden-words grep clean · live text 4 passed; completed goodbye: "Ya tenemos toda la información que necesitamos. El equipo de contratación de Acme Burgers la revisará y se pondrá en contacto contigo pronto."

### 2026-10-19 12:39 [anton-team] iteration 4 — human request — silence goodbye
- human: after 3 unanswered "are you still there?" Ana should end saying goodbye ("hasta luego")
- swe (sonnet): done · commit a5f6109 · watchdog: up to `silence_checkins` (3) check-ins every `silence_note_s` (20 s), count reset when the candidate speaks or types; then `controller.end(ABANDONED)` + the goodbye guard with the abandoned closing line (ends the call, they can start again, "hasta luego"); a socket that never sent `start` ends silently after the same total
- tester: tech-lead re-run → 1055 passed (fake-runner tests: 3 check-ins → goodbye note → abandoned; speaking after 2 check-ins resets the count)

### 2026-10-19 14:37 [anton-team] human QA — voice check
- human: voice testing across several calls (2026-10-19), issues found were fixed in the follow-ups above; final confirmation "Todo bien"
- status: verified (on main, no PR)

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Controller: first "no" → confirm_decline (consent empty, phase consent, nothing stored on drop); second "no" declines and purges; "no" then "yes" → collecting | test | pass | tests/unit/test_controller_closing.py::test_first_no_asks_for_confirmation, ::test_second_no_declines_and_purges, ::test_no_then_yes_starts_collecting, ::test_drop_while_decline_pending_stores_nothing, ::test_invalid_answer_while_decline_pending_keeps_asking; `uv run pytest -q` → 1052 passed |
| Session: silent end → one goodbye note, close after next turn_complete; spoken goodbye → no note; no second turn → close after timeout | test | pass | tests/web/test_session.py::test_silent_end_sends_one_goodbye_note_and_closes_after_next_turn, ::test_spoken_goodbye_sends_no_note, ::test_silent_end_without_another_turn_closes_after_timeout (+ goodbye audio not cut at the deadline, user End during the wait); text mode: tests/unit/test_text_interview.py::test_silent_end_gets_one_goodbye_reprompt, ::test_spoken_goodbye_does_not_reprompt |
| Tools: search_faq carries next_goal + resume instruction; end_interview returns `say` for every reason | test | pass | tests/unit/test_tools.py::test_search_faq_returns_pending_question_and_resume_instruction, ::test_end_interview_says_a_closing_line_per_reason, ::test_end_interview_ok |
| Live text mode: "no" → confirmation question without ending; second "no" → spoken goodbye; FAQ answer then the pending question again | live test | pass | tests/integration/test_text_mode.py::test_declining_consent_asks_to_confirm_then_ends_with_goodbye, ::test_faq_answer_returns_to_the_pending_question (iteration 1: live text 4 passed, agent turns quoted) |
| Manual voice check: completed and declined calls end with an audible goodbye | manual | pass (human voice QA 2026-10-19) | — |
