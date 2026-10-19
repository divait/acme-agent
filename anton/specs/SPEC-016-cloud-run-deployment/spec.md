---
id: SPEC-016
title: Container image, GCS storage and Cloud Run deployment
status: ready
mode: full
origin_type: technical
origin: Give the proof of concept a public HTTPS URL for demos and show the production path with the same image.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-002, ADR-006, ADR-013, ADR-014]
supersedes: []
superseded_by: null
depends_on: [SPEC-008, SPEC-009]
touches: [Dockerfile, .dockerignore, src/acme_agent/storage/gcs_repo.py, src/acme_agent/storage/repository.py, docs/DEPLOY.md, Makefile, tests/unit/test_gcs_repo.py]
parent: null
---

# SPEC-016 — Container image, GCS storage and Cloud Run deployment

## Problem & Scope
Package the app as a container, add the GCS repository implementation, and document and script a Cloud Run deployment with a least-privilege service account.

Details: TECHNICAL_DESIGN §14.

## Non-goals
- Terraform or other IaC.
- Custom domains, CDN, multi-region.
- CI/CD pipelines.

## Functional Requirements
- `Dockerfile` (`python:3.12-slim`, `uv sync --frozen --no-dev`, non-root user, `uvicorn acme_agent.web.app:app --host 0.0.0.0 --port $PORT`); `.dockerignore` excludes `raw/`, `data/`, `.env*`, tests and docs.
- `GcsConversationRepository(bucket)` implementing the protocol with `google-cloud-storage`, writes with `if_generation_match` to avoid lost updates; selected with `ACME_STORAGE=gcs`, `ACME_BUCKET`.
- `docs/DEPLOY.md`: enable APIs, create bucket (private, uniform access, lifecycle rule = retention days), create service account with `roles/aiplatform.user` and bucket-scoped `roles/storage.objectAdmin`, deploy with `gcloud run deploy acme-agent --source . --region ... --timeout 3600 --session-affinity --concurrency 20 --min-instances 0 --service-account ... --set-env-vars ...`, set `ACME_ALLOWED_ORIGINS` to the service URL, budget alert, teardown commands.
- `make deploy` wraps the documented command using variables from the environment.

## Technical Requirements
- Behind Cloud Run / a TLS proxy, configure uvicorn trusted forwarded headers (`forwarded_allow_ips` via env) so `ws_url` uses `wss://` and the rate limiter sees the real client IP — or have the client build the WebSocket URL from `location` (follow-up from SPEC-008 review).
- Extend the repository contract with a `ConflictError` (storage/repository.py) raised on a GCS generation mismatch, and document how callers react (follow-up from SPEC-006 review: `save` has no expected-version parameter today).
- Same image locally and on Cloud Run; only env differs (ADR-013.3).
- No credentials baked into the image; ADC from the service account (ADR-002.2).
- GCS repo `find_unfinished_by_phone` lists objects with a prefix and reads metadata (`phone_hash`, `end_reason` as custom metadata) to avoid downloading every record.
- Unit tests use a fake bucket client; one `live`-marked test against a real test bucket.

## Acceptance Criteria
- `docker build .` succeeds and `docker run -p 8080:8080 --env-file .env` serves the app locally with ADC mounted (documented).
- Fake-bucket unit tests cover save/get/list/find/purge and the generation-match conflict.
- A deployment following `docs/DEPLOY.md` serves the page over HTTPS and completes a voice interview whose record lands in the bucket (Verification with URL redacted).
- The deployed service account has no project-wide storage role.

## Dependencies & Risks
- Cloud Run WebSocket timeouts: `--timeout 3600` and client keep-alive pings.
- Live model region availability may force a US region; documented.

## Plan
GCS repository with fake client tests first, then Dockerfile and local container run, then DEPLOY.md and a real deploy, then teardown instructions.

## Tasks
- [ ] Add `google-cloud-storage` dependency and `GcsConversationRepository` + fake-client tests
- [ ] Enable `ACME_STORAGE=gcs` in `make_repository`
- [ ] Write `Dockerfile` and `.dockerignore`; run locally
- [ ] Write `docs/DEPLOY.md` and `make deploy`
- [ ] Deploy, run a voice interview, verify the record in the bucket, record evidence

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
