---
id: SPEC-007
title: Agent tools, system prompt v1 and text-mode chat
status: verified
mode: full
origin_type: technical
origin: Candidates must complete a short voice screening interview with Ana: consent first, every required field collected or marked unresolved, corrections, barge-in, ~1-1.5 s responses.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-002, ADR-003, ADR-016, ADR-007, ADR-009, ADR-010, ADR-014, ADR-015]
supersedes: []
superseded_by: null
depends_on: [SPEC-005, SPEC-006]
touches: [src/acme_agent/agent/tools.py, src/acme_agent/interview/prompts.py, src/acme_agent/agent/text.py, src/acme_agent/bootstrap.py, src/acme_agent/cli.py, tests/unit/test_tools.py, tests/unit/test_prompts.py, tests/integration/test_text_mode.py, src/acme_agent/domain/validators/location.py, src/acme_agent/agent/models.py, src/acme_agent/interview/readback.py]
parent: null
---

# SPEC-007 — Agent tools, system prompt v1 and text-mode chat

## Problem & Scope
Expose the controller to an LLM: the five tools, the versioned system instruction (TECHNICAL_DESIGN §7), a composition root that wires settings, repository, retriever and session finalizer, and a text-mode agent (`acme-agent chat`) that runs a full interview by typing with a Gemini text model through ADK. This is the first end-to-end demoable slice and the target of later evals.

## Non-goals
- Audio, WebSockets, browser (SPEC-008/009).
- Real FAQ retrieval (SPEC-011) — `search_faq` uses a `NullRetriever` returning `found: false` until then.
- Post-call processing (SPEC-010) — the finalizer here only saves the record.

## Functional Requirements
- `build_tools(controller, retriever) -> list[Callable]` returns `record_field`, `search_faq`, `confirm_profile`, `escalate_to_human`, `end_interview` with the docstrings from TECHNICAL_DESIGN §4 (they are the tool descriptions); each returns a JSON-serialisable dict.
- `search_faq` records a `faq_answered` or `faq_missed` event (with `source` when found) and adds missed questions to `candidate_questions` metadata.
- `prompts.SYSTEM_INSTRUCTION` and `PROMPT_VERSION = "ana-v1"` with persona, goal, tool contract, `[SYSTEM NOTE]` convention, boundaries (protected characteristics), start instructions and three few-shot snippets (multi-field sentence, correction, mid-flow question).
- `bootstrap.py`: `AppContainer` built from `Settings` with `repository`, `retriever`, `parse_context_factory`, `finalizer` (`SessionFinalizer` protocol: `async finalize(controller, transcript) -> ConversationRecord`; default `SaveOnlyFinalizer`), `genai_client`.
- `TextInterview` (agent/text.py): ADK `Agent` with `settings.text_model`, same instruction and tools, `Runner.run_async` per typed turn; keeps the transcript (agent/candidate turns with timestamps); exposes `start()`, `send(text) -> str`, `close(reason)`; on close calls the finalizer.
- `acme-agent chat [--lang es|en]` runs an interactive console interview: prints Ana's turns, reads candidate input, shows a compact progress line (`[6/14 slots] phone ✓ store ?`), saves the record and prints its id and status at the end; `/quit` ends as `abandoned`.
- `[SYSTEM NOTE]` steering notes returned by the controller (sentiment, human request) are injected before the next model turn.

