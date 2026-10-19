---
id: SPEC-009
title: Browser client with live captions and profile panel
status: verified
mode: full
origin_type: technical
origin: Candidates must complete a short voice screening interview with Ana: consent first, every required field collected or marked unresolved, corrections, barge-in, ~1-1.5 s responses.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-013]
supersedes: []
superseded_by: null
depends_on: [SPEC-008]
touches: [src/acme_agent/web/static/index.html, src/acme_agent/web/static/format.js, src/acme_agent/web/protocol.py, src/acme_agent/web/session.py, docs/TECHNICAL_DESIGN.md, src/acme_agent/web/static/app.js, src/acme_agent/web/static/styles.css, src/acme_agent/web/static/pcm-recorder.js, src/acme_agent/web/static/pcm-player.js, src/acme_agent/web/app.py]
parent: null
---

# SPEC-009 — Browser client with live captions and profile panel

## Problem & Scope
A single static page where a candidate talks to Ana: start/end controls, microphone capture to 16 kHz PCM16, playback of 24 kHz PCM with barge-in flush, live captions, and a panel showing the candidate profile filling in and the final summary/status — the main visual for the demo.

## Non-goals
- Recruiter dashboard or list of past interviews.
- Build tooling, frameworks or npm (ADR-013.1).
- Mobile app.

## Functional Requirements
- Landing state: Acme Burgers branding (fictional), short explanation, privacy note, *Start interview* button.
- Start: `POST /api/interviews`, open the WebSocket, request microphone, send `start` with `navigator.language`.
- Capture: AudioWorklet recorder downsampling to 16 kHz mono PCM16, sending ~100 ms binary frames.
- Playback: AudioWorklet player with a ring buffer at 24 kHz; on `interrupted` flush the buffer immediately.
- Captions: candidate and Ana turns, partial text updating in place, final text fixed.
- Profile panel: one row per slot with status (empty, filled ✓ with normalised value, invalid !, unresolved ?), rider-only rows appear when activated, progress bar from `progress`.
- End: *End interview* sends `end`; on `ended` show "Processing…", on `completed` show one neutral line (a declined consent gets its own line saying nothing was stored), headline and key points when the server provides a candidate-facing summary, and the status pill with reasons only inside a collapsed "Demo: recruiter view" panel (constitution: the assistant never tells a candidate they passed or failed).
- Errors: mic denied, socket closed, `error` messages → clear text explaining what to do.
- Optional small text box to type an answer (sends `text`).
- Works at phone width; keyboard accessible; respects reduced motion; light and dark themes.

## Technical Requirements
- Plain ES modules and CSS under `web/static/`, served by FastAPI `StaticFiles` at `/` (ADR-013.1).
- No credentials or model names in client code (ADR-013.2); the only server contract is TECHNICAL_DESIGN §2.
- Audio worklets loaded from same origin; `AudioContext({sampleRate: 16000})` for capture where supported, otherwise resample in the worklet.
- Total static payload < 100 KB.

## Acceptance Criteria
- In Chrome and Safari (desktop) and Chrome Android, a full interview can be held by voice, captions appear, the profile fills in live and the summary shows at the end (manual QA script in Verification).
- Speaking over Ana stops her playback within ~300 ms (manual).
- Mic-denied and server-down states show actionable messages (manual).
- No horizontal scroll at 375 px width; all controls reachable by keyboard.
- `grep -ri "gemini\|api_key\|token" src/acme_agent/web/static` returns nothing.

## Dependencies & Risks
- Safari AudioWorklet and sample-rate quirks: resample in the worklet and test early.
- Autoplay policies: audio starts only after the *Start* click.

## Plan
Build audio worklets first and test them against SPEC-008's server with the console open; then captions, then the profile panel driven by `slot` messages, then end/summary states and error handling; finish with styling and the manual QA script.

