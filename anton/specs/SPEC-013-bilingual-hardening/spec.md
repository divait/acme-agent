---
id: SPEC-013
title: Bilingual Spanish/English hardening
status: ready
mode: task
origin_type: technical
origin: Candidates in Spain and Mexico must be able to interview in Spanish or English and switch language mid-call.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-015, ADR-012]
supersedes: []
superseded_by: null
depends_on: [SPEC-008, SPEC-011]
touches: [src/acme_agent/analysis/language.py, src/acme_agent/web/session.py, src/acme_agent/agent/text.py, src/acme_agent/agent/tools.py, tests/unit/test_language.py]
parent: null
---

# SPEC-013 — Bilingual Spanish/English hardening

## Problem & Scope
Make language handling observable and consistent: detect the language of each final candidate turn with `lingua-language-detector` restricted to ES/EN (minimum confidence and ≥ 3 words), keep `controller.language` and `ParseContext.language` in sync, log `language_switched` events and `record.language.switches`, make `search_faq` default to the current language, and run a Spanish-only, English-only and code-switching interview end to end in text and voice. Add any validator cases found missing during those runs.

## Acceptance Criteria
- Unit tests: detection on short ES/EN phrases, no switch on 1–2 word turns, switch event recorded once per change (ADR-012.3).
- `search_faq` without an explicit language uses the current interview language.
- Manual runs (ES, EN, switching) are recorded in Verification with record ids; Ana follows a switch on her next turn.

- Store matching tolerates ASR spelling variants of area names (e.g. "Chambéry, Madrid" → mad-chamberi) with an accent/spelling-tolerant fuzzy area match that still never guesses between two stores (follow-up from SPEC-008 live run).

## Plan
Add the detector behind a small `LanguageDetector` protocol, wire it where candidate turns finalise (session and text mode), then run the three manual scripts and patch validators/tests as needed.

## Tasks
- [ ] Add `lingua-language-detector` dependency and `analysis/language.py` + tests
- [ ] Wire detection into session and text mode; update `ParseContext.language`
- [ ] Default `search_faq` language to the interview language
- [ ] Run ES, EN and switching scripts in text and voice; add missing validator cases

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
