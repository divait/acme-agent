---
id: SPEC-001
title: Project scaffold, tooling, config and logging
status: verified
mode: full
origin_type: technical
origin: Foundation every other spec builds on: package layout, dependency management, settings, logging and test harness.
primary_story: null
related_stories: []
created_at: 2026-10-18
updated_at: 2026-10-18
decisions: [ADR-002, ADR-010, ADR-014]
supersedes: []
superseded_by: null
depends_on: []
touches: [pyproject.toml, uv.lock, Makefile, .env.example, src/acme_agent/__init__.py, src/acme_agent/config.py, src/acme_agent/logging.py, src/acme_agent/llm.py, src/acme_agent/cli.py, tests/conftest.py, tests/unit/test_architecture.py, tests/unit/test_logging.py, tests/unit/test_config.py]
parent: null
---

# SPEC-001 — Project scaffold, tooling, config and logging

## Problem & Scope
Create the Python project skeleton that every later spec plugs into: `src/acme_agent/` package with empty sub-packages (`domain`, `interview`, `agent`, `knowledge`, `analysis`, `storage`, `web`), dependency management with uv, settings loaded from the environment, structured logging with PII masking, a Vertex AI client factory, a typer CLI entry point, the pytest/ruff/mypy setup and a Makefile.

Covers TECHNICAL_DESIGN §16 (configuration) and §12 (logging conventions).

## Non-goals
- Any domain model, controller or agent behaviour (later specs).
- Docker or Cloud Run files (SPEC-016).
- CI pipeline configuration (the Makefile targets are enough for the PoC).

## Functional Requirements
- `uv sync` installs the project and dev tools; `uv run acme-agent --help` lists the commands registered so far (`version` at minimum).
- `Settings` (pydantic-settings) loads `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `ACME_LIVE_MODEL`, `ACME_TEXT_MODEL`, `ACME_SENTIMENT_MODEL`, `ACME_EMBEDDING_MODEL`, `ACME_VOICE`, `ACME_STORAGE`, `ACME_DATA_DIR`, `ACME_BUCKET`, `ACME_RETENTION_DAYS`, `ACME_ALLOWED_ORIGINS`, `ACME_LOG_LEVEL` from env or `.env`, with the defaults from DESIGN §16.
- `.env.example` documents every setting with safe placeholder values.
- `configure_logging()` sets up structlog JSON output; `mask_pii` masks phone numbers (`+34******456`), emails (`l***@example.com`) and values under keys `full_name`/`name`.
- `make_genai_client(settings)` returns a `google.genai.Client(vertexai=True, project=..., location=...)` using ADC.
- Makefile targets: `setup`, `test`, `lint`, `format`, `typecheck`, `cov`, `serve` and `chat` (placeholders that print "not implemented yet" until their specs land), `eval`.

## Technical Requirements
- Python `>=3.12`, `src/` layout, package name `acme_agent`, console script `acme-agent = acme_agent.cli:app`.
- Runtime deps: `google-adk`, `google-genai`, `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `structlog`, `typer`, `phonenumbers`, `dateparser`, `rapidfuzz`, `numpy`, `python-ulid`. Dev deps: `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`, `httpx` (test client). Versions pinned via `uv.lock`.
- `pyproject.toml`: ruff (line length 100, rules `E,F,I,B,UP,SIM,RUF`), mypy strict for `acme_agent.domain` and `acme_agent.interview`, pytest `asyncio_mode = "auto"`, markers `eval` and `live`, `addopts = "-m 'not eval and not live'"`.
- `Settings` is the only place that reads the environment (ADR-014.5); model ids exist only as `Settings` defaults (ADR-002.1); no API-key setting exists (ADR-002.2).
- `tests/unit/test_architecture.py` enforces import boundaries by parsing imports with `ast`: `domain` imports no project package; `interview` imports only `domain`; neither imports `google`, `fastapi`, `starlette`, `httpx` (ADR-004.1). It must pass on empty packages and keep passing as code is added.
- `tests/conftest.py` provides a `settings` fixture with a temp data dir and fake project id, and ensures no test needs ADC.