## Technical Requirements
- Controller contract from SPEC-005: call `controller.start()` before the first model turn (it moves greeting→consent; `next_goal()` is side-effect-free); `escalate_to_human(reason)` documents the closed set `candidate_request | frustration | technical_issue | other` and the tool handles `ticket_id: None` (escalation after the interview ended).
- (ADR-015) Tool signature `record_field(field: str, value: str, said: str)`; the docstring lists the canonical format of every canonical slot and says verbatim slots (name, phone, email, store) take the candidate's words in `value`.
- (ADR-015) The session (text and live) sends `controller.date_context()` as a `[SYSTEM NOTE]` before the greeting; the system instruction tells the model to resolve relative expressions ("el lunes que viene", "in two weeks", "weekday mornings", "two and a half years") itself and to pass only canonical values.
- Tools close over one controller (ADR-003.2); no globals. `len(build_tools(...)) == 5` (ADR-016.3).
- Tool functions are synchronous and fast (< 20 ms, no network) except `search_faq`, which awaits the retriever (in-memory once SPEC-011 lands).
- The text agent and the future live agent share `build_tools` and `SYSTEM_INSTRUCTION` (ADR-010.3); `text.py` must not duplicate flow logic.
- Prompt tests assert the boundary text exists, the prompt contains no FAQ content (ADR-007.1) and no model ids, and stays under 1 200 words.
- `tests/integration/test_text_mode.py` is marked `live` (real Gemini) and runs one scripted candidate (fixed inputs) asserting the record reaches `completed` with ≥ 12 filled slots.
- Unit tests drive `TextInterview` with a fake ADK model or by calling tools directly to avoid network.

## Acceptance Criteria
- `acme-agent chat` completes a full interview in English and in Spanish with a real Gemini model (manual check, noted in Verification) and saves a record whose status is computed by rules.
- Unit tests: each tool's output shape; `search_faq` with `NullRetriever` returns `found: false` and logs `faq_missed`; tool count and names; prompt assertions.
- `pytest -m live tests/integration/test_text_mode.py` passes with credentials.
- The saved record contains `model.text`, `model.prompt_version` = the current `PROMPT_VERSION` (`ana-v3` at verification), transcript and events.

## Dependencies & Risks
- ADK text-mode API details may differ from the sketch; fall back to `google-genai` chat with automatic function calling inside `text.py` if ADK is awkward (shared tools remain).
- Prompt quality: iterate in text mode before voice; bump `PROMPT_VERSION` on each change.

## Plan
Write tools as thin adapters over the controller first (unit-tested without any model), then the prompt with its tests, then the composition root, then `TextInterview` with a fake model, then the CLI loop; finish with a live integration run and prompt iteration.

## Tasks
- [x] Implement `build_tools` and tool docstrings + unit tests
- [x] Implement `NullRetriever` and the `Retriever` protocol import point
- [x] Write `interview/prompts.py` (`SYSTEM_INSTRUCTION`, few-shots, `PROMPT_VERSION`) + prompt tests
- [x] Implement `bootstrap.py` (`AppContainer`, `SessionFinalizer`, `SaveOnlyFinalizer`)
- [x] Implement `TextInterview` with ADK text model and transcript capture
- [x] Implement `acme-agent chat` with progress line and `/quit`
- [x] Add live-marked integration test
- [x] Iterate prompt with ES and EN manual runs; record results

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 14:39 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 8fc2274
- plan/tasks: pre-existing; tech-lead decisions: (1) `Retriever` protocol + `NullRetriever` in knowledge/retriever.py (ADR-007.4); (2) FAQ bookkeeping via a controller method `note_faq()` emitting faq_answered/faq_missed events (ADR-016.2), candidate questions derived from events in SPEC-010; (3) `build_record()` stays transcript-free — `SaveOnlyFinalizer` attaches the transcript and saves; (4) offline parts first, live integration test and manual ES/EN runs wait for the user's GCP project

### 2026-10-18 14:45 [anton-team] iteration 1 — part 1 — tools, retriever protocol, prompt v1, composition root
- swe (sonnet): done · commit 21b101f · files: agent/tools.py, knowledge/retriever.py, interview/prompts.py, bootstrap.py, interview/controller.py (`note_faq`), interview/events.py, tests/unit/{test_tools,test_prompts,test_bootstrap}.py, tests/unit/test_controller.py
- tester: tech-lead pre-check → 816 passed; full tester run after part 2
- deviations: mid-flow few-shot uses "dress code" (a "uniform" example collided with a FAQ title — ADR-007.1); knowledge dir resolved relative to the checkout (packaging note for SPEC-016)

