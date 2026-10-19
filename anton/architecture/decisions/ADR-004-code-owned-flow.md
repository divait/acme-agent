---
id: ADR-004
title: Code-owned interview flow; LLM extracts through tool calls
status: superseded
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: ADR-016
---

# ADR-004 — Code-owned interview flow; LLM extracts through tool calls

## Context
An interview must reliably collect a fixed set of fields with validation, conditional
fields and retries, while sounding natural. Speech-to-speech models drift if they manage
the flow alone, and prompt-only designs are hard to test.

## Decision
A deterministic **`InterviewController`** (state machine over data-driven slot specs) owns
slots, order, conditions, retries, phases and completion. The model handles language and
reports data via `record_field`; every tool result returns `next_goal` and `missing`.

## Rules
- **ADR-004.1** — `acme_agent/domain/` and `acme_agent/interview/` import no I/O or LLM
  libraries (`google`, `fastapi`, `starlette`, `httpx`, `aiofiles`, `structlog` sinks,
  `os` file access) and no other project package except `domain`.
  _Check:_ grep imports in `src/acme_agent/domain/**` and `src/acme_agent/interview/**`; an import-boundary test in `tests/unit/test_architecture.py`.
- **ADR-004.2** — Slot values change only through `InterviewController` methods
  (`record`, `apply_reconciliation`, `prefill`); no other code assigns to slot state.
  _Check:_ grep for `.slots[` / `SlotState(` assignments outside `interview/controller.py`.
- **ADR-004.3** — The live model is given at most five tools: `record_field`,
  `search_faq`, `confirm_profile`, `escalate_to_human`, `end_interview`.
  _Check:_ unit test asserts `len(build_tools(c)) <= 5` and their names.
- **ADR-004.4** — Every `record_field` response includes `status`, `next_goal` and `missing`.
  _Check:_ controller unit tests cover all statuses and assert those keys.
- **ADR-004.5** — Slots, their order, conditions and `ask` texts are declared as data in
  `interview/slots.py`; the controller contains no per-field `if field == "..."` branches
  except the documented hooks (role activation, phone lookup).
  _Check:_ read `interview/controller.py`.

## Consequences
- Unit-testable flow; prompts stay short and stable.
- The model may still skip a tool call → covered by ADR-008.
- Controller can steer the session with `[SYSTEM NOTE]` messages for events the model did not cause.

## Alternatives considered
- **Prompt-only, extract at the end** — rejected: no live validation or re-asking, untestable flow.
- **LLM decides the flow, tools only store** — rejected: drift, no guaranteed completeness.
