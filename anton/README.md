# anton/ — Spec-Driven Development tree

Managed by the anton-core plugin.

- `constitution/` — why the project exists and the rules every change respects.
- `architecture/` — current technical shape (overview, tech stack) and
  `decisions/ADR-NNN-slug.md`: architecture decisions with the checkable
  rules every change must follow.
- `research/RES-NNN-slug.md` — investigations that informed decisions.
- `roadmap/` — `roadmap.md` narrative (this project plans without epics).
- `stories/` — unused: this project writes technical specs only (the user need is each spec's `origin`).
- `specs/SPEC-NNN-slug/spec.md` — behavioral contracts with plan, tasks,
  implementation log and verification evidence as sections (lite profile).
- `indexes/` — generated views (`active.md`, `archived.md`); do not edit.

Lifecycle: draft → ready → in-progress → implemented → verified → archived
(plus cancelled / superseded). Transitions are gated — use
`/anton-core:advance`, and validate anytime with `/anton-core:validate`.

Decisions: record with `/anton-core:new-decision`, investigate first with
`/anton-core:research`. Accepted ADRs are law — to change a rule, supersede
the ADR.

Narrative design documents live in [`../docs/`](../docs/): `DESIGN.md` (what and why)
and `TECHNICAL_DESIGN.md` (how). When they and an accepted ADR disagree, the ADR wins.
