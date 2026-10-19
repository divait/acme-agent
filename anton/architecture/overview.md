# Architecture Overview

Narrative and diagrams: [`docs/DESIGN.md`](../../docs/DESIGN.md) and
[`docs/TECHNICAL_DESIGN.md`](../../docs/TECHNICAL_DESIGN.md).

## Quality attributes
1. **Conversational responsiveness** — perceived response time from end of candidate
   speech to first agent audio ≈ 1–1.5 s (target; measured ≈ 2 s with the tool round trip —
   accepted bound ≤ 2.5 s, model response ≤ 1.5 s); tool execution < 20 ms; nothing optional on the hot path.
2. **Data correctness** — every required slot is validated or explicitly `unresolved`;
   persona evals target slot precision ≥ 0.95 and recall ≥ 0.90.
3. **Time-to-market / maintainability** — core buildable in ~8 h; domain and controller
   have no I/O so they are unit-tested to ≥ 90 % coverage; business content is data.

Tie-breakers below these: privacy & compliance (non-negotiable, see constraints), then cost.

## Components

| Component | Package | Owns |
| --- | --- | --- |
| Config | `acme_agent.config` | Settings from env (`pydantic-settings`), model ids, GenAI client factory |
| Domain | `acme_agent.domain` | `CandidateProfile`, `ConversationRecord`, enums, validators (parsers), screening rules |
| Interview | `acme_agent.interview` | Slot specs, `InterviewController` state machine, versioned prompts |
| Agent | `acme_agent.agent` | Tool functions bound to a controller, ADK live agent, text-mode agent |
| Knowledge | `acme_agent.knowledge` | FAQ loading, embeddings index, retriever |
| Analysis | `acme_agent.analysis` | Sentiment monitor, post-call processor (extraction, reconciliation, summary, metrics) |
| Storage | `acme_agent.storage` | `ConversationRepository` protocol, JSON and GCS implementations |
| Web | `acme_agent.web` | FastAPI app, WebSocket gateway, `InterviewSession` runtime, static browser client |
| CLI | `acme_agent.cli` | `serve`, `chat`, `show`, `stats`, `purge`, `eval` |
| Knowledge content | `knowledge/` (repo root) | `faq_es.md`, `faq_en.md`, `stores.json` |

Flow: browser ⇄ WebSocket gateway ⇄ ADK live agent ⇄ Gemini Live; the agent's tool calls
go into the `InterviewController`, which uses validators and the retriever and emits events
to the persister and UI. After the call the post-call processor reconciles, scores and
summarises, then the repository stores the final record.

## Dependency direction

```
web ─┐
cli ─┼─► agent ─► interview ─► domain
     │     │          ▲
     │     └► knowledge, analysis ─► domain
     └────► storage ─► domain
config is importable by everything except domain and interview.
```

- `domain` imports nothing from the project except itself.
- `interview` imports only `domain` (no I/O, no Google libraries).
- Only `agent`, `knowledge`, `analysis` and `web` talk to Vertex AI.
- Only `storage` touches the filesystem/GCS for records; nothing imports `web` or `cli`.

## Decisions

| ADR | Decision | Status |
| --- | --- | --- |
| ADR-001 | Business domain: Acme Burgers frontline hiring | accepted |
| ADR-002 | Voice layer: Gemini Live native audio on Vertex AI | accepted |
| ADR-003 | Agent framework: Google ADK + FastAPI WebSocket gateway | accepted |
| ADR-004 | Code-owned interview flow; LLM extracts through tool calls | superseded by ADR-016 |
| ADR-005 | Validation and normalisation in code | superseded by ADR-015 |
| ADR-006 | Storage: JSON files behind a repository interface | accepted |
| ADR-007 | Lightweight RAG over a job FAQ | accepted |
| ADR-008 | Post-call extraction, reconciliation and structured summary | accepted |
| ADR-009 | Human in the loop; deterministic screening status | accepted |
| ADR-010 | Shared core with text mode; testing strategy | accepted |
| ADR-011 | Sentiment analysis and escalation | accepted |
| ADR-012 | Languages: Spanish and English with mid-call switching | accepted |
| ADR-013 | Browser client and deployment | accepted |
| ADR-014 | Language, tooling and code conventions | accepted |
| ADR-015 | Hybrid slot normalisation: model normalises meaning, code validates | accepted |
| ADR-016 | Code-owned interview flow v2: documented hooks and a read-only goal query | accepted |

## Known deviations
None yet.
