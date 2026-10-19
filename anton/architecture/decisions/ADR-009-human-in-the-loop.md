---
id: ADR-009
title: Human in the loop; deterministic screening status
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-009 — Human in the loop; deterministic screening status

## Context
AI systems used for recruitment are high-risk under the EU AI Act, and GDPR applies to
candidate data. Hiring outcomes must be explainable and overseen by people.

## Decision
`screening_status ∈ {meets_requirements, missing_requirements, needs_human_review}` is
computed by `domain/rules.py` from validated data. The agent never tells a candidate they
passed or failed. A recruiter always decides.

## Rules
- **ADR-009.1** — `screening_status` is set only by `domain/rules.py`; no LLM output is
  mapped to it.
  _Check:_ grep assignments to `screening`/`status` outside `domain/rules.py` and its callers in `analysis/post_call.py`.
- **ADR-009.2** — Each status carries the list of rules/knock-outs that produced it.
  _Check:_ rules unit tests assert `knockouts`/`flags` content.
- **ADR-009.3** — The system instruction forbids questions about nationality, religion,
  health, disability, pregnancy, family and exact age, and no slot collects such data.
  _Check:_ prompt test asserts the boundary text; slot list review; persona eval guardrail metric.
- **ADR-009.4** — Recording consent is the first slot; if declined, the stored record
  contains only metadata, the consent answer and `end_reason: declined_consent` (no transcript).
  _Check:_ controller and session tests for the declined path.

## Consequences
- Explainable outcomes; prompt injection gains nothing (the model has no decision power).
- Eligibility questions are yes/no only (`right_to_work`, `is_18_or_over`).

## Alternatives considered
- **LLM decides pass/fail** — rejected: unexplainable, non-compliant.
- **Automatic rejection on knock-outs** — rejected: removes human oversight.
