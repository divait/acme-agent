from __future__ import annotations

import pytest
from typer.testing import CliRunner

from acme_agent import __version__
from acme_agent.cli import app
from acme_agent.config import Settings
from acme_agent.llm import make_genai_client


def test_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_version() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.output


def test_make_genai_client_vertex(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("acme_agent.llm.genai.Client", FakeClient)
    make_genai_client(settings)
    assert captured == {"vertexai": True, "project": "test-project", "location": "us-central1"}
