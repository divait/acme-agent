---
id: ADR-008
title: Post-call extraction, reconciliation and structured summary
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-008 — Post-call extraction, reconciliation and structured summary

## Context
Recruiters need a summary with key points and a reliable record. Live tool calls from a
native-audio model can be missed (ADR-002).

## Decision
Live slots are primary. After the session, **Gemini Flash with structured output**
re-extracts raw values from the full transcript, the same parsers normalise them, a
reconciliation step merges them with live slots, deterministic rules compute the status,
and a structured summary is generated.

## Rules
- **ADR-008.1** — Post-call extracted values go through the same `domain/validators.py`
  parsers as live input before they are used.
  _Check:_ read `analysis/post_call.py`; test that an invalid extracted phone is not stored.
- **ADR-008.2** — Reconciliation never overwrites a valid live value: disagreement keeps the
  live value and adds a `reconciliation_conflict`; values filled post-call are marked `source: post_call`.
  _Check:_ unit tests for the four reconciliation cases (agree, fill, conflict, both missing).
- **ADR-008.3** — LLM outputs consumed by code use structured output (`response_schema`
  with a Pydantic model); no regex or ad-hoc JSON parsing of free text.
  _Check:_ grep `json.loads`/`re.search` on model output in `analysis/`.
- **ADR-008.4** — If post-call processing fails after retries, the record is still saved with
  `summary: null` and status `needs_human_review`.
  _Check:_ test with a failing fake model client.

## Consequences
- One extra text call per interview (negligible next to audio minutes).
- Post-call values were never confirmed by the candidate; their source is recorded.

## Alternatives considered
- **Trust live slots only** — rejected: silently loses data when a tool call is skipped.
- **Extract only after the call** — rejected: no validation or re-asking during the call.
