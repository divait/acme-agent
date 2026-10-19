---
id: SPEC-008
title: Live voice session: ADK live agent and WebSocket gateway
status: verified
mode: full
origin_type: technical
origin: Candidates must complete a short voice screening interview with Ana: consent first, every required field collected or marked unresolved, corrections, barge-in, ~1-1.5 s responses.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-002, ADR-003, ADR-016, ADR-006, ADR-009, ADR-013, ADR-014]
supersedes: []
superseded_by: null
depends_on: [SPEC-007]
touches: [src/acme_agent/agent/live.py, src/acme_agent/web/app.py, src/acme_agent/web/session.py, src/acme_agent/web/protocol.py, src/acme_agent/cli.py, tests/web/]
parent: null
---

# SPEC-008 — Live voice session: ADK live agent and WebSocket gateway

## Problem & Scope
Run real-time voice interviews: a FastAPI app with `POST /api/interviews` and `GET /ws/interview/{id}`, an `InterviewSession` runtime per WebSocket (upstream, downstream, persister and watchdog tasks under one TaskGroup), and the ADK live agent with Gemini Live native audio, transcription, VAD and session resumption.

Runtime and protocol: TECHNICAL_DESIGN §1–3.

## Non-goals
- The browser UI (SPEC-009) — tested here with a Python WebSocket client and WAV fixtures.
- Sentiment monitor (SPEC-012), post-call processing (SPEC-010) — plugged in through the finalizer and hooks.
- Telephony.

## Functional Requirements
- `POST /api/interviews` creates a ULID conversation id (rate-limited per IP, 5/min) and returns `{conversation_id, ws_url}`.
- `GET /ws/interview/{id}`: origin allow-list (`ACME_ALLOWED_ORIGINS`), one active socket per id (second → close 4409), frame limits (audio ≤ 16 KB, text ≤ 2 KB → close 1009).
- Message protocol exactly as TECHNICAL_DESIGN §2 (client: binary audio, `start`, `text`, `end`, `ping`; server: binary audio, `transcript`, `interrupted`, `slot`, `faq`, `state`, `ended`, `completed`, `error`), defined as Pydantic models in `web/protocol.py`.
- On `start`, the controller's greeting goal is sent to the model so Ana speaks first.
- Input/output transcriptions become transcript turns (finalised on turn completion) and `transcript` messages; controller events become `slot`/`state`/`faq` messages.
- `interrupted` from the model is forwarded so the client flushes playback.
- Watchdog: after 20 s of candidate silence a `[SYSTEM NOTE]` asks Ana to check in; after 60 s the session ends as `abandoned`; at 8 min Ana is asked to wrap up; hard stop at 10 min.
- Persister flushes the record every 5 s when dirty and on phase changes; on any end path the finalizer runs and `ended` (then `completed` if still connected) is sent.
- Any task failure → session ends `abandoned`, partial record persisted, `error` message with a user-facing message (ADR-003.3).
- `acme-agent serve [--host --port --reload]` starts uvicorn; static files mount point `/` reserved for SPEC-009 (serves a placeholder page until then).

## Technical Requirements
- `agent/live.py`: `build_live_agent(controller, container)` and `build_run_config(settings)` per TECHNICAL_DESIGN §3 — `StreamingMode.BIDI`, `response_modalities=["AUDIO"]`, input and output transcription (ADR-002.3), prebuilt voice from settings, session resumption, affective dialog when the pinned model supports it.
- `web/session.py`: `InterviewSession` owning controller, record, `LiveRequestQueue`, tasks; `asyncio.TaskGroup`; clean shutdown closes the queue and cancels tasks; structlog bound with `conversation_id` (ADR-014.3).
- Audio in: PCM16 LE mono 16 kHz forwarded as `types.Blob(mime_type="audio/pcm;rate=16000")`; audio out forwarded as raw bytes (24 kHz).
- Steering notes via `send_content` with `[SYSTEM NOTE]` prefix.
- Stdlib loggers (uvicorn, google-adk, google-genai) are routed through structlog's `ProcessorFormatter` so `mask_pii` applies to third-party log lines too (ADR-014.4; follow-up from SPEC-001 review).
- Per-conversation metrics collected into `record.metrics`: duration, turns, tool calls, tool errors, interruptions, time to first agent audio.
- Tests: protocol model tests; session tests with a fake live runner (async generator of scripted events incl. tool calls, transcriptions, interruption, error) asserting messages sent, record persisted, abandoned path; one `live`-marked test streaming a short Spanish WAV fixture to real Gemini Live and asserting an agent audio reply and a transcript.

