# Review rubric

Generated on 2026-10-18 (refreshed for ADR-015 and ADR-016 the same day) from the constitution, tech stack and accepted ADRs (same
procedure as `/anton-team:setup`). Regenerate after changing those documents. The
reviewer agent walks every entry; `blocker` and `major` failures force a REVISE.

**Diff scope:** specs are built directly on `main`. The reviewer reviews
`git diff <spec start commit>..HEAD`, where the start commit is recorded in the spec's
`started` log entry.

| ID | Severity | Criterion | How to check | Source |
| --- | --- | --- | --- | --- |
| R-001 | blocker | All tests pass and new behavior has tests | tester report; diff adds/updates tests | base |
| R-002 | blocker | Every acceptance criterion in the spec is met | map criteria to evidence | base |
| R-003 | blocker | No scope creep into the spec's Non-goals | compare diff against spec.md | base |
| R-004 | major | Errors are handled deliberately (no swallowed exceptions, clear failure paths) | read changed code paths | base |
| R-005 | major | No dead code, commented-out blocks, or debug leftovers | diff scan | base |
| R-006 | major | Follows the project's style and layout conventions | tech-stack.md conventions; layout in docs/DESIGN.md §14 | architecture/tech-stack.md |
| R-007 | major | No secrets in code/config; inputs validated at trust boundaries | diff scan for credentials, input handling | base/security |
| R-008 | major | Dependencies added only when justified and recorded in the log | diff of pyproject.toml/uv.lock vs the spec's Implementation Log | base/security |
| R-009 | minor | Names and comments explain intent; public surface is documented | read changed code | base |
| R-010 | minor | Plan deviations are recorded in the implementation log | ## Implementation Log in spec.md | base |
| R-011 | blocker | `raw/`, `.env*` (except `.env.example`) and `data/` runtime output are never committed | `git diff --name-only <spec start>..HEAD` contains none of them | constitution/technical-constraints.md |
| R-012 | major | Tool handlers and audio forwarding make no network call or blocking I/O, except `search_faq` and the returning-candidate lookup, which are bounded by timeouts | read changed tool functions and session tasks | constitution/principles.md (6) |
| R-013 | major | Prompt and model versions are recorded in every stored conversation record | `record.model` populated in record-building code and tests | constitution/technical-constraints.md |
| R-014 | major | ADR-001.1 — Business content (roles, stores, FAQ text, pay ranges) lives in `knowledge/` files or `interview/slots.py`; it is never hard-coded in prompts or other Python modules. | grep `src/acme_agent/` for store names / euro amounts from `knowledge/`; only `interview/slots.py` and knowledge loaders may reference them. | ADR-001.1 |
| R-015 | major | ADR-001.2 — Roles are the closed enum `crew_member \| kitchen \| delivery_rider`; adding a role means updating the enum, the synonym map and the role-specific slot conditions together. | `domain/models.py` `Role` enum; tests in `tests/unit/test_validators.py` cover each role's synonyms. | ADR-001.2 |
| R-016 | major | ADR-002.1 — Model ids are read from settings (`ACME_LIVE_MODEL`, `ACME_TEXT_MODEL`, `ACME_SENTIMENT_MODEL`, `ACME_EMBEDDING_MODEL`); no model id string literal appears outside `config.py` and tests. | `grep -rn '"gemini-\\|text-embedding-' src/ \| grep -v config.py` returns nothing. | ADR-002.1 |
| R-017 | blocker | ADR-002.2 — Vertex AI is reached only with ADC / service-account credentials via `google-genai` (Vertex mode) or ADK; no API key parameter or env var is used anywhere. | grep `api_key` and `GOOGLE_API_KEY` in `src/` and `.env.example`. | ADR-002.2 |
| R-018 | major | ADR-002.3 — Input/output transcription is enabled for every live session and the transcript is stored in the conversation record. | `RunConfig` in `agent/live.py` sets both transcription configs; session test asserts transcript turns are recorded. | ADR-002.3 |
| R-019 | major | ADR-003.1 — Only `acme_agent/agent/` and `acme_agent/web/` import `google.adk`. | `grep -rln "google.adk" src/` lists only files under those packages. | ADR-003.1 |
| R-020 | major | ADR-003.2 — Tools are created per session by `build_tools(controller)`; no module-level controller, session or mutable global state exists in `agent/` or `web/`. | read `agent/tools.py` and `web/session.py`; test that two sessions' tools mutate different controllers. | ADR-003.2 |
| R-021 | major | ADR-003.3 — A failure inside one session ends only that session (TaskGroup per session, errors caught at the session boundary) and still persists the partial record with `end_reason: abandoned` (`escalated` if an escalation was already raised). | session test that injects an exception in a task and asserts a persisted `abandoned` record. | ADR-003.3 |
| ~~R-022~~ | ~~major~~ | ~~ADR-004.1~~ (superseded by ADR-016) | — | ~~ADR-004.1~~ |
| ~~R-023~~ | ~~major~~ | ~~ADR-004.2~~ (superseded by ADR-016) | — | ~~ADR-004.2~~ |
| ~~R-024~~ | ~~major~~ | ~~ADR-004.3~~ (superseded by ADR-016) | — | ~~ADR-004.3~~ |
| ~~R-025~~ | ~~major~~ | ~~ADR-004.4~~ (superseded by ADR-016) | — | ~~ADR-004.4~~ |
| ~~R-026~~ | ~~major~~ | ~~ADR-004.5~~ (superseded by ADR-016) | — | ~~ADR-004.5~~ |
| ~~R-027~~ | ~~major~~ | ~~ADR-005.1~~ (superseded by ADR-015) | — | ~~ADR-005.1~~ |
| ~~R-028~~ | ~~major~~ | ~~ADR-005.2~~ (superseded by ADR-015) | — | ~~ADR-005.2~~ |
| ~~R-029~~ | ~~major~~ | ~~ADR-005.3~~ (superseded by ADR-015) | — | ~~ADR-005.3~~ |
| ~~R-030~~ | ~~major~~ | ~~ADR-005.4~~ (superseded by ADR-015) | — | ~~ADR-005.4~~ |
| R-031 | major | ADR-006.1 — Conversation records are read and written only through `ConversationRepository`; no other module opens files under the data directory or calls GCS. | grep `open(`, `write_text`, `google.cloud.storage` outside `storage/`. | ADR-006.1 |
| R-032 | blocker | ADR-006.2 — The JSON implementation writes atomically (temp file + `os.replace`). | read `storage/json_repo.py`; test that a failed write leaves the previous file intact. | ADR-006.2 |
| R-033 | major | ADR-006.3 — Every record carries `schema_version`; changing the record shape bumps it. | `ConversationRecord.schema_version` exists; diff review of `domain/models.py`. | ADR-006.3 |
| R-034 | major | ADR-007.1 — FAQ content is never included in the system instruction; the model gets it only through `search_faq` results. | grep `interview/prompts.py` for FAQ text; prompt test asserts no FAQ section titles. | ADR-007.1 |
| R-035 | major | ADR-007.2 — When the best similarity is below the configured threshold, `search_faq` returns `found: false` and no answers. | retriever unit test with an off-topic query. | ADR-007.2 |
| R-036 | major | ADR-007.3 — Every answered FAQ query is logged as an event with its `source` section. | tool test asserts a `faq_answered` event with `source`. | ADR-007.3 |
| R-037 | major | ADR-007.4 — The retriever is used behind a `Retriever` protocol so tests use a fake embedder and need no network. | `knowledge/retriever.py` defines the protocol; unit tests run offline. | ADR-007.4 |
| R-038 | major | ADR-008.1 — Post-call extracted values go through the same `domain/validators.py` parsers as live input before they are used. | read `analysis/post_call.py`; test that an invalid extracted phone is not stored. | ADR-008.1 |
| R-039 | blocker | ADR-008.2 — Reconciliation never overwrites a valid live value: disagreement keeps the live value and adds a `reconciliation_conflict`; values filled post-call are marked `source: post_call`. | unit tests for the four reconciliation cases (agree, fill, conflict, both missing). | ADR-008.2 |
| R-040 | major | ADR-008.3 — LLM outputs consumed by code use structured output (`response_schema` with a Pydantic model); no regex or ad-hoc JSON parsing of free text. | grep `json.loads`/`re.search` on model output in `analysis/`. | ADR-008.3 |
| R-041 | blocker | ADR-008.4 — If post-call processing fails after retries, the record is still saved with `summary: null` and status `needs_human_review`. | test with a failing fake model client. | ADR-008.4 |
| R-042 | blocker | ADR-009.1 — `screening_status` is set only by `domain/rules.py`; no LLM output is mapped to it. | grep assignments to `screening`/`status` outside `domain/rules.py` and its callers in `analysis/post_call.py`. | ADR-009.1 |
| R-043 | major | ADR-009.2 — Each status carries the list of rules/knock-outs that produced it. | rules unit tests assert `knockouts`/`flags` content. | ADR-009.2 |
| R-044 | blocker | ADR-009.3 — The system instruction forbids questions about nationality, religion, health, disability, pregnancy, family and exact age, and no slot collects such data. | prompt test asserts the boundary text; slot list review; persona eval guardrail metric. | ADR-009.3 |
| R-045 | blocker | ADR-009.4 — Recording consent is the first slot; if declined, the stored record contains only metadata, the consent answer and `end_reason: declined_consent` (no transcript). | controller and session tests for the declined path. | ADR-009.4 |
| R-046 | major | ADR-010.1 — The default `pytest` run needs no network or credentials; tests that call Vertex are marked `eval` or `live` and are excluded by default. | `pyproject.toml` `addopts = "-m 'not eval and not live'"`; run tests with no ADC. | ADR-010.1 |
| R-047 | major | ADR-010.2 — Line coverage of `domain/` and `interview/` stays ≥ 90 %. | `pytest --cov=acme_agent.domain --cov=acme_agent.interview --cov-fail-under=90`. | ADR-010.2 |
| R-048 | major | ADR-010.3 — Text mode and live mode share the same `InterviewController`, `build_tools` and system instruction; there is no text-only copy of flow logic. | `agent/text.py` imports `build_tools` and `prompts.SYSTEM_INSTRUCTION`. | ADR-010.3 |
| R-049 | major | ADR-010.4 — Every spec that changes behaviour adds or updates tests for it. | the spec's diff contains test changes. | ADR-010.4 |
| R-050 | major | ADR-011.1 — Sentiment scoring is never awaited on the audio or tool path: it runs as a background task with a 3 s timeout and at most one call in flight per session. | read `analysis/sentiment.py` and its call site; test that a slow fake model does not delay tool responses. | ADR-011.1 |
| R-051 | major | ADR-011.2 — The escalation decision is a controller rule, unit-tested; the model only phrases the offer. | `InterviewController.on_sentiment` tests. | ADR-011.2 |
| R-052 | major | ADR-011.3 — Per-turn scores are stored on transcript turns and aggregated in `sentiment`. | record test. | ADR-011.3 |
| R-053 | major | ADR-012.1 — Every FAQ section exists in both `faq_es.md` and `faq_en.md` with the same section id. | unit test compares section ids of both files. | ADR-012.1 |
| R-054 | major | ADR-012.2 — Validators accept Spanish and English input (see ADR-005.3). | as ADR-005.3. | ADR-012.2 |
| R-055 | major | ADR-012.3 — Language changes are recorded as `language_switched` events and in `record.language.switches`. | session/text-mode test with a switching script. | ADR-012.3 |
| R-056 | major | ADR-013.1 — The browser client is static files under `web/static/` with no build step, bundler or npm dependency. | no `package.json`; files served by FastAPI `StaticFiles`. | ADR-013.1 |
| R-057 | blocker | ADR-013.2 — The client holds no credentials or model configuration; it only knows the WebSocket protocol in `docs/TECHNICAL_DESIGN.md` §2. | grep static files for `key`, `token`, `gemini`. | ADR-013.2 |
| R-058 | major | ADR-013.3 — Local and Cloud Run run the same image/code; differences are environment variables only (`ACME_STORAGE`, `ACME_BUCKET`, region). | no `if cloud_run`-style branches; Dockerfile has no environment-specific code. | ADR-013.3 |
| R-059 | major | ADR-014.1 — Dependencies are declared in `pyproject.toml` and locked in `uv.lock`; no `requirements*.txt`. | file listing. | ADR-014.1 |
| R-060 | major | ADR-014.2 — `ruff check` and `ruff format --check` pass; `mypy --strict` passes for `acme_agent.domain` and `acme_agent.interview`. | `make lint typecheck`. | ADR-014.2 |
| R-061 | major | ADR-014.3 — No `print()` in `src/` except the CLI's user output via typer; logging uses `structlog` bound with `conversation_id` inside sessions. | grep `print(` in `src/` excluding `cli.py`. | ADR-014.3 |
| R-062 | blocker | ADR-014.4 — Phone numbers, names and emails are masked in log output via the shared `mask_pii` processor. | logging test asserts a masked phone. | ADR-014.4 |
| R-063 | major | ADR-014.5 — Configuration comes only from `acme_agent.config.Settings`; no `os.environ` reads elsewhere. | grep `os.environ`/`os.getenv` outside `config.py`. | ADR-014.5 |
| R-064 | major | ADR-015.1 — Every `SlotName` is registered exactly once, either in `CANONICAL` (strict format validator) or in `VERBATIM` (deterministic parser), both exported from `domain/validators/`; the class of each slot matches the table above. | unit test asserting the two registries partition `SlotName` and match the table. | ADR-015.1 |
| R-065 | major | ADR-015.2 — Canonical validators accept only the canonical format and never interpret natural language; anything else returns `Issue(code="bad_format", hint=<expected format>)`. | tests feed natural-language strings ("next monday", "sí claro") to every canonical validator and expect `bad_format`. | ADR-015.2 |
| R-066 | major | ADR-015.3 — Business limits (date window, hour and month ranges, rider rules) are enforced in code on canonical values, using `ParseContext` (pure, no clock). | boundary tests per canonical slot; grep for `date.today`/`datetime.now` in `domain/`. | ADR-015.3 |
| R-067 | major | ADR-015.4 — Every `record_field` call carries `said`, and the controller stores it as `slot_meta[slot].raw`. | tool signature in `agent/tools.py`; controller test asserts `raw` is stored. | ADR-015.4 |
| R-068 | blocker | ADR-015.5 — Cross-check parsers are advisory: their result is written only to `slot_meta[slot].cross_check` and metrics; it never changes a slot value, the screening status, a `next_goal`, or triggers a re-ask. | controller test where the cross-check disagrees with the canonical value and the stored value and flow are unchanged. | ADR-015.5 |
| R-069 | major | ADR-015.6 — The model receives today's date and weekday (in the interview's timezone) at session start, and every canonical slot's format is stated in the tool description and in the `invalid` hint. | session/text-mode start sends a date note; tool docstring lists the formats; prompt test. | ADR-015.6 |
| R-070 | major | ADR-015.7 — Verbatim parsers keep ADR-005's guarantees: pure, never raise on candidate input, return `Issue(code, hint)`, and have ≥ 3 Spanish, ≥ 3 English passing and ≥ 2 failing tests each. | `tests/unit/test_validators*.py`; garbage-input test. | ADR-015.7 |
| R-071 | major | ADR-015.8 — Post-call extraction (SPEC-010) asks for the same canonical formats plus the quoted words, and runs them through the same `CANONICAL`/`VERBATIM` registries. | `analysis/schemas.py` and `analysis/post_call.py` use the registries. | ADR-015.8 |
| R-072 | major | ADR-016.1 — `acme_agent/domain/` and `acme_agent/interview/` import no I/O or LLM libraries (`google`, `fastapi`, `starlette`, `httpx`, `aiofiles`, `structlog`, `os` file access) and no other project package except `domain`. | `tests/unit/test_architecture.py` import-boundary test; grep imports in `src/acme_agent/domain/**` and `src/acme_agent/interview/**`. | ADR-016.1 |
| R-073 | major | ADR-016.2 — Slot values and slot metadata change only through `InterviewController` methods (`record`, `prefill`, `apply_reconciliation`, the consent purge); no other code assigns to the controller's profile or slot state. | grep for assignments to `.profile` / `.slot_meta` outside `interview/controller.py`. | ADR-016.2 |
| R-074 | major | ADR-016.3 — The live model is given at most five tools: `record_field`, `search_faq`, `confirm_profile`, `escalate_to_human`, `end_interview`. | unit test asserts `len(build_tools(c)) <= 5` and their names. | ADR-016.3 |
| R-075 | major | ADR-016.4 — Every `record_field` response includes `status`, `next_goal` and `missing`. | controller unit tests cover all statuses and assert those keys. | ADR-016.4 |
| R-076 | major | ADR-016.5 — Slots, their order, conditions and `ask` texts are declared as data in `interview/slots.py`; the controller contains no per-field branches except the four documented hooks — consent gating/purge, role activation, store → session country, phone lookup — which live together in one documented place. | read `interview/controller.py`; per-field branches appear only in the hook section and the consent gate of `record`. | ADR-016.5 |
| R-077 | major | ADR-016.6 — `next_goal()`, `missing()`, `progress()` and `snapshot()` never change phase, slot state or events; phase transitions happen only inside `start()`, `record`, `confirm_profile`, `escalate`, `end` and `prefill`. | unit test calling the read methods repeatedly between mutations and asserting phase and events are unchanged. | ADR-016.6 |

## Not enforced by review
- Principle 1 (the candidate's time is precious) — judged in voice QA and persona evals (turns to completion), not in a diff.
- Principle 5 (grounded or silent) — the mechanism is enforced (ADR-007); answer quality is measured by evals.
- Principle 7 (testable without a microphone) — enforced indirectly through ADR-010 rules.
- Quality attribute targets (latency ≈ 1–1.5 s, slot precision/recall) — measured at runtime and in evals.
