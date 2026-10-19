---
id: ADR-013
title: Browser client and deployment
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-013 — Browser client and deployment

## Context
Candidates need a way to talk to Ana for the demo, and the PoC needs a credible path
beyond the local machine.

## Decision
A **vanilla JS page** with AudioWorklets (PCM16 16 kHz up, PCM 24 kHz down) over the
WebSocket, showing live captions and the profile filling in. Runs **locally by default**;
**Cloud Run** is an optional phase using the same container image.

## Rules
- **ADR-013.1** — The browser client is static files under `web/static/` with no build step,
  bundler or npm dependency.
  _Check:_ no `package.json`; files served by FastAPI `StaticFiles`.
- **ADR-013.2** — The client holds no credentials or model configuration; it only knows the
  WebSocket protocol in `docs/TECHNICAL_DESIGN.md` §2.
  _Check:_ grep static files for `key`, `token`, `gemini`.
- **ADR-013.3** — Local and Cloud Run run the same image/code; differences are environment
  variables only (`ACME_STORAGE`, `ACME_BUCKET`, region).
  _Check:_ no `if cloud_run`-style branches; Dockerfile has no environment-specific code.

## Consequences
- Requires microphone permission and HTTPS or localhost.
- Telephony (Twilio Media Streams) is future work.

## Alternatives considered
- **React/Next.js** — rejected: build tooling without benefit for one page.
- **Phone number via Twilio** — deferred: setup and μ-law transcoding.
- **`adk web` dev UI** — rejected: cannot show the profile panel.
- **GKE / Agent Engine** — rejected: more ops than a PoC needs.