### 2026-10-18 14:45 [anton-team] iteration 1 — part 2 — TextInterview over ADK, acme-agent chat, live test
- swe (sonnet): done · commit 162444f · files: agent/text.py, cli.py (`chat`, progress line), Makefile, tests/unit/test_text_interview.py (scripted fake `BaseLlm`), tests/integration/test_text_mode.py (live, skipped without GOOGLE_CLOUD_PROJECT)
- tester: pending (offline criteria); live test and manual ES/EN runs wait for GCP
- deviations: ADK text mode uses `Runner.run_async` per turn (no RunConfig); steering notes prepended to the next user message; known gap — a model failure mid-interview exits without saving an `abandoned` record (to fix)

### 2026-10-18 14:49 [anton-team] iteration 1 — tester run (offline criteria)
- tester (sonnet, full): PASS (offline) · 825 passed, live test skips cleanly; tool names/shapes, docstring formats, prompt checks (546 words, no FAQ content, no model ids), TextInterview start/steering/transcript/close, chat progress line, `/quit` → abandoned record, no-project error one line, ADR-003.1/002.1 greps all met · findings routed to swe: model failure mid-chat saves no record (confirmed); HUMAN_REQUEST_NOTE names a non-existent `escalate` tool; record_field docstring implies only `missing` fields are allowed; text-mode records carry channel "voice"; ADK logs tracebacks to the terminal on model errors; no-project message wording
- tech-lead: GCP ready — `.env` written (git-ignored) for the personal GCP project / us-central1; text model replied in 2.5 s; Live, Flash-Lite and embedding models available

### 2026-10-18 14:59 [anton-team] iteration 2 — tester findings, live wiring, first real-model runs
- swe (sonnet): commits 636cf6e (abandoned record saved on model failure, tool names in notes, explicit channel, quieter chat, clear no-project message), a0f1fdd + 064a58e (live/eval tests read the repo `.env`; offline isolation unchanged), 4317f11 + 85e44e9 (`build_adk_model`: ADK `Gemini(model, client=make_genai_client(settings))` — Vertex via ADC, no env, no API key; first commit failed the architecture test, fixed in the second), f74b540 (store parser: unique area match first, city only narrows)
- tester: `uv run pytest -q` → 842 passed; live `pytest -m live tests/integration/test_text_mode.py` → 1 passed in 38 s (Gemini 2.5 Flash, Vertex, the personal GCP project)
- manual real-model runs (tech-lead, scratchpad driver with scripted candidate lines): ES run 1 stuck on the store ("Ruzafa, en Valencia" → ambiguous; model looped) → parser fixed; ES run 2 → completed / meets_requirements, all slots correct ("lunes a viernes por la tarde, pero los miércoles no" → mon/tue/thu/fri afternoon; "dos años y medio" → 30); EN run → completed / meets_requirements, data correct (phone self-correction applied, "weekday mornings and Saturday nights" → mon–fri morning + sat night, "in two weeks" → 2026-11-01, 18 months)
- prompt findings (to fix as ana-v2): Ana answered in Spanish to an English candidate for the whole call (ADR-012); confirm_profile read-back spoken a turn late, after the candidate already said "correct", then the call ended without real confirmation

### 2026-10-18 15:09 [anton-team] iteration 3 — prompt ana-v2 (language, same-turn read-back)
- swe (sonnet): blocked (partial) · commits 591e071 + ea4b55a · files: interview/prompts.py (`ana-v2`: LANGUAGE section, same-turn read-back rule, confirmation example; 747 words), agent/text.py (start note names the session language; `controller.language` set from it), tests (prompt rules, start-note language)
- tester: `uv run pytest -q` → 845 passed; live test → 1 passed · real-model runs (9): language now correct on every turn in ES and EN; read-back on the same turn in ~3 of 5 runs with the final prompt — failures are a lead-in sentence ("para confirmar, tus datos son:", "I have the following details for you:") with no list, the turn ending after the confirm_profile tool call; every run ended completed / meets_requirements with correct data
- deviations: 4 prompt edits used (one over the allowance) before stopping

