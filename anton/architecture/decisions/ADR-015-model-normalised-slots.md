---
id: ADR-015
title: Hybrid slot normalisation — model normalises meaning, code validates
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: [ADR-005]
superseded_by: null
---

# ADR-015 — Hybrid slot normalisation: model normalises meaning, code validates

## Context
ADR-005 had the model pass the candidate's near-verbatim words and made hand-written
Spanish/English parsers turn them into typed values. Building SPEC-003 showed the cost:
two review rounds of realistic, messy input kept finding parsers that return a **wrong
value with full confidence** (principle 3) — negation ("I can't do mondays" → Mondays,
"lunes no, martes sí" → Monday), idioms ("no worries" → No, which would end the call on
the consent slot), contractions, ages counted as experience, invented days of the month.
Fixing each case uncovers the next, while blanket negation checks cause over-rejection
(extra turns, principle 1). Understanding negation, idioms and relative expressions is
exactly what the LLM already does well; deterministic code is better at *checking*
values than at *understanding* speech.

Some fields are the other way round: phone numbers, emails, store names and personal
names are better handled by deterministic code (digit handling, `phonenumbers`, fuzzy
matching against the store list), and the model tends to reformat or "correct" them.

## Decision
Split slots into two classes.

- **Canonical slots** — `consent_recording`, `right_to_work`, `is_18_or_over`,
  `driving_licence`, `own_vehicle`, `role`, `availability`, `start_date`, `weekly_hours`,
  `experience_months`, `languages`, `experience_summary`. The model passes the value in a
  documented **canonical format**; code validates it strictly and applies the business
  limits. No natural-language interpretation in code.
- **Verbatim slots** — `full_name`, `phone`, `email`, `preferred_store_id`. The model
  passes the candidate's words; the existing deterministic parsers normalise them
  (ADR-005's guarantees carry over).

`record_field(field, value, said)`: `value` is the canonical value (canonical slots) or
the candidate's words (verbatim slots); `said` is always the candidate's words, stored as
`slot_meta.raw` for audit. One tool, so ADR-016.3 (≤ 5 tools) still holds.

The existing natural-language parsers for canonical slots are kept as **advisory
cross-checks**: their reading of `said` is stored in `slot_meta.cross_check` and counted in
metrics/evals, but never changes a value, a status or the flow.

| Slot | Canonical format | Validation in code |
| --- | --- | --- |
| bool slots | `yes` \| `no` | exact token |
| `role` | `crew_member` \| `kitchen` \| `delivery_rider` | enum |
| `availability` | comma list of `day:shift`, e.g. `mon:morning,sat:night` | day ∈ mon..sun, shift ∈ morning/afternoon/night, ≥ 1, de-duplicated |
| `start_date` | `YYYY-MM-DD` | today ≤ d ≤ today + 90 |
| `weekly_hours` | integer | 10–40 |
| `experience_months` | integer | 0–600 |
| `languages` | comma list of ISO 639-1 codes | known codes, ≥ 1 |
| `experience_summary` | short text written by the model | trimmed to 300 chars, control chars removed, non-empty |

## Rules
- **ADR-015.1** — Every `SlotName` is registered exactly once, either in `CANONICAL` (strict
  format validator) or in `VERBATIM` (deterministic parser), both exported from
  `domain/validators/`; the class of each slot matches the table above.
  _Check:_ unit test asserting the two registries partition `SlotName` and match the table.
- **ADR-015.2** — Canonical validators accept only the canonical format and never interpret
  natural language; anything else returns `Issue(code="bad_format", hint=<expected format>)`.
  _Check:_ tests feed natural-language strings ("next monday", "sí claro") to every canonical validator and expect `bad_format`.
- **ADR-015.3** — Business limits (date window, hour and month ranges, rider rules) are
  enforced in code on canonical values, using `ParseContext` (pure, no clock).
  _Check:_ boundary tests per canonical slot; grep for `date.today`/`datetime.now` in `domain/`.
- **ADR-015.4** — Every `record_field` call carries `said`, and the controller stores it as
  `slot_meta[slot].raw`.
  _Check:_ tool signature in `agent/tools.py`; controller test asserts `raw` is stored.
- **ADR-015.5** — Cross-check parsers are advisory: their result is written only to
  `slot_meta[slot].cross_check` and metrics; it never changes a slot value, the screening
  status, a `next_goal`, or triggers a re-ask.
  _Check:_ controller test where the cross-check disagrees with the canonical value and the stored value and flow are unchanged.
- **ADR-015.6** — The model receives today's date and weekday (in the interview's timezone)
  at session start, and every canonical slot's format is stated in the tool description
  and in the `invalid` hint.
  _Check:_ session/text-mode start sends a date note; tool docstring lists the formats; prompt test.
- **ADR-015.7** — Verbatim parsers keep ADR-005's guarantees: pure, never raise on candidate
  input, return `Issue(code, hint)`, and have ≥ 3 Spanish, ≥ 3 English passing and ≥ 2
  failing tests each.
  _Check:_ `tests/unit/test_validators*.py`; garbage-input test.
- **ADR-015.8** — Post-call extraction (SPEC-010) asks for the same canonical formats plus the
  quoted words, and runs them through the same `CANONICAL`/`VERBATIM` registries.
  _Check:_ `analysis/schemas.py` and `analysis/post_call.py` use the registries.

## Consequences
- Negation, idioms, contractions and relative dates become the model's job; code checks the
  result. The re-ask loop handles format mistakes.
- Normalisation is no longer deterministic for canonical slots; quality is measured by the
  persona evals (SPEC-014) and the advisory cross-check mismatch rate.
- The model must know "today" to resolve relative dates (ADR-015.6).
- Natural-language parsers for canonical slots are no longer on the critical path; their
  remaining weaknesses only affect advisory cross-check signals.
- Tool contract changes for SPEC-005 (controller), SPEC-007 (tools and prompt) and SPEC-010
  (post-call schemas); docs updated accordingly.

## Alternatives considered
- **Keep ADR-005 (rule-based parsing of verbatim words for every slot)** — rejected: two
  review rounds showed recurring wrong confident values; the rule surface for ES/EN speech
  does not converge.
- **Model normalises every slot, including phone/email/store/name** — rejected: the model
  tends to reformat digits and spellings and cannot match the store list reliably;
  deterministic code is better there.
- **Typed per-field tools (one tool per slot)** — rejected: breaks the ≤ 5 tools rule
  (ADR-016.3) and native-audio tool-call reliability drops with many tools.
