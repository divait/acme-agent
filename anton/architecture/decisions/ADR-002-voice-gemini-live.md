---
id: ADR-002
title: Voice layer: Gemini Live native audio on Vertex AI
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-002 — Voice layer: Gemini Live native audio on Vertex AI

## Context
The agent must listen and speak in real time. A screening call must feel natural
(low latency, interruptions) and work in Spanish and English. GCP credits fund the project.

| Criterion | Cascaded (Pipecat: Deepgram → LLM → Cartesia) | Cascaded GCP (STT → Flash → TTS) | Gemini Live native audio | Turn-based |
|---|---|---|---|---|
| Latency per turn | ~1–1.5 s | ~1–1.5 s | sub-second | 3 s+ |
| Barge-in / VAD | configure | configure | built-in | none |
| Multilingual voice | per vendor | per service | native | per service |
| Vendors / keys | 3 | 1 | 1 | 1–3 |
| Covered by GCP credits | no | yes | yes | depends |
| Build effort | high | high | low | low |
| Transcript fidelity | exact | exact | approximate | exact |

## Decision
Use the **Gemini Live API on Vertex AI** with the speech-to-speech model
`gemini-live-2.5-flash-native-audio` (GA). Text-only tasks use cheaper Gemini Flash /
Flash-Lite. All model ids are configuration.

## Rules
- **ADR-002.1** — Model ids are read from settings (`ACME_LIVE_MODEL`, `ACME_TEXT_MODEL`,
  `ACME_SENTIMENT_MODEL`, `ACME_EMBEDDING_MODEL`); no model id string literal appears
  outside `config.py` and tests.
  _Check:_ `grep -rn '"gemini-\|text-embedding-' src/ | grep -v config.py` returns nothing.
- **ADR-002.2** — Vertex AI is reached only with ADC / service-account credentials via
  `google-genai` (Vertex mode) or ADK; no API key parameter or env var is used anywhere.
  _Check:_ grep `api_key` and `GOOGLE_API_KEY` in `src/` and `.env.example`.
- **ADR-002.3** — Input/output transcription is enabled for every live session and the
  transcript is stored in the conversation record.
  _Check:_ `RunConfig` in `agent/live.py` sets both transcription configs; session test asserts transcript turns are recorded.

## Consequences
- Tool calling in native-audio models is less reliable than in text models → small tool
  surface (ADR-016, formerly ADR-004) and post-call reconciliation (ADR-008).
- Transcripts are approximate → read-back of risky fields at confirmation; validated slots
  are the source of truth.
- Lock-in is limited to the voice adapter; a cascaded GCP pipeline remains a fallback.

## Alternatives considered
- **Cascaded pipeline with Pipecat (Deepgram, Claude/GPT, Cartesia)** — rejected: three
  vendors outside the credits, more wiring, higher latency.
- **Cascaded on GCP (Cloud STT, Gemini Flash, Cloud TTS)** — rejected as primary: higher
  latency and more code; kept as fallback.
- **Turn-based record → transcribe → reply → speak** — rejected: unnatural 3 s+ turns, no barge-in.