### 2026-10-18 15:09 [anton-team] halted
- at: T8 prompt iteration (read-back) · iterations used: 3/3
- last failure: Gemini 2.5 Flash intermittently ends the confirmation turn after a lead-in, without reading back role/phone/store/start date
- worktree state: committed, clean (main @ ea4b55a)
- next: human decision — code-side guarantee for the read-back (confirm_profile returns ready-to-say text and the session re-prompts once when the reply after confirm_profile lacks the details) vs. accept as a known limitation and revisit in SPEC-014 evals

### 2026-10-18 15:09 [anton-team] question — read-back guarantee
- question: add a code-side guarantee for the confirmation read-back, or accept the intermittent miss as a known limitation for now?
- options: code-side guard (recommended) · accept and track in SPEC-014 evals
- blocking: closing SPEC-007 (and the same behaviour in SPEC-008 live voice)

### 2026-10-18 15:28 [anton-team] judge
- judge: approved code-side read-back guarantee — `confirm_profile` returns ready-to-say read-back text and the expected details; a pure controller check verifies the agent's reply contains them; the session re-prompts once with a [SYSTEM NOTE] when they are missing; same mechanism required in SPEC-008 live voice
- source: user decision in chat (2026-10-18); build resumes from the halted state with one extra iteration for this task

### 2026-10-18 15:35 [anton-team] iteration 4 — code-side read-back guarantee (approved extra iteration)
- swe (sonnet): done · commit 8f9b146 · files: interview/controller.py (`confirm_profile` returns `say`; `readback_pending`, `readback_complete(text)`, `readback_say()`, `drop_readback()`), agent/text.py (one re-prompt with [SYSTEM NOTE] when the reply after confirm_profile lacks the details; combined reply in transcript; warning if still missing), interview/prompts.py (read `say` back in the same reply; still ana-v2), tests
- tester: PASS (tech-lead re-run) · `uv run pytest -q` → 864 passed; live test → 1 passed · real-model runs 3 ES + 3 EN: read-back before the candidate's confirmation in 6/6, guard did not need to fire, all completed / meets_requirements
- deviations: acceptance criterion text says `prompt_version = "ana-v1"`; the prompt was bumped to `ana-v2` during prompt iteration as the spec's plan requires ("bump PROMPT_VERSION on each change") · observation for SPEC-014: "el lunes que viene" said on a Sunday resolved to 19 Oct in 2 runs and 26 Oct in 1 — the read-back now exposes it to the candidate

### 2026-10-18 15:41 [anton-team] review round 1
- reviewer: REVISE · [major] live test never asserts completion (`completed or ≥12` made redundant); [major] `_ROLE_LABELS` duplicates the role synonym map (ADR-001.1/.2) and prefix-matches ("salario" → "sala"); [major] read-back matching/formatting adds per-field branches in the controller (ADR-016.5) → move to a pure `interview/readback.py` table; [major, evidence] AC1 not run through `acme-agent chat` itself · minors: per-session bound logger + `configure_logging()` in chat, prompt "Then"/length-rule conflict, `confirm_profile` docstring lacks `say`, broad except in chat settings check, human-request note vs prompt (insist vs accept), tool tests thin, progress-line format · notes: AC4 "ana-v1" is spec wording (version bumped per plan); candidate_questions must be listed in SPEC-010; location.py missing from `touches`
- tech-lead: SPEC-010 gets an explicit candidate_questions-from-faq_missed requirement; location.py added to `touches`; AC1 to be run through the real CLI after the fixes; AC4 wording raised with the human

