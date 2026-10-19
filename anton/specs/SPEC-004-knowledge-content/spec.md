---
id: SPEC-004
title: Acme Burgers knowledge content: FAQ and stores
status: verified
mode: task
origin_type: technical
origin: Candidates ask job questions mid-call and must get answers grounded in Acme's FAQ, or a recruiter follow-up when the FAQ has no answer.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-001, ADR-007, ADR-012, ADR-009]
supersedes: []
superseded_by: null
depends_on: [SPEC-001]
touches: [knowledge/faq_es.md, knowledge/faq_en.md, knowledge/stores.json, knowledge/README.md]
parent: null
---

# SPEC-004 — Acme Burgers knowledge content: FAQ and stores

## Problem & Scope
Write the fictional Acme Burgers knowledge base used by the store validator and the FAQ retriever: `knowledge/stores.json` (12 stores across Madrid, Barcelona, Valencia, Ciudad de México and Guadalajara with id, name, city, area, country, address) and `knowledge/faq_es.md` / `knowledge/faq_en.md` with the same ~25 `## ` sections, each with a stable id comment (`<!-- id: pay-crew -->`). Topics: pay per role and country, contract types, shifts and hours, weekly hours, uniforms and meals, training, career progression, rider vehicle and insurance, tips, hiring process steps and timeline, documents needed on day one, store locations, accessibility, data privacy and how to delete data, how to contact a recruiter. Content is clearly fictional and plausible; amounts in EUR for Spain and MXN for Mexico. `knowledge/README.md` explains the format and that the content is fictional.

## Acceptance Criteria
- `stores.json` is valid JSON with 12 stores, unique ids (kebab-case, e.g. `vlc-ruzafa`), and at least two stores in Madrid (to exercise ambiguity).
- Both FAQ files have the same set of section ids in the same order (ADR-012.1).
- Every section is ≤ 80 words so one chunk answers one question.
- No real company names or real addresses are used.

## Plan
Draft the English FAQ first, then translate to natural Spanish (Spain register, with Mexico-specific notes where pay differs). Keep ids identical.

## Tasks
- [x] Write `knowledge/stores.json`
- [x] Write `knowledge/faq_en.md` with section ids
- [x] Write `knowledge/faq_es.md` with the same ids
- [x] Write `knowledge/README.md`

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 13:32 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 830f270
- plan/tasks: pre-existing (task mode)

### 2026-10-18 13:36 [anton-team] iteration 1 — T1–T4 stores, bilingual FAQ, README (+ content checks)
- swe (sonnet): done · commit 1714e62 · files: knowledge/stores.json, knowledge/faq_en.md, knowledge/faq_es.md, knowledge/README.md, tests/unit/test_knowledge_content.py
- tester (sonnet, full): PASS with advisory · 652 passed; 12 stores = conftest rows; 26/26 section ids equal in order; max 63/67 words; pay ranges equal EN/ES; Spanish natural · advisory: all addresses used real streets + numbers (one likely a real mall) → criterion "no real addresses" not met; "after 18:00" vs inclusive code → fed back to swe
- deviations: swe report was empty; results taken from the commit and the tester run

### 2026-10-18 13:36 [anton-team] iteration 2 — invented addresses, inclusive night wording
- swe (sonnet): done · commit 20951f2 · files: knowledge/stores.json (invented food-themed streets), knowledge/faq_en.md, knowledge/faq_es.md, knowledge/README.md, tests/unit/test_knowledge_content.py (real-street denylist test)
- tester: PASS (tech-lead re-run) · `uv run pytest -q` → 653 passed; all addresses invented; "from 18:00" / "a partir de las 18:00"
- deviations: none

### 2026-10-18 13:38 [anton-team] review round 1
- reviewer: REVISE · all 4 acceptance criteria met; content contradicts constitution/ADRs: [blocker] FAQ says a date of birth is asked (fair-screening constraint, ADR-009.3; slot is yes/no `is_18_or_over`); [major] "under 18 → cannot continue" describes automatic rejection (ADR-009); [major] "recordings kept 6 months" vs configurable retention (default 30 days) and transcript-not-audio · minors: stored-data list incomplete (sentiment), bicycle vs rider licence rule, "store list" the candidate cannot see; note: ES pay floor 9.00 EUR/h may be below the real minimum wage — drop the legal claim and raise the floors; avoid "in this proof of concept" in candidate-facing text

### 2026-10-18 13:40 [anton-team] iteration 3 — review round 1 fixes
- swe (sonnet): done · commit d4ef860 · files: knowledge/faq_en.md, knowledge/faq_es.md (minimum age: only "18 or over" asked, recruiter reviews every application; retention "30 days by default", transcript not audio; stored-data examples + tone scoring; no bicycle; store list via assistant/careers page; Spain pay floors raised, minimum-wage claims removed; no "proof of concept" wording), tests/unit/test_knowledge_content.py (forbidden-phrase and EN/ES pay-equality tests)
- tech-lead: content edits — removed "fictional stores"/"locales ficticios" from candidate-facing text (README keeps the fictional notice); Spanish frustration sentence made gender-neutral
- tester: tech-lead re-run first showed 1 failure (faq_es.md:privacy-recorded at 81 words after the tech-lead's wording edit; committed by mistake in f964880) → shortened the sentence; re-run → 656 passed

### 2026-10-18 13:42 [anton-team] review round 2
- reviewer: APPROVE · round-1 findings fixed; content consistent with code (shift windows, 10–40 h, 90-day start, 30-day retention, no audio, tone scoring, eligibility slots); still clearly fictional without a candidate-facing notice · minors: screening "ten minutes" vs designed 3–5; rider licence "one year" not screened; "you need your own vehicle" vs FLAG_NO_VEHICLE; README line outdated; add ADR-009 to decisions
- tech-lead: applied all minors (about five minutes; licence clause dropped; vehicle wording softened; README updated; ADR-009 added to `decisions:`) · `uv run pytest -q` → 656 passed; ruff clean

### 2026-10-18 13:42 [anton-team] implemented
- PR: not opened — project builds directly on `main` (commits 830f270..HEAD); 656 tests and lint green

### 2026-10-18 13:42 [anton-team] verified (on main, no PR)


## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| `stores.json` is valid JSON with 12 stores, unique ids (kebab-case, e.g. `vlc-ruzafa`), and at least two stores in Madrid (to exercise ambiguity). | test | pass | tests/unit/test_knowledge_content.py::test_stores_valid_and_match_fixture; 656 passed |
| Both FAQ files have the same set of section ids in the same order (ADR-012.1). | test | pass | test_faq_ids_match_across_languages (26 ids, identical order) |
| Every section is ≤ 80 words so one chunk answers one question. | test | pass | test_faq_sections_short[faq_en.md], [faq_es.md] |
| No real company names or real addresses are used. | test + manual | pass | test_store_addresses_use_no_real_street_names, test_only_example_domains; manual read (invented food-themed streets, `.example` domains only) |
