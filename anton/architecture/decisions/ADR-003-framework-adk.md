---
id: ADR-003
title: Agent framework: Google ADK + FastAPI WebSocket gateway
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-003 — Agent framework: Google ADK + FastAPI WebSocket gateway

## Context
We need to stream audio between a browser and Gemini Live, execute tool calls, receive
transcriptions, and serve a small web page — with sessions fully isolated from each other.

## Decision
Use **Google ADK** (`Runner.run_live` + `LiveRequestQueue`) for the live agent and
**FastAPI** for HTTP and the WebSocket gateway. Each WebSocket gets its own
`InterviewSession` with its own controller, tools and ADK agent.

## Rules
- **ADR-003.1** — Only `acme_agent/agent/` and `acme_agent/web/` import `google.adk`.
  _Check:_ `grep -rln "google.adk" src/` lists only files under those packages.
- **ADR-003.2** — Tools are created per session by `build_tools(controller)`; no module-level
  controller, session or mutable global state exists in `agent/` or `web/`.
  _Check:_ read `agent/tools.py` and `web/session.py`; test that two sessions' tools mutate different controllers.
- **ADR-003.3** — A failure inside one session ends only that session (TaskGroup per
  session, errors caught at the session boundary) and still persists the partial record
  with `end_reason: abandoned` (`escalated` when a recruiter callback was already
  promised — amended 2026-10-19, SPEC-012).
  _Check:_ session test that injects an exception in a task and asserts a persisted `abandoned` record.

## Consequences
- ADK changes fast: versions pinned; `agent/live.py` is the only adapter to rewrite on raw
  `google-genai` if needed.
- WebSocket rather than WebRTC between browser and server: fine for the PoC, noted as a
  production improvement.

## Alternatives considered
- **Raw `google-genai` live client** — rejected as primary: more hand-written plumbing; kept as fallback.
- **Pipecat** — rejected: its value is cascaded pipelines and transports we do not need.
- **LiveKit Agents** — rejected: requires a LiveKit server/rooms; overkill for one-to-one browser calls.
