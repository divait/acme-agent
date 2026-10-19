.PHONY: setup test lint format typecheck cov serve chat eval

setup:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

cov:
	uv run pytest --cov=acme_agent.domain --cov=acme_agent.interview --cov-report=term-missing --cov-fail-under=90

serve:
	uv run acme-agent serve

chat:
	uv run acme-agent chat

eval:
	@echo "eval: not implemented yet"