## Acceptance Criteria
- Read-back guarantee (SPEC-007 decision): after `confirm_profile`, when the agent's completed turn (output transcription) fails `controller.readback_complete(text)`, the session sends one [SYSTEM NOTE] asking Ana to read the details now; tested with the fake runner.
- The persister and the final save always write `controller.build_record(...)` output, never a record assembled from the raw event stream, so consent-refusal redaction (ADR-009.4) holds for every stored version (follow-up from SPEC-005 review).
- On every end path the persister task is cancelled and any in-flight flush awaited before the finalizer saves the final record, so a stale periodic flush can never overwrite it (test with a slow fake repository; follow-up from SPEC-006 review).
- With the fake runner, a scripted session produces the expected sequence of server messages and a persisted record (unit/integration tests, no network).
- Exceptions injected into any task end only that session with `abandoned` and a persisted partial record; a second concurrent session is unaffected (test).
- Origin, frame-size, duplicate-socket and rate limits are enforced (tests).
- `pytest -m live tests/web/test_live_audio.py` gets audio back from Gemini Live for a WAV fixture.
- Manual run with a minimal WebSocket client script (`scripts/ws_client.py`, mic via `sounddevice` optional dev dep) holds a full conversation; time to first agent audio is logged; over 5 turns on a normal connection the median model response (final candidate transcription → first agent audio) is ≤ 1.5 s and the median perceived response (end of candidate voice → first agent audio, client-measured) is ≤ 2.5 s. Perceived ≤ 1.5 s stays the tracked target (overview QA1).

## Dependencies & Risks
- ADK live API details (event fields, run_live signature) must be checked against the pinned version; keep all ADK specifics inside `agent/live.py`.
- Native-audio tool-call reliability: monitor `tool calls / filled slots` in metrics; SPEC-010 reconciliation is the safety net.
- Region availability of the Live model: configurable `GOOGLE_CLOUD_LOCATION`.

## Plan
Start from the ADK bidi-streaming sample shape, but structure it as `InterviewSession` from the beginning. Build protocol models and the session with a fake runner test-first, then plug the real live agent and test with a WAV fixture, then the dev WebSocket client for manual voice checks.

## Tasks
- [x] Define protocol messages in `web/protocol.py` + tests
- [x] Implement `agent/live.py` (`build_live_agent`, `build_run_config`)
- [x] Implement `InterviewSession` (tasks, TaskGroup, shutdown, steering, metrics)
- [x] Implement watchdog timers
- [x] Implement FastAPI app: `POST /api/interviews`, WebSocket endpoint, limits, origin check, placeholder static mount
- [x] Add `acme-agent serve`
- [x] Write fake-runner session tests (happy path, interruption, failure, concurrency)
- [x] Add live-marked WAV test and `scripts/ws_client.py`
- [x] Measure and log time to first agent audio

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 15:54 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 7e210fc
- plan/tasks: pre-existing; tech-lead plan — three dispatches: (1) protocol, live agent/run config via `build_adk_model(settings, settings.live_model)`, FastAPI app + limits, `serve`, stdlib logs through structlog; (2) InterviewSession runtime (TaskGroup: upstream, downstream, persister, watchdog), steering, read-back guard, metrics, finalizer ordering, fake-runner tests; (3) WAV fixture (macOS `say` + `afconvert`), live audio test, scripts/ws_client.py, timed run

### 2026-10-18 16:17 [anton-team] iteration 1 — part 1 — protocol, live agent, gateway, serve, logging
- swe (sonnet): done · commit ce21cf1 · files: web/{protocol,frames,app,main}.py, web/static/index.html (placeholder), agent/live.py (`build_run_config`, `build_live_agent`), logging.py (stdlib through ProcessorFormatter, access-log query strings stripped), cli.py (`serve`), Makefile, tests/web/{test_protocol,test_app}.py, tests/unit/{test_live_agent,test_logging}.py
- tester: tech-lead pre-check → 904 passed; full tester run after part 3
- deviations: missing Origin header rejected (1008) — non-browser clients send `Origin: http://localhost:8000`; affective dialog/proactivity off until verified live; `StreamingMode` imported from a private ADK module (pin-sensitive)

