---
id: ADR-001
title: Business domain: Acme Burgers frontline hiring
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-001 — Business domain: Acme Burgers frontline hiring

## Context
The proof of concept needs a concrete business and agent function. Frontline hiring
(restaurants, retail, logistics) suits voice agents: very high volume, hourly roles,
candidates who apply from their phone at any hour, and multilingual workforces. It also
exercises every capability we want to prove: conditional slot collection, messy spoken
input, knowledge questions, frustration, two languages, and regulatory sensitivity.

## Decision
**Acme Inc. = Acme Burgers**, a quick-service restaurant chain with stores in Spain and
Mexico hiring `crew_member`, `kitchen` and `delivery_rider` roles. The agent, **Ana**,
runs a 3–5 minute voice screening interview and produces a candidate record for a
recruiter.

## Rules
- **ADR-001.1** — Business content (roles, stores, FAQ text, pay ranges) lives in
  `knowledge/` files or `interview/slots.py`; it is never hard-coded in prompts or other
  Python modules.
  _Check:_ grep `src/acme_agent/` for store names / euro amounts from `knowledge/`; only
  `interview/slots.py` and knowledge loaders may reference them.
- **ADR-001.2** — Roles are the closed enum `crew_member | kitchen | delivery_rider`;
  adding a role means updating the enum, the synonym map and the role-specific slot
  conditions together.
  _Check:_ `domain/models.py` `Role` enum; tests in `tests/unit/test_validators.py` cover each role's synonyms.

## Consequences
- Hiring raises compliance duties (see ADR-009) that a support bot would not.
- An employee check-in or absence-reporting agent is a natural follow-up on the same engine.

## Alternatives considered
- **Customer support agent** (order number, category, urgency) — rejected: generic, fewer
  conditional fields, no compliance dimension.
- **Appointment scheduling agent** — rejected: dominated by calendar integration rather than conversation.
- **Employee check-in agent** — deferred: good follow-up, but screening is the higher-volume use case.
