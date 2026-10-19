"""`acme-agent stats` over a temp data dir of fixture records."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from acme_agent.cli import app
from acme_agent.config import get_settings
from acme_agent.domain.models import ConversationRecord
from acme_agent.storage.json_repo import JsonConversationRepository

FIXTURE = Path(__file__).parent.parent / "fixtures" / "record_example.json"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def make_record(
    cid: str, end_reason: str, status: str, metrics: dict[str, Any]
) -> ConversationRecord:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["conversation_id"] = cid
    data["started_at"] = NOW.isoformat()
    data["ended_at"] = None
    data["end_reason"] = end_reason
    data["screening"]["status"] = status
    data["metrics"] = metrics
    return ConversationRecord.model_validate(data)


@pytest.fixture(autouse=True)
def _fresh_settings() -> Any:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "data"
    repo = JsonConversationRepository(directory)
    records = [
        make_record(
            "c_01M58KVS9NHX20A4N2BXXR5AA1",
            "completed",
            "meets_requirements",
            {"duration_s": 100, "invalid_attempts": {"phone": 2}, "post_call_fills": 1},
        ),
        make_record(
            "c_01M58KVS9NHX20A4N2BXXR5AA2",
            "completed",
            "needs_human_review",
            {"duration_s": 200, "invalid_attempts": {"phone": 1, "email": 1}, "post_call_fills": 0},
        ),
        make_record(
            "c_01M58KVS9NHX20A4N2BXXR5AA3", "abandoned", "missing_requirements", {"duration_s": 60}
        ),
    ]
    for record in records:
        asyncio.run(repo.save(record))
    monkeypatch.setenv("ACME_DATA_DIR", str(directory))
    return directory


def test_stats_json(data_dir: Path) -> None:
    result = CliRunner().invoke(app, ["stats", "--json"])
    assert result.exit_code == 0, result.output
    stats = json.loads(result.output)
    assert stats["count"] == 3
    assert stats["completion_rate"] == pytest.approx(2 / 3)
    assert stats["status_distribution"] == {
        "meets_requirements": 1,
        "needs_human_review": 1,
        "missing_requirements": 1,
    }
    assert stats["median_duration_s"] == 100
    assert stats["most_failed_slots"][0] == {"slot": "phone", "invalid_attempts": 3}
    assert stats["post_call_fill_rate"] == 0.5


def test_stats_text_and_empty(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = CliRunner().invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Conversations:     3" in result.output and "67%" in result.output
    monkeypatch.setenv("ACME_DATA_DIR", str(tmp_path / "empty"))
    get_settings.cache_clear()
    empty = CliRunner().invoke(app, ["stats", "--json"])
    assert empty.exit_code == 0
    assert json.loads(empty.output)["count"] == 0
