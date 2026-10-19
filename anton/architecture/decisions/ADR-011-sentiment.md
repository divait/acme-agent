---
id: ADR-011
title: Sentiment analysis and escalation
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-011 — Sentiment analysis and escalation

## Context
A frustrated candidate should be offered a human or a later call rather than pushed
through. Sentiment must not slow the conversation.

## Decision
Each final candidate transcription triggers an **async Gemini Flash-Lite** score
`{score, frustration, reason}` over the last 3 turns. The escalation rule lives in the
controller (≥ 2 frustration flags in the last 4 turns, or an explicit request for a person).
Gemini Live affective dialog is enabled only as a tone complement.

## Rules
- **ADR-011.1** — Sentiment scoring is never awaited on the audio or tool path: it runs as a
  background task with a 3 s timeout and at most one call in flight per session.
  _Check:_ read `analysis/sentiment.py` and its call site; test that a slow fake model does not delay tool responses.
- **ADR-011.2** — The escalation decision is a controller rule, unit-tested; the model only
  phrases the offer.
  _Check:_ `InterviewController.on_sentiment` tests.
- **ADR-011.3** — Per-turn scores are stored on transcript turns and aggregated in `sentiment`.
  _Check:_ record test.

## Consequences
- Prosody is not used (text-only signal).
- One small text call per candidate turn.

## Alternatives considered
- **`report_sentiment` live tool** — rejected: adds tool noise to a model already weak at tool calls.
- **Affective dialog only** — rejected: not observable or testable.
- **Local transformer classifier** — rejected: model hosting for little gain.