## Tasks
- [x] Write `pcm-recorder.js` worklet (downsample to 16 kHz PCM16, 100 ms frames)
- [x] Write `pcm-player.js` worklet (24 kHz ring buffer, flush)
- [x] Write `app.js` (session start, socket, message handling, state machine of the page)
- [x] Write `index.html` and `styles.css` (layout, captions, profile panel, status pill, themes)
- [x] Mount static files in `web/app.py`
- [x] Write manual QA script and run it on three browsers

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 17:30 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 317f9b1
- plan: one swe dispatch for worklets + app.js + html/css + static tests, then tech-lead browser checks (375 px, keyboard, themes, error states) in the built-in browser and a manual QA script for the human (voice on Chrome/Safari/Android)
- carried over from SPEC-008: mic capture with `echoCancellation`, `noiseSuppression`, `autoGainControl` on (the human heard Ana through open-ear earbuds); a visible "Connecting…" state until Ana's first audio (greeting 3–4 s, ~11 s cold); ids are single-use, so a dropped socket ends the interview → page shows "connection lost" and offers to start a new interview (no reconnect in the PoC)

### 2026-10-18 17:36 [anton-team] iteration 1 — client build + browser check
- swe (sonnet): done · commit 57df5dc · static/{index.html, styles.css, app.js, pcm-recorder.js, pcm-player.js} (~31 KB), tests/web/test_static.py (9) · 955 passed; node recorder test (48 kHz sine → 3200-byte frames, 440 Hz preserved)
- tester (tech-lead, built-in Chromium, served on :8001 with matching ACME_ALLOWED_ORIGINS, fake silent mic stream): landing at 375 px no horizontal scroll (scrollWidth 375); Tab focuses Start with a visible ring; dark and light themes; connecting state shown until the greeting (9.6 s cold start); live view: Ana greeting caption (en from navigator.language), typed answer "Yes, I agree. I want to apply as a rider." → consent + role filled ✓, progress bar moved, rider rows present; End → summary view with status pill "Needs human review"; error states: origin rejected (1008) → "could not be opened", mic NotAllowedError → allow-mic message, POST failure → "could not reach the interview service"
- findings: [major] profile panel shows raw canonical values ("true", "delivery_rider", day:shift lists) → needs display formatting per language · [minor] /favicon.ico 404 on every load
- deviations: `state` frames carry no progress → bar driven by `slot` messages; `completed.summary` is null until SPEC-010 → summary view falls back to a generic line + status pill

### 2026-10-18 17:42 [anton-team] iteration 2 — readable values + review round 1
- swe (sonnet): done · commit 2334cd5 · static/format.js (pure `formatValue`, node-tested; app.js re-exports), data-URI favicon · 957 passed · browser re-check: Yes / Delivery rider / Mornings: Mon, Tue, Wed, Thu, Fri / 25 h/week; store still shows its id
- reviewer: REVISE · [major] Ana's goodbye is cut off on model-ended interviews (client flushes on `ended` and closes the play context on `completed` while audio is still buffered) · minors: recorder carry-over sample never used (44.1 kHz boundary error, no anti-alias), focus lost after Start, no player worklet test, captions aria-live re-announces partials + progressbar label, no `ping`, Firefox sample-rate NotSupportedError, rider rows stay after role correction, unused CSS, log/touches for format.js
- tech-lead decisions: (1) constitution over spec — the candidate summary shows one neutral line for every status ("A person from the hiring team will review your application and contact you"); status pill and reasons move into a collapsed, clearly labelled "Demo: recruiter view" panel with neutral colours (ADR-009 decision text, principle 4 "never rejects"); (2) store names come from the server: optional `display` on `SlotMessage`, filled from knowledge/stores.json, documented in TECHNICAL_DESIGN §2 (touches extended: web/protocol.py, web/session.py, docs/TECHNICAL_DESIGN.md, static/format.js); (3) `ping` stays optional — mic frames keep the socket busy; §2.1 updated; (4) server-sent slot list/labels → follow-up, not this spec

