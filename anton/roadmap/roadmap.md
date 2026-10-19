# Roadmap

This project plans without epics or stories: every spec is a technical spec whose
`origin` states the user need, and specs carry `depends_on`, so the build order below
is derived from the spec graph.

| Epic | Title | Status | Priority |
| --- | --- | --- | --- |

## Build waves

Derived from `depends_on`. Specs in the same wave can be built in parallel; where they
touch the same files (noted) the manager should stack or sequence them.

| Wave | Specs | Outcome | Shared files |
| --- | --- | --- | --- |
| 1 | SPEC-001 | Project skeleton, tooling, config, logging | — |
| 2 | SPEC-002, SPEC-004 | Domain model + screening rules; knowledge content | — |
| 3 | SPEC-003, SPEC-006 | Validators; conversation repository | — |
| 4 | SPEC-005 | Interview controller | — |
| 5 | SPEC-007 | Tools, prompt v1, text-mode agent (`acme-agent chat`) — **first demoable core** | — |
| 6 | SPEC-008, SPEC-010, SPEC-011, SPEC-015 | Live voice session; post-call processing; FAQ retrieval; returning candidates | `bootstrap.py`, `cli.py`, `agent/tools.py` |
| 7 | SPEC-009, SPEC-012, SPEC-013, SPEC-014 | Browser client; sentiment & escalation; bilingual hardening; persona evals | `web/session.py`, `agent/text.py` |
| 8 | SPEC-016, SPEC-017 | Cloud Run deployment; README and demo | — |

**Core (must have):** SPEC-001 … SPEC-010.
**Stretch:** SPEC-011 (RAG), SPEC-012 (sentiment), SPEC-013 (bilingual), SPEC-014 (evals),
SPEC-015 (returning candidates), SPEC-016 (Cloud Run).
**Last:** SPEC-017 only needs the core, but run it after whichever stretch specs are
built so the README is accurate. Cancel stretch specs that will not be built
(`/anton-core:advance SPEC-NNN cancelled`) rather than leaving them in draft.
