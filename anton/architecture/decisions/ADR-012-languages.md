---
id: ADR-012
title: Languages: Spanish and English with mid-call switching
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-012 — Languages: Spanish and English with mid-call switching

## Context
Acme operates in Spain and Mexico; candidates often prefer Spanish but may switch.

## Decision
Spanish and English, auto-detected, switchable at any time. Ana answers in the
candidate's language; validators and FAQ cover both; switches are logged. Recruiter
summaries are written in English.

## Rules
- **ADR-012.1** — Every FAQ section exists in both `faq_es.md` and `faq_en.md` with the same
  section id.
  _Check:_ unit test compares section ids of both files.
- **ADR-012.2** — Validators accept Spanish and English input (verbatim parsers: see ADR-015.7; canonical slots are normalised by the model in either language).
  _Check:_ as ADR-015.7.
- **ADR-012.3** — Language changes are recorded as `language_switched` events and in
  `record.language.switches`.
  _Check:_ session/text-mode test with a switching script.

## Consequences
- Adding a language = FAQ file + synonyms + tests.

## Alternatives considered
- **English only** — rejected: does not fit Acme's markets.
- **Language fixed at the start** — rejected: real candidates code-switch.
- **Many languages** — deferred: validation coverage would not be tested properly.
