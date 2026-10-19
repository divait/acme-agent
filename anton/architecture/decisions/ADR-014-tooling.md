---
id: ADR-014
title: Language, tooling and code conventions
status: accepted
origin: chosen
confidence: null
date: 2026-10-18
research: []
supersedes: []
superseded_by: null
---

# ADR-014 — Language, tooling and code conventions

## Context
Python is required. We want fast setup for anyone cloning the repo and visible
code-quality signals.

## Decision
Python 3.12+, `src/` layout, **uv**, **ruff**, **mypy** (strict on domain and interview),
**pytest**, **pydantic-settings**, **structlog** JSON logs, **typer** CLI, and a `Makefile`
with `setup`, `test`, `lint`, `typecheck`, `serve`, `chat`, `eval`.

## Rules
- **ADR-014.1** — Dependencies are declared in `pyproject.toml` and locked in `uv.lock`;
  no `requirements*.txt`.
  _Check:_ file listing.
- **ADR-014.2** — `ruff check` and `ruff format --check` pass; `mypy --strict` passes for
  `acme_agent.domain` and `acme_agent.interview`.
  _Check:_ `make lint typecheck`.
- **ADR-014.3** — No `print()` in `src/` except the CLI's user output via typer; logging uses
  `structlog` bound with `conversation_id` inside sessions.
  _Check:_ grep `print(` in `src/` excluding `cli.py`.
- **ADR-014.4** — Phone numbers, names and emails are masked in log output via the shared
  `mask_pii` processor.
  _Check:_ logging test asserts a masked phone.
- **ADR-014.5** — Configuration comes only from `acme_agent.config.Settings`; no `os.environ`
  reads elsewhere.
  _Check:_ grep `os.environ`/`os.getenv` outside `config.py`.

## Consequences
- Contributors need `uv` and, for live parts, `gcloud` ADC; unit tests need neither.

## Alternatives considered
- **pip + requirements.txt** — rejected: no lockfile workflow.
- **Poetry** — rejected: slower; uv is already installed.
