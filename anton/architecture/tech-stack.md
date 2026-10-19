# Tech Stack

Concrete technologies currently in use. Update when the stack changes.
Exact versions are pinned in `uv.lock` (recorded here at SPEC-001, 2026-10-18).

| Layer | Technology | Version | Notes |
| --- | --- | --- | --- |
| Language | Python | 3.12+ (dev on 3.13) | typed, `src/` layout |
| Packaging | uv | 0.6.17 | `pyproject.toml` + `uv.lock` |
| Voice model | Gemini Live `gemini-live-2.5-flash-native-audio` | GA | Vertex AI; id in `ACME_LIVE_MODEL` |
| Text model | Gemini 2.5 Flash | — | extraction, summary; `ACME_TEXT_MODEL` |
| Sentiment model | Gemini 2.5 Flash-Lite | — | `ACME_SENTIMENT_MODEL` |
| Embeddings | Vertex `text-embedding-005` | — | `ACME_EMBEDDING_MODEL` |
| Agent framework | Google ADK (`google-adk`) | 2.12.0 | bidi streaming, tools |
| GenAI SDK | `google-genai` | 2.31.0 | Vertex mode via ADC |
| Web | FastAPI + uvicorn | fastapi 0.141.1 · uvicorn 0.54.0 | HTTP + WebSocket |
| Validation | Pydantic v2, pydantic-settings | pydantic 2.14.1 · pydantic-settings 2.16.0 | models + settings |
| Parsing | phonenumbers, dateparser, rapidfuzz | phonenumbers 9.0.41 · dateparser 1.4.3 · rapidfuzz 3.14.6 | phones, dates, store matching |
| Identifiers | python-ulid | 4.0.1 | conversation ids |
| Time zones | tzdata | 2026.5 | IANA tz data so `zoneinfo` works in slim containers (SPEC-005) |
| Vector math | numpy | numpy 2.5.4 | in-memory cosine |
| Logging | structlog | structlog 26.1.0 | JSON logs |
| CLI | typer | typer 0.27.3 | `acme-agent` entry point |
| Tests | pytest, pytest-asyncio, pytest-cov | pytest 9.1.1 · pytest-asyncio 1.4.0 · pytest-cov 7.1.0 · httpx 0.28.1 | markers `eval`, `live` |
| Lint / types | ruff, mypy | ruff 0.17.1 · mypy 2.4.0 | mypy strict on domain + interview |
| Browser client | Vanilla JS, Web Audio AudioWorklet | — | no build step |
| Storage | JSON files; Google Cloud Storage (optional) | — | `ACME_STORAGE=json|gcs` |
| Hosting (optional) | Cloud Run | — | Dockerfile, `gcloud run deploy --source` |