### 2026-10-18 16:17 [anton-team] iteration 1 — part 2 — InterviewSession runtime
- swe (sonnet): done · commit 903b468 · files: web/session.py (TaskGroup: upstream, downstream, controller-event pump, persister, watchdog; steering; read-back guard at turn_complete; metrics; safe finalisation), web/main.py, agent/live.py (`stream_live_events` — the only run_live path), bootstrap.py (finalizer `metrics`), tests/web/test_session.py (19 tests)
- tester: tech-lead pre-check → 923 passed
- deviations: fifth task (controller-event pump) added; `tool_errors` reported as `validation_errors`

### 2026-10-18 16:17 [anton-team] iteration 1 — part 3 — real Gemini Live
- swe (sonnet): done · commit 25e594f · files: tests/fixtures/audio/*.wav (7 synthetic ES utterances, 295 KB) + README, tests/web/test_live_audio.py (live), scripts/ws_client.py, web/session.py (fix: date note + greeting sent as ONE content turn — two turns made Ana greet twice), tests/web/test_session.py, pyproject/uv.lock (optional `mic` group)
- tester: live audio test → 1 passed in 10.4 s (greeting audio, candidate + agent final transcripts, consent filled, record channel web_voice) · real served run (7 WAV turns): consent, role, name, phone, availability, hours, start date, store, right to work filled before the scripted end; client-measured latency median 1816 ms (end of candidate audio → first agent audio, includes VAD + ASR), server metric median 1140 ms (final transcription → first audio)
- tech-lead analysis of the record: start date correct (model `said` "desde el 1 de noviembre"; only the input-transcription stream misheard "enero" — transcripts approximate, ADR-002); [finding] after an ambiguous store the model recorded "Acme Burgers Sol" with `said` = "Acme Burgers Sol" although the candidate never chose (principle 3; read-back would catch it) → prompt rule; [finding] `interruptions` metric counts every server-VAD speech start (7 in 7 turns) → count only barge-ins while agent audio is playing

### 2026-10-18 16:20 [anton-team] iteration 2 — live-run findings
- swe (sonnet): done · commit ffa6a49 · files: interview/prompts.py (`ana-v4`: `said` must be the candidate's own words; never fill an unanswered choice), interview/evidence.py (pure `said_in_transcript`), interview/controller.py (last 3 candidate texts, `said_unverified`, `on_said_unverified` hook — advisory only), web/session.py + agent/text.py (warning `said_not_in_transcript` with field name only; `said_unverified` in metrics; barge-in window 300 ms), tests
- tester: tech-lead re-run → 929 passed; live audio test → 1 passed

### 2026-10-18 16:23 [anton-team] iteration 2 — tester run (full, incl. one live test and one served run)
- tester (sonnet, full): PASS · 929 passed offline; tests/web 50 passed; ADR greps clean; stdlib/uvicorn lines masked, query strings stripped; live audio test → 1 passed (10 s); served ws_client run c_01M58E95GRZETGJGNJ2523HC8S: consent, name, role, phone, availability filled; record channel web_voice, prompt ana-v4; `interruptions` 0 (no real barge-in), `said_unverified` [full_name] (ASR misheard the name; advisory works)
- latency: server-side median 1317.5 ms over 5 turns (final candidate transcription → first agent audio) — meets ≤ 1.5 s; client-measured median 2019 ms (end of candidate audio → first agent audio, includes end-of-speech detection ≈ 0.7 s) — does not; greeting first audio 2.9 s
- observation: ASR heard "Chambéry, Madrid" → store falls back to city-only ambiguous (Sol/Chamberí); fuzzy area matching would resolve it

### 2026-10-18 16:31 [anton-team] review round 1
- reviewer: REVISE · [blocker] R-045 ADR-009.4: declined-consent records store the full transcript (name/phone spoken) — session `_build_record` and `SaveOnlyFinalizer` attach it unredacted (text mode too); [major] server latency anchor taken after the flush → ~0/negative samples; [major] latency criterion means end of candidate speech → first agent audio (overview QA1, TECHNICAL_DESIGN §11): client 1816/2019 ms not met, and no served run reached confirmation/completed; [major] gateway accepts never-issued ids (rate limit bypass, a record per bare connect, reconnect overwrites a stored record) · minors: private StreamingMode import, `_drain_flush` silent/unbounded, `aclosing` on run_live, "answers saved" message when save failed, stale StubSession default, third-party loggers at DEBUG could log free text, `websockets` undeclared for ws_client, task checkboxes
- tech-lead decisions: no transcript (and no `said_unverified`) is stored unless consent is a clear yes — "consent not given" treated like "declined" (constitution: consent before anything else); fuzzy area matching for ASR variants ("Chambéry") → SPEC-013 task; trusted forwarded headers / ws_url behind a proxy → SPEC-016; if the tuned client-side latency still misses 1.5 s, the threshold goes to the human

### 2026-10-18 16:44 [anton-team] iteration 3 — review round 1 fixes (A: correctness, B: latency + full conversation)
- swe (sonnet): A done · commit 644bdc8 · single redaction point in `InterviewController.build_record(transcript=, metrics=)` (no transcript / said_unverified unless consent is a clear yes; used by session and SaveOnlyFinalizer), issued-id registry (unissued/reused/expired → 1008; no record without `start`), latency anchored on last candidate input, StreamingMode from run_config, bounded `_drain_flush`, `aclosing` runner, honest error message, StubSession moved to tests, third-party loggers ≥ INFO, `websockets` dev dep · B done · commit d589745 · configurable VAD (`ACME_VAD_SILENCE_MS` default 300, `ACME_VAD_END_SENSITIVITY` default high), ws_client voiced-end latency, 12 normal-rate synthetic ES fixtures
- tester: tech-lead re-run → 938 passed; live audio test → 1 passed · FULL served voice conversation (12 turns): all 13 fields correct (name, rider, phone, Chamberí, mon–fri mornings, 25 h, 2026-10-26, eligibility, licence, vehicle, 30 months), read-back before "Sí, es todo correcto", record completed / meets_requirements, interruptions 0
- latency (not met): perceived end-of-voice → first agent audio median ≈ 2.3 s (VAD 500), 2.1 s (300), 1.96 s (150); server median ≈ 1.0 s; greeting first audio 2.9–4.0 s, 10.9 s on a cold start · cause: record_field tool round trip before speaking + native-audio turnaround; VAD contributes ≈ 0.3 s

### 2026-10-18 16:44 [anton-team] question — latency target
- question: the perceived latency (end of candidate speech → first agent audio) is ≈ 2.0–2.3 s against the 1.5 s criterion; restate the criterion, or spend an iteration on an experiment to cut the tool round trip?
- options: restate as model response ≤ 1.5 s from end-of-speech detection (server ≈ 1.0 s, met) + perceived ≤ 2.5 s, keep 1.5 s perceived as a tracked target · experiment (non-blocking tool calls / acknowledge-first) before closing
- blocking: SPEC-008 review round 2 and closing the spec

### 2026-10-18 17:04 [anton-team] iteration 4 — human local test findings
- human mic test (scripts/ws_client.py --mic): (1) Ana heard her own playback through open-ear earbuds and kept interrupting herself → ws_client half-duplex by default + device selection (commits 79a9012 live playback, 63ab001 AsyncExitStack crash fix, 0c629e2 half-duplex/devices); (2) input transcription sometimes in Hindi/Arabic script for Spanish speech (slots still correct) → commit 674219b: `ACME_TRANSCRIPTION_LANGUAGES` (default es-ES,en-US; one code forces a single language) as `language_codes` on input/output transcription, plus `custom_vocabulary` from stores.json ("Acme Burgers", store names, cities, areas) — both accepted by the Vertex native-audio model
- tester: tech-lead re-run → 941 passed; live audio test → 1 passed; served WAV subset → clean Spanish transcripts incl. "Chamberí"; mic retest by the human pending

### 2026-10-18 17:14 [anton-team] answer — latency target
- human: "go with spec 008" — proceed with the recommended option (restate the criterion)
- applied: acceptance criterion now median model response ≤ 1.5 s (final transcription → first audio) and median perceived ≤ 2.5 s (end of voice → first audio); perceived 1.5 s kept as the tracked target in overview QA1; TECHNICAL_DESIGN §11 records the measured numbers and the next levers (acknowledge-first / non-blocking tools, warm greeting)
- next: reviewer round 2 over 7e210fc..HEAD

### 2026-10-18 17:18 [anton-team] iteration 5 — review round 2
- reviewer (round 2): APPROVE · all round-1 findings fixed (R-045 single redaction point, latency anchor, issued-id registry, minors); latency judged against the restated criterion → met (server ≈ 1.0–1.3 s, perceived ≈ 1.96–2.3 s); 941 passed, ruff/mypy clean, coverage domain+interview 98.3%; no public-repo wording issues
- minors F1–F4 fixed · swe commit a2e6698 · ws_client unused Player fields removed, summary prints "(bound <= 2500, target <= 1500)", `build_record` side-effect free (recent-text clear moved to the consent purge hook), empty `ACME_TRANSCRIPTION_LANGUAGES` rejected · F5 (`StreamingMode` private import) accepted, re-check on ADK bump
- tester: tech-lead re-run → 946 passed
- follow-ups: latency levers (acknowledge-first / non-blocking tools / warm greeting) and reconnect-vs-single-use ids → SPEC-009 notes; human mic retest pending

### 2026-10-18 19:01 [anton-team] follow-up — stale flush race (found while closing SPEC-011)
- problem: `test_final_record_wins_over_in_flight_flush` failed ~1 in 12 full runs; root cause in the code, not only the test — when the in-flight periodic flush outlives the drain timeout (`flush_s`), the stale save could land after the final save and overwrite the final record
- swe (sonnet): commit c213dcc (event-driven test, `types-PyYAML` dev dep for mypy on tests) · commit 8282d8b (`_flush_abandoned` + `_reassert_final`: after finalize, await the stale flush up to `Timings.stale_flush_s` = 30 s and re-save the final record; `stale_flush_unresolved` logged on timeout; `completed` sent after the re-save)
- tester: tech-lead → new test_final_record_wins_after_timed_out_drain fails on the pre-fix session.py and passes on the fix; swe loops 50/50 and full suite 5×; tech-lead re-run → 1032 passed

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Read-back guarantee: one [SYSTEM NOTE] when the completed agent turn fails `readback_complete` | test | pass | tests/web/test_session.py::test_readback_guard_sends_one_note_when_details_missing, ::test_readback_guard_silent_when_details_read |
| Persister and final save always write `controller.build_record(...)` (ADR-009.4 for every stored version) | test | pass | tests/web/test_session.py::test_consent_refusal_every_version_redacted, ::test_declined_consent_transcript_not_stored, ::test_abandoned_before_consent_stores_no_transcript; tests/unit/test_bootstrap.py::test_finalizer_redacts_transcript_without_consent |
| Persister cancelled and in-flight flush awaited before the final save | test | pass | tests/web/test_session.py::test_final_record_wins_over_in_flight_flush |
| Scripted fake-runner session → expected server messages and persisted record | test | pass | tests/web/test_session.py::test_happy_path, ::test_interruption_forwarded, ::test_session_factory_through_gateway |
| Injected task exceptions end only that session as `abandoned`, partial record, second session unaffected | test | pass | tests/web/test_session.py::test_exception_in_any_task_abandons_only_that_session, ::test_model_error_event_abandons_with_error_frame |
| Origin, frame-size, duplicate-socket and rate limits enforced | test | pass | tests/web/test_app.py::test_origin_rejected, ::test_oversized_frames_close_1009, ::test_duplicate_socket_4409_and_id_not_reusable_after_close, ::test_rate_limit_five_per_minute_per_ip, ::test_unissued_id_rejected |
| `pytest -m live tests/web/test_live_audio.py` gets audio back from Gemini Live | live test | pass | 1 passed (≈10 s), iterations 1–4 |
| Manual ws_client full conversation; model response median ≤ 1.5 s, perceived median ≤ 2.5 s | manual (served, 12 WAV turns) | pass | iteration 3: 13 fields correct, read-back, completed / meets_requirements; server ≈ 1.0–1.3 s, perceived ≈ 1.96–2.3 s |
