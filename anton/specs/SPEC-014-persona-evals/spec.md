---
id: SPEC-014
title: Persona evaluation harness
status: ready
mode: full
origin_type: technical
origin: Turn prompt and flow quality into numbers (slot precision/recall, turns, guardrail violations) so changes can be compared and reported.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-009, ADR-010, ADR-015]
supersedes: []
superseded_by: null
depends_on: [SPEC-007, SPEC-010]
touches: [tests/evals/, src/acme_agent/evals/, src/acme_agent/cli.py, docs/EVALS.md]
parent: null
---

# SPEC-014 — Persona evaluation harness

## Problem & Scope
Simulate candidates with an LLM playing defined personas against the text-mode agent and score the resulting records against hidden ground truth, producing a report that can be tracked over prompt versions.

## Non-goals
- Voice-level evaluation (latency, ASR errors) — covered by manual QA.
- Online evaluation of production traffic.

## Functional Requirements
- Personas in `tests/evals/personas/*.yaml`: ground-truth profile, language, behaviour notes, max turns. Six to start: happy rider (ES), confused cook (EN), rude candidate (ES), code-switcher, over-sharer (several fields per sentence), question-asker (FAQ heavy). Plus one adversarial persona that tries to make Ana skip consent or ask protected questions.
- Simulator: Gemini Flash plays the persona from its card, sees only Ana's replies, ends when Ana ends or max turns reached.
- Runner: `acme-agent eval [--persona NAME] [--repeat N]` runs `TextInterview` vs simulator, saves records under `data/evals/<run_id>/`.
- Scoring per run: slot precision and recall vs ground truth (normalised values), turns to completion, completion rate, correct screening status, guardrail violations (LLM-judge over Ana's turns with a fixed rubric: protected-characteristic questions, promises of jobs/salary, missing consent first).
- Report: markdown + JSON summary in `data/evals/<run_id>/report.md`, including prompt version and model ids; `docs/EVALS.md` explains how to run and read it and records the latest headline numbers.

## Technical Requirements
- (ADR-015) The report includes per-slot canonical-normalisation accuracy against ground truth and the advisory cross-check disagreement rate.
- Lives in `src/acme_agent/evals/` (importable by CLI) and `tests/evals/` (pytest entry marked `eval`, ADR-010.1).
- Judge and simulator use structured output schemas.
- Deterministic as possible: temperature 0 for judge, fixed seeds where supported; `--repeat` to measure variance.

## Acceptance Criteria
- `acme-agent eval --repeat 2` runs all personas and writes a report with per-persona and overall metrics.
- `pytest -m eval` runs one persona end to end and asserts the report is produced.
- On prompt `ana-v1` (or later), overall slot precision ≥ 0.95, recall ≥ 0.90, zero guardrail violations; if not met, gaps are recorded as follow-up work in the Implementation Log.
- `docs/EVALS.md` exists with instructions and the latest numbers.

## Dependencies & Risks
- Simulator drifting from its persona: include persona reminders every turn and cap turns.
- Cost: default `--repeat 1`, run on demand only.

## Plan
Persona schema and two personas first, simulator + runner, scoring, judge, report; then the remaining personas and a baseline run.

## Tasks
- [ ] Define persona schema and write seven persona files
- [ ] Implement simulator and runner over `TextInterview`
- [ ] Implement slot scoring and status check
- [ ] Implement guardrail judge
- [ ] Implement report writer and `acme-agent eval`
- [ ] Add `eval`-marked pytest entry
- [ ] Run baseline and write `docs/EVALS.md`

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
