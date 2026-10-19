---
id: ADR-010
title: Shared core with text mode; testing strategy
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-010 — Shared core with text mode; testing strategy

## Context
Voice is slow and costly to test by hand, and prompt changes need fast feedback.

## Decision
Layered tests on a voice-independent core: **unit** (no network), **conversation**
(mocked model, scripted tool calls), **text mode** (`acme-agent chat`, same controller,
tools and prompt with a text Gemini model) and **persona evals** (simulated candidates,
opt-in).

## Rules
- **ADR-010.1** — The default `pytest` run needs no network or credentials; tests that call
  Vertex are marked `eval` or `live` and are excluded by default.
  _Check:_ `pyproject.toml` `addopts = "-m 'not eval and not live'"`; run tests with no ADC.
- **ADR-010.2** — Line coverage of `domain/` and `interview/` stays ≥ 90 %.
  _Check:_ `pytest --cov=acme_agent.domain --cov=acme_agent.interview --cov-fail-under=90`.
- **ADR-010.3** — Text mode and live mode share the same `InterviewController`, `build_tools`
  and system instruction; there is no text-only copy of flow logic.
  _Check:_ `agent/text.py` imports `build_tools` and `prompts.SYSTEM_INSTRUCTION`.
- **ADR-010.4** — Every spec that changes behaviour adds or updates tests for it.
  _Check:_ the spec's diff contains test changes.

## Consequences
- Evals approximate voice behaviour; manual voice QA scripts remain for the demo.
- Eval runs consume credits, so they are opt-in.

## Alternatives considered
- **Manual voice testing only** — rejected: slow, unrepeatable.
- **Helper unit tests only** — rejected: misses flow and prompt regressions.