## Acceptance Criteria
- `uv sync && uv run pytest` passes on a machine without Google credentials.
- `uv run ruff check . && uv run ruff format --check . && uv run mypy` pass (`make lint typecheck`).
- `uv run acme-agent --help` exits 0.
- `Settings()` with no env returns the documented defaults; overriding `ACME_LIVE_MODEL` via env is reflected.
- A logging test shows `+34600123456` rendered as `+34******456` and an email masked.
- The architecture test fails if a temporary file in `domain/` imports `fastapi` (verified once by the test's own negative case).
- `grep -rn "os.environ\|os.getenv" src/` only matches `config.py`; no `requirements*.txt` exists.

## Dependencies & Risks
- ADK/genai version churn: pin and record versions in tech-stack.md.
- mypy strict on empty packages is trivial now; strictness pays off as SPEC-002/005 add code.

## Plan
Initialise with `uv init --package`, then hand-edit `pyproject.toml` for tools and markers. Add packages as empty modules with docstrings so the layout from DESIGN §14 exists from day one. Write config, logging and llm modules with tests first (they are tiny), then the architecture test, then the Makefile. Record pinned versions in `anton/architecture/tech-stack.md`.

## Tasks
- [x] Create `pyproject.toml` (deps, console script, ruff, mypy, pytest config) and run `uv lock`
- [x] Create package skeleton `src/acme_agent/{domain,interview,agent,knowledge,analysis,storage,web}/__init__.py`
- [x] Implement `config.py` (`Settings`, `get_settings()` cached) + `tests/unit/test_config.py`
- [x] Implement `logging.py` (`configure_logging`, `mask_pii` processor, `bind_conversation`) + `tests/unit/test_logging.py`
- [x] Implement `llm.py` (`make_genai_client`) without network calls at import
- [x] Implement `cli.py` typer app with `version`
- [x] Write `tests/unit/test_architecture.py` import-boundary test
- [x] Write `.env.example` and `Makefile`
- [x] Update `anton/architecture/tech-stack.md` with pinned versions

## Implementation Log
<!-- append-only: decisions, deviations, problems, commits, test results -->

### 2026-10-18 11:54 [anton-team] started
- preset: standard · max_iterations: 3 · branch: main (direct, no worktree)
- start commit: 640d719 (corrected in review round 1; was recorded as its parent 2594561)
- plan/tasks: pre-existing

### 2026-10-18 11:57 [anton-team] iteration 1 — T1–T8 project scaffold (grouped dispatch)
- swe (sonnet): done · commit 1e06770 · files: pyproject.toml, uv.lock, Makefile, .env.example, README.md, src/acme_agent/**, tests/conftest.py, tests/unit/*
- tester (sonnet, full): FAIL · `uv run pytest` → 18 passed; ruff check and mypy pass; `ruff format --check .` fails on Python snippets inside docs/TECHNICAL_DESIGN.md (ruff 0.17 formats Markdown code blocks) → fed back to swe
- deviations: T1–T8 dispatched as one unit (cohesive scaffold); swe's report was empty, results taken from the commit and the tester run; an accidental reformat of docs/TECHNICAL_DESIGN.md by `ruff format` was reverted by the tech-lead

### 2026-10-18 11:58 [anton-team] iteration 2 — T1–T8 project scaffold (grouped dispatch)
- swe (sonnet): done · commit 03d97d3 · files: pyproject.toml (`extend-exclude = ["docs", "anton", "raw"]`)
- tester: PASS (re-run by tech-lead; one-line config fix) · `uv run pytest -q` → 18 passed without ADC; `make lint typecheck` → 18 files already formatted, mypy no issues in 17 files; `acme-agent --help` exit 0
- deviations: T9 done by tech-lead — pinned versions recorded in anton/architecture/tech-stack.md

### 2026-10-18 12:00 [anton-team] review round 1
- reviewer: REVISE · R-062 fail [blocker] (src/acme_agent/logging.py:64-71 exception text and tracebacks bypass `mask_pii`), R-022 fail [major] (tests/unit/test_architecture.py resolves relative imports against `acme_agent`, so `from .models import X` in domain/ is flagged) · minors: conftest local import, untyped monkeypatch, `cov` without fail-under, phone regex over-masking comment
- tech-lead: fixed start commit in `started` entry (640d719); moved python-ulid to its own tech-stack row
- follow-up for SPEC-008: route stdlib logging (uvicorn, ADK, google-genai) through structlog `ProcessorFormatter` so ADR-014.4 also covers third-party log lines
- swe (sonnet): fixed findings 1–6 · commit 1cce4fe · files: src/acme_agent/logging.py, tests/unit/test_logging.py, tests/unit/test_architecture.py, tests/conftest.py, tests/unit/test_llm_cli.py, Makefile
- tester: PASS (tech-lead re-run) · `uv run pytest -q` → 21 passed without ADC; `make lint typecheck cov` → clean, coverage 98.80 % (fail-under 90); manual `log.exception` with `+34600123456`/`laura@example.com` renders only `+34******456`/`l***@example.com`
- deviations: `make cov` measures `acme_agent` (not domain/interview) because empty packages give "no data"; switch back in SPEC-002

### 2026-10-18 12:03 [anton-team] review round 2
- reviewer: APPROVE · round-1 findings fixed, no new blocker/major · minors: `from .. import storage` (module None) resolves to `acme_agent` and slips past the boundary test → added as SPEC-002 task; phone regex over-masks 9+ digit runs (documented, safe)

### 2026-10-18 12:03 [anton-team] implemented
- PR: not opened — project builds directly on `main` (commits 640d719..HEAD); 21 tests, lint, mypy and coverage 98.80 % green

### 2026-10-18 12:03 [anton-team] verified (on main, no PR)

## Verification
| Criterion | Method | Result | Evidence |
| --- | --- | --- | --- |
| `uv sync && uv run pytest` passes on a machine without Google credentials. | command | pass | `uv run pytest -q` with ADC env removed → 21 passed; tests/conftest.py `_isolated_environment` |
| `uv run ruff check . && uv run ruff format --check . && uv run mypy` pass (`make lint typecheck`). | command | pass | `make lint typecheck cov` clean (reviewer re-run, round 2) |
| `uv run acme-agent --help` exits 0. | command + test | pass | exit 0; tests/unit/test_llm_cli.py::test_help_lists_version |
| `Settings()` with no env returns the documented defaults; overriding `ACME_LIVE_MODEL` via env is reflected. | test | pass | tests/unit/test_config.py::test_defaults, ::test_env_override |
| A logging test shows `+34600123456` rendered as `+34******456` and an email masked. | test | pass | tests/unit/test_logging.py::test_phone_masked, ::test_email_masked, ::test_exception_text_and_stack_info_masked |
| The architecture test fails if a temporary file in `domain/` imports `fastapi` (verified once by the test's own negative case). | test | pass | tests/unit/test_architecture.py::test_negative_case_detects_forbidden_import |
| `grep -rn "os.environ\|os.getenv" src/` only matches `config.py`; no `requirements*.txt` exists. | command + test | pass | grep empty; no requirements file; tests/unit/test_architecture.py::test_no_environment_reads_outside_config |