### 2026-10-18 17:46 [anton-team] iteration 3 — review round 1 fixes
- swe (sonnet): done · commits 6fda117 (SlotMessage.display from the store catalogue, §2 docs, ping optional), a4ad1ff (drain-on-complete, flush on `ended` only after user End, neutral summary + collapsed "Demo: recruiter view", focus moves, sr-only live region for final turns, progressbar label, Firefox NotSupportedError retry, rider rows hide on non-rider role, recorder carry-over + [1 2 1]/4 anti-alias with 44.1 kHz node test, player node tests)
- tester: tech-lead re-run → 961 passed · browser (Chromium, served :8001, real Gemini, typed answers): declined consent → Ana "I understand. Thank you for your time. Goodbye." then ended+completed at 11.7 s, capture ctx closed at once, playback ctx closed 2.25 s later (drained, goodbye not cut) · consent+kitchen+Chamberí → rows "Yes", "Kitchen team", "Acme Burgers Chamberí"; End → neutral line, collapsed recruiter panel, focus on h1
- note for SPEC-012/013: on declined consent Ana says goodbye without pointing to the recruiter contact the FAQ promises (prompt wording)

### 2026-10-18 17:49 [anton-team] iteration 4 — review round 2
- reviewer (round 2): APPROVE · all 9 round-1 findings fixed; decisions (neutral summary + demo recruiter panel, server-side store display, optional ping) sound; 961 passed, ruff/mypy clean, payload 39.5 KB
- minors fixed · swe commit 9564eff · declined-consent summary line ("Nothing from this conversation has been stored…", node-tested `declinedLine`), rider rows hidden on any non-rider role · Functional Requirement on `completed` amended to the logged decision
- open minors (accepted): Firefox retry context created after an await (Firefox not in criteria); language switch on the summary page may reset the declined line
- follow-ups: slot list/labels from the server; SPEC-010 headline must be candidate-facing with no verdict (or go into the demo panel); declined-consent goodbye should point to the recruiter contact (SPEC-012/013 prompt)
- tester: tech-lead re-run → 962 passed
- status: implemented; verified after the human runs the manual QA script (real mic on Chrome, Safari, Chrome Android; barge-in) — script in docs/QA_BROWSER.md

### 2026-10-18 18:35 [anton-team] iteration 5 — human request — language selector
- human: "it works well, can we add a button to select the language to start"
- swe (sonnet): done · commit 25aec91 · landing segmented radio "Español / English" (default from navigator.language via node-tested `pickDefaultLanguage`, remembered in localStorage), switches page copy and <html lang>; `start` sends es-ES / en-US; session test es-ES → Spanish greeting, en-US → English
- tester: tech-lead re-run → 1010 passed · browser 375 px: selecting Español switches all copy, lang="es", scrollWidth 375

### 2026-10-19 11:05 [anton-team] iteration 6 — human test — error text not localized
- human test (es selected): "Algo ha salido mal" with the server's English error text; tech-lead reproduced on :8001 → `session_task_failed` RefreshError 1.5 s after start (expired Application Default Credentials needing reauthentication, not a language issue) → human to run `gcloud auth application-default login`
- swe (sonnet): done · commit 01b0de2 · client shows its own en/es text for known error codes (`session_failed`, new distinct `session_failed_unsaved`), server text only for unknown codes; `session_task_failed` logs `hint="run: gcloud auth application-default login"` on RefreshError / DefaultCredentialsError (candidate message stays generic) · test_expired_credentials_log_operator_hint
- tester: tech-lead re-run → 1033 passed

### 2026-10-19 12:39 [anton-team] iteration 7 — human requests — orb UI, stale cache
- human: email / languages rows still visible; hide the chat unless the candidate chooses to read or type; a pulsing orb, red while Ana speaks and blue while the candidate speaks
- cause of the visible rows: the browser kept the pre-change ES modules (no Cache-Control) → static mount now sends `Cache-Control: no-cache` (ETag revalidation); one hard reload needed once
- swe (sonnet): done · commit a5f6109 · orb driven by player / mic RMS levels from the worklets (pure `orbState` / `orbIntensity`, node-tested; agent wins over mic; 500 ms hold; thresholds 0.02 / 0.04), status line "Ana está hablando… / Te escucho… / Esperando tu respuesta…" (aria-live on state change only), captions and text box hidden behind "Mostrar conversación" / "Escribir", reduced motion = colour only
- tester: tech-lead re-run → 1055 passed · browser 375 px after one forced reload: Cache-Control no-cache on app.js; orb red + "Ana está hablando…" during the greeting, then "Esperando tu respuesta…"; optional rows hidden; scrollWidth 375 · blue state (real mic) and echo not turning it blue → human check

