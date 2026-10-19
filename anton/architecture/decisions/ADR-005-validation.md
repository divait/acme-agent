---
id: ADR-005
title: Validation and normalisation in code
status: superseded
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: ADR-015
---

# ADR-005 — Validation and normalisation in code

## Context
Spoken answers are messy ("seis cero cero…", "el finde", "next Monday", "dos años y
medio"). We need typed values, deterministic behaviour and helpful re-ask hints.

## Decision
The model passes near-verbatim values; **parsers in `domain/validators.py`** normalise and
validate them using Pydantic v2, `phonenumbers`, `dateparser`, synonym maps and
`rapidfuzz`. Failures return `Issue(code, hint)`.

## Rules
- **ADR-005.1** — Every slot has exactly one parser `(raw: str, ctx: ParseContext) -> T | Issue`
  in `domain/validators.py`; prompts never instruct the model to reformat values.
  _Check:_ each `SlotSpec` references a parser from `domain.validators`; grep prompts for "format"/"E.164".
- **ADR-005.2** — Parsers never raise on candidate input; they return an `Issue` with a
  machine `code` and an English `hint`.
  _Check:_ parametrised tests feed garbage input to every parser and assert an `Issue`.
- **ADR-005.3** — Every parser has unit tests with both Spanish and English inputs.
  _Check:_ `tests/unit/test_validators.py` has ES and EN cases per parser.
- **ADR-005.4** — Parsers are pure: "today", country and store list come from `ParseContext`,
  never from the clock or files.
  _Check:_ grep `date.today`/`datetime.now`/`open(` in `domain/validators.py`.

## Consequences
- Small custom helpers (spoken digits) need maintenance and tests.
- Ambiguity (two matching stores) leads to a question instead of a guess.

## Alternatives considered
- **Trust LLM-normalised values** — rejected: non-deterministic, untestable.
- **LLM normalises, code checks shape** — rejected: still non-deterministic normalisation.
