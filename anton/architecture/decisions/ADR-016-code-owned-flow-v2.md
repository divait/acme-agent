---
id: ADR-016
title: Code-owned interview flow v2 — documented hooks and a read-only goal query
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: [ADR-004]
superseded_by: null
---

# ADR-016 — Code-owned interview flow v2: documented hooks and a read-only goal query

## Context
ADR-004 put a deterministic `InterviewController` in charge of the interview and let the
model only phrase questions and report data through tools. Building the controller
(SPEC-005) confirmed the approach but showed two gaps in its rules:

- ADR-004.5 allowed per-field hooks only for *role activation* and *phone lookup*. The
  controller also needs a **consent** hook (GDPR: nothing is stored before consent; a
  decline or withdrawal purges everything else — ADR-009.4) and a **store → country** hook
  (the session country decides how phone numbers are parsed, so a Mexican number works
  once a Mexican store is chosen).
- Review found that `next_goal()` silently changed the phase. Callers in the text and live
  sessions (SPEC-007/008) query the goal freely, so a query with side effects is a trap.

Everything else in ADR-004 stands unchanged. This ADR restates it with those two
corrections so the rules stay checkable.

## Decision
Keep the code-owned flow of ADR-004. The controller may branch on a field only in four
documented hooks — **consent gating/purge, role activation, store → session country,
phone lookup** — kept together in one place, and `next_goal()` (with the other read
methods) is side-effect-free; phase transitions happen only in mutating methods.

## Rules
- **ADR-016.1** — `acme_agent/domain/` and `acme_agent/interview/` import no I/O or LLM
  libraries (`google`, `fastapi`, `starlette`, `httpx`, `aiofiles`, `structlog`, `os` file
  access) and no other project package except `domain`.
  _Check:_ `tests/unit/test_architecture.py` import-boundary test; grep imports in `src/acme_agent/domain/**` and `src/acme_agent/interview/**`.
- **ADR-016.2** — Slot values and slot metadata change only through `InterviewController`
  methods (`record`, `prefill`, `apply_reconciliation`, the consent purge); no other code
  assigns to the controller's profile or slot state.
  _Check:_ grep for assignments to `.profile` / `.slot_meta` outside `interview/controller.py`.
- **ADR-016.3** — The live model is given at most five tools: `record_field`,
  `search_faq`, `confirm_profile`, `escalate_to_human`, `end_interview`.
  _Check:_ unit test asserts `len(build_tools(c)) <= 5` and their names.
- **ADR-016.4** — Every `record_field` response includes `status`, `next_goal` and `missing`.
  _Check:_ controller unit tests cover all statuses and assert those keys.
- **ADR-016.5** — Slots, their order, conditions and `ask` texts are declared as data in
  `interview/slots.py`; the controller contains no per-field branches except the four
  documented hooks — consent gating/purge, role activation, store → session country, phone
  lookup — which live together in one documented place.
  _Check:_ read `interview/controller.py`; per-field branches appear only in the hook section and the consent gate of `record`.
- **ADR-016.6** — `next_goal()`, `missing()`, `progress()` and `snapshot()` never change
  phase, slot state or events; phase transitions happen only inside `start()`, `record`,
  `confirm_profile`, `escalate`, `end` and `prefill`.
  _Check:_ unit test calling the read methods repeatedly between mutations and asserting phase and events are unchanged.

## Consequences
- The controller's per-field behaviour is fully enumerated; adding a hook requires a
  superseding ADR.
- Sessions call `controller.start()` before the first model turn and may query goals as
  often as they like.
- Rule IDs change from ADR-004.x to ADR-016.x; the rubric and open specs are updated.

## Alternatives considered
- **Keep ADR-004 and list the consent/store hooks as known deviations** — rejected: the
  hooks are intentional and required (GDPR, phone parsing), so recording them as deviations
  would mislabel correct code and leave the rule inaccurate.
- **Move consent and country handling out of the controller (into the session layer)** —
  rejected: consent gating must hold in text mode, live mode and tests alike; the
  controller is the only shared, unit-tested place.