### 2026-10-19 12:54 [anton-team] iteration 8 — human test — 'frame is not a JSON object'
- human: session ended with "frame is not a JSON object"
- cause: version skew — the browser kept the pre-orb app.js (cached before the no-cache header) and loaded the new pcm-recorder.js; the old app.js forwarded the worklet's `{level}` messages to the socket as text frames → server ProtocolError
- swe (sonnet): done · commit eb06033 · worklets post levels only after `{levels: true}` from app.js (old clients never see them); worklet URLs versioned `?v=APP_VERSION` (bump when a worklet changes); server logs `bad_frame` (code, reason, no content)
- tester: tech-lead re-run → 1055 passed · human: one hard reload (Cmd+Shift+R) clears the stale app.js

### 2026-10-19 14:16 [anton-team] iteration 9 — human request — final view
- human: final view should show all the information and whether it was complete; remove "Requiere revisión humana"
- swe (sonnet): commit dccf578 · `completed` frame carries `profile` (slot → value, display, status, required) and `complete`; recruiter panel: completeness line, end reason, full profile with readable values ("—" when missing), tone, English summary; status pill and reasons removed from the client
- tester: tech-lead browser run (typed answers, real Gemini, End after 3 turns): "Entrevista incompleta · Terminada antes por el candidato", profile Puesto Equipo de cocina / Nombre Daniel Pérez / Teléfono +34612345678 / Tienda Acme Burgers Chamberí / rest "—", tone line, summary

### 2026-10-19 14:37 [anton-team] human QA — voice check
- human: voice testing across several calls (2026-10-19), issues found were fixed in the follow-ups above; final confirmation "Todo bien"
- status: verified (on main, no PR)

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Full voice interview, captions, live profile, summary: Chrome desktop | manual: tech-lead Chromium run (typed answers, fake mic, real Gemini); real-mic per QA script A | pass (Chromium typed + human voice QA 2026-10-19) | iterations 1 and 3: greeting caption, rows "Yes", "Kitchen team", "Acme Burgers Chamberí", neutral summary, goodbye drained 2.25 s |
| Same, Safari desktop | manual (QA script A) | pass (human voice QA 2026-10-19) | — |
| Same, Chrome Android | manual (QA script A) | pass (human voice QA 2026-10-19) | — |
| Barge-in stops Ana within ~300 ms | manual (QA script B), real mic; flush unit-tested | pass (human voice QA 2026-10-19) | tests/web/test_static.py::test_player_flush_overflow_resample_and_drained |
| Mic-denied and server-down states show actionable messages | manual (tech-lead browser) | pass | iteration 1: NotAllowedError, POST failure, 1008 rejection |
| No horizontal scroll at 375 px; all controls reachable by keyboard | manual (tech-lead browser) | pass | iteration 1: scrollWidth 375, visible focus ring; iteration 3: focus moves to the summary h1 |
| `grep -ri "gemini\|api_key\|token" src/acme_agent/web/static` returns nothing | command + test | pass | grep rc=1; tests/web/test_static.py::test_no_forbidden_words_in_static |
| Payload < 100 KB, no external URLs | test | pass | test_total_payload_under_100_kb (≈40 KB), test_index_has_no_external_urls |
| Capture 16 kHz PCM16 100 ms frames; 24 kHz playback with flush | test (node) | pass | test_recorder_resamples_to_16khz_pcm16_frames, test_recorder_44k_blocks_are_continuous, test_player_flush_overflow_resample_and_drained |
