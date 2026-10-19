---
id: SPEC-017
title: README, demo script and demo recording
status: implemented
mode: task
origin_type: request
origin: Make the project understandable and runnable by anyone cloning it, and capture a demo of the agent's capabilities.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-010, ADR-014]
supersedes: []
superseded_by: null
depends_on: [SPEC-009, SPEC-010]
touches: [README.md, docs/DEMO.md, docs/images/]
parent: null
---

# SPEC-017 — README, demo script and demo recording

## Problem & Scope
Write the top-level `README.md` once the core is in place: what Acme Agent is (a personal proof of concept), a screenshot/GIF of the browser client, quick start (`uv sync`, `gcloud auth application-default login`, `.env`, `make serve`, `make chat`), architecture overview with a link to `docs/DESIGN.md` and the ADRs, key design decisions table, how to run tests and evals, project layout, limitations and potential improvements (from DESIGN §19), and links to the demo video. Write `docs/DEMO.md` with the demo script: happy path in Spanish (rider), a correction, an FAQ question, an invalid phone, a language switch to English, and an escalation; record the demo and link it. Run last, reflecting whichever stretch specs were implemented.

## Acceptance Criteria
- Following only the README on a clean machine with GCP access, a new user can run tests, `make chat` and `make serve` successfully (dry run by a fresh clone).
- README lists implemented vs. not implemented stretch features accurately.
- `docs/DEMO.md` exists and the demo video link works.
- No mention of anything outside the project's own context (personal PoC framing); `grep -ri` for third-party company names returns nothing.

## Plan
Draft README sections from DESIGN.md, verify every command on a fresh clone, write the demo script, record, add the link.

## Tasks
- [x] Draft README.md
- [x] Capture screenshot/GIF into `docs/images/`
- [x] Write `docs/DEMO.md` demo script
- [x] Fresh-clone dry run of every README command
- [ ] Record demo video and add link

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-19 13:29 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 76d450b
- plan: swe drafts README.md + docs/DEMO.md (demo script reflecting what is built: orb UI, language selector, consent confirmation, FAQ + resume, correction, invalid phone, language switch, frustration → recruiter, silence goodbye, post-call summary in the recruiter panel, `acme-agent stats`) and a headless landing screenshot; tech-lead fresh-clone dry run; human records the video and captures the live screenshots
- implemented stretch features: FAQ RAG (SPEC-011), sentiment + escalation (SPEC-012), multi-turn memory, ES/EN (selector + mid-call switch); not implemented: SPEC-013 bilingual hardening, SPEC-014 persona evals, SPEC-015 returning candidate, SPEC-016 Cloud Run
- wording: personal proof-of-concept framing only; no third-party names

### 2026-10-19 13:33 [anton-team] iteration 1 — README, demo script, dry run
- swe (sonnet): done · commit 789d8a7 · README.md (222 lines: pitch, screenshots, features implemented / not, quick start + troubleshooting, mermaid architecture + package table, 12 key decisions, data and privacy, testing, measured numbers, layout, limitations and improvements), docs/DEMO.md (setup checklist + 8 scenes), docs/images/landing.png (+ landing-mobile.png) via headless Chrome
- tech-lead review of README: corrected three claims (per-field metadata fields, protected characteristics wording vs "18 or over", `purge --yes` dry-run default)
- tester (tech-lead, fresh clone in scratchpad): `uv sync`, `make test` 1089 passed, `make chat` real interview turns + saved record, `serve` GET / 200, POST /api/interviews ok · wording grep clean
- pending (human): docs/images/live.png and summary.png (referenced in the README), demo recording and its URL

### 2026-10-19 14:40 [anton-team] iteration 2 — screenshots
- tech-lead: live.png and summary.png captured from a real scripted interview (headless Chrome over CDP, silent mic, typed Spanish answers, real Gemini): live view with the red orb "Ana está hablando…" and the profile filling; final view "Entrevista completa · Completada" with the full profile, tone and summary (record completed)
- pending: demo recording URL (human)

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| Fresh clone: tests, `make chat`, `make serve` succeed following only the README | manual (tech-lead, clone in scratchpad, real GCP) | pass | `uv sync`; `make test` → 1089 passed; `.env` from `.env.example` + project id; `make chat` → Spanish greeting, consent + role filled, record saved with post-call summary; `acme-agent serve` → GET / 200 in 3 s, POST /api/interviews → id + ws_url |
| README lists implemented vs not implemented stretch features accurately | review | pass | README "Features": implemented list matches verified specs (SPEC-001…012, 018; 009 implemented); not implemented SPEC-013…016, `make eval` placeholder, gcs storage not wired |
| `docs/DEMO.md` exists and the demo video link works | manual | partial: DEMO.md pass; video pending human | docs/DEMO.md (setup checklist + 8 scenes); README "Demo video: coming soon" |
| No mention of anything outside the project's own context | command | pass | case-insensitive grep for third-party company names and hiring-process wording over README.md and docs/ → nothing |