### 2026-10-18 15:46 [anton-team] iteration 5 — review round 1 fixes + CLI evidence
- swe (sonnet): done · commit f5f8478 · files: interview/readback.py (new pure READBACK table), interview/controller.py (thin read-back methods, no per-slot branches, no role vocabulary), domain/validators/choice.py (public `ROLE_WORDS`, whole-word matching), agent/text.py (per-session bound logger), agent/tools.py (`say` documented), interview/prompts.py (`ana-v3`: read-back is the one exception to the length rule), cli.py (`configure_logging`, ValidationError handling, `[n/m slots]` short labels), tests (strict live assertions, "salario" ≠ "sala", two-controller isolation, confirm_profile keys)
- tester: PASS (tech-lead re-run) · `uv run pytest -q` → 868 passed; live test (strict: COMPLETED, ≥ 12 slots, MEETS_REQUIREMENTS, model.text) → 1 passed in 43 s
- AC1 evidence via the real CLI (tech-lead, candidate lines piped into `uv run acme-agent chat`, temp ACME_DATA_DIR): `--lang en` → c_01M58C6CPKKCDBYNN4NYESMXZ1 completed / meets_requirements, read-back before confirmation incl. corrected phone; `--lang es` → c_01M58C7HJ48BSWP99AKYD5RBKY completed / meets_requirements, read-back before confirmation; both listed by `acme-agent list`

### 2026-10-18 15:49 [anton-team] review round 2
- reviewer: APPROVE · all round-1 findings fixed, no regressions (readback.py pure and table-driven, ROLE_WORDS single vocabulary, ana-v3 consistent with controller notes and tool docstrings, chat logging masks PII) · follow-ups (non-blocking): give `role` a READBACK row (mark risky) to remove the last role special-cases; text-channel records carry `ModelInfo.live`; SPEC-014 to track Sunday "el lunes que viene"; AC4 wording to be amended by the human

### 2026-10-18 15:49 [anton-team] implemented
- PR: not opened — project builds directly on `main` (commits 8fc2274..HEAD); 868 offline tests, live test and real CLI runs green

### 2026-10-18 15:49 [anton-team] verified (on main, no PR)


### 2026-10-18 15:54 [anton-team] judge
- judge: acceptance criterion 4 reworded from `prompt_version = "ana-v1"` to "the current `PROMPT_VERSION` (`ana-v3` at verification)" — the spec's plan requires a bump on every prompt change; evidence unchanged
- source: user approval in chat (2026-10-18)

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| `acme-agent chat` completes a full interview in English and in Spanish with a real Gemini model (manual check, noted in Verification) and saves a record whose status is computed by rules. | manual: `uv run acme-agent chat --lang en` / `--lang es` with piped candidate lines, temp ACME_DATA_DIR | pass | en → c_01M58C6CPKKCDBYNN4NYESMXZ1, es → c_01M58C7HJ48BSWP99AKYD5RBKY, both completed / meets_requirements, read-back before confirmation; status from domain.rules via build_record (log "iteration 5") |
| Unit tests: each tool's output shape; `search_faq` with `NullRetriever` returns `found: false` and logs `faq_missed`; tool count and names; prompt assertions. | test | pass | 868 passed; tests/unit/test_tools.py (15 tests), tests/unit/test_prompts.py |
| `pytest -m live tests/integration/test_text_mode.py` passes with credentials. | live test (Vertex ADC, the personal GCP project) | pass | 1 passed in 43 s with strict assertions (COMPLETED, ≥ 12 filled, MEETS_REQUIREMENTS, model.text, prompt_version) |
| The saved record contains `model.text`, `model.prompt_version` = the current `PROMPT_VERSION` (`ana-v3` at verification), transcript and events. | test | pass | tests/unit/test_text_interview.py::test_close_saves_record + live test |
