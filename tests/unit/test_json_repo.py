from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner
from ulid import ULID

from acme_agent.cli import app
from acme_agent.config import Settings
from acme_agent.domain.models import ConversationRecord
from acme_agent.storage.json_repo import JsonConversationRepository, make_repository
from acme_agent.storage.repository import (
    CorruptRecordError,
    InvalidConversationIdError,
    RepositoryError,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "record_example.json"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def make_record(
    *,
    started: datetime = NOW,
    end_reason: str | None = "completed",
    phone: str = "+34600123456",
    cid: str | None = None,
) -> ConversationRecord:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["conversation_id"] = cid or f"c_{ULID()}"
    data["started_at"] = started.isoformat()
    data["ended_at"] = None
    data["end_reason"] = end_reason
    data["candidate"]["phone"] = phone
    return ConversationRecord.model_validate(data)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def repo(data_dir: Path) -> JsonConversationRepository:
    return JsonConversationRepository(data_dir, clock=lambda: NOW)


async def test_round_trip_and_utf8(repo: JsonConversationRepository, tmp_path: Path) -> None:
    rec = make_record()
    await repo.save(rec)
    assert await repo.get(rec.conversation_id) == rec
    text = (tmp_path / "data" / f"{rec.conversation_id}.json").read_text(encoding="utf-8")
    assert "Laura Gómez" in text
    assert "\n  " in text
    assert json.loads(text)["schema_version"] == "1.2"


async def test_get_missing_returns_none(repo: JsonConversationRepository) -> None:
    assert await repo.get(f"c_{ULID()}") is None


@pytest.mark.parametrize("bad", ["../etc/passwd", "abc", "", "c_../x", "a/b"])
async def test_invalid_id_raises(repo: JsonConversationRepository, bad: str) -> None:
    with pytest.raises(ValueError):
        await repo.get(bad)


async def test_list_order_limit_and_corrupt(
    repo: JsonConversationRepository, tmp_path: Path
) -> None:
    old = make_record(started=NOW - timedelta(days=2))
    new = make_record(started=NOW)
    mid = make_record(started=NOW - timedelta(days=1))
    for r in (old, new, mid):
        await repo.save(r)
    (tmp_path / "data" / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "data" / "invalid.json").write_text('{"a": 1}', encoding="utf-8")
    ids = [s.conversation_id for s in await repo.list()]
    assert ids == [new.conversation_id, mid.conversation_id, old.conversation_id]
    assert len(await repo.list(limit=2)) == 2
    assert await JsonConversationRepository(tmp_path / "none").list() == []


async def test_failed_replace_keeps_previous_file(
    repo: JsonConversationRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = make_record()
    await repo.save(rec)
    path = tmp_path / "data" / f"{rec.conversation_id}.json"
    before = path.read_bytes()

    def boom(*_: object, **__: object) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    changed = rec.model_copy(update={"channel": "other"})
    with pytest.raises(OSError):
        await repo.save(changed)
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == [path.name]


async def test_find_unfinished_by_phone(repo: JsonConversationRepository) -> None:
    await repo.save(make_record(end_reason="completed", started=NOW))
    older = make_record(end_reason="abandoned", started=NOW - timedelta(days=2))
    newer = make_record(end_reason="abandoned", started=NOW - timedelta(days=1))
    await repo.save(older)
    await repo.save(newer)
    await repo.save(make_record(end_reason="abandoned", phone="+34611111111"))
    await repo.save(make_record(end_reason="escalated", started=NOW))
    found = await repo.find_unfinished_by_phone("+34600123456")
    assert found is not None
    assert found.conversation_id == newer.conversation_id
    assert await repo.find_unfinished_by_phone("+34699999999") is None


async def test_find_unfinished_accepts_no_end_reason(repo: JsonConversationRepository) -> None:
    rec = make_record(end_reason=None)
    await repo.save(rec)
    found = await repo.find_unfinished_by_phone("+34600123456")
    assert found is not None
    assert found.conversation_id == rec.conversation_id


async def test_purge_only_old(repo: JsonConversationRepository) -> None:
    old = make_record(started=NOW - timedelta(days=40))
    fresh = make_record(started=NOW - timedelta(days=5))
    await repo.save(old)
    await repo.save(fresh)
    assert await repo.purge_older_than(30) == 1
    assert await repo.get(old.conversation_id) is None
    assert await repo.get(fresh.conversation_id) is not None


async def test_purge_corrupt_by_mtime(repo: JsonConversationRepository, data_dir: Path) -> None:
    data_dir.mkdir(parents=True)
    old = data_dir / f"c_{ULID()}.json"
    recent = data_dir / f"c_{ULID()}.json"
    old.write_text("{not json", encoding="utf-8")
    recent.write_text("{not json", encoding="utf-8")
    old_ts = (NOW - timedelta(days=40)).timestamp()
    recent_ts = (NOW - timedelta(days=2)).timestamp()
    os.utime(old, (old_ts, old_ts))
    os.utime(recent, (recent_ts, recent_ts))
    assert [c.conversation_id for c in await repo.purge_candidates(30)] == [old.stem]
    assert await repo.purge_older_than(30) == 1
    assert not old.exists()
    assert recent.exists()


async def test_get_corrupt_raises(repo: JsonConversationRepository, data_dir: Path) -> None:
    data_dir.mkdir(parents=True)
    cid = f"c_{ULID()}"
    (data_dir / f"{cid}.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CorruptRecordError) as info:
        await repo.get(cid)
    assert isinstance(info.value, RepositoryError)
    assert not isinstance(info.value, ValueError)


async def test_invalid_id_is_distinct_value_error(repo: JsonConversationRepository) -> None:
    with pytest.raises(InvalidConversationIdError):
        await repo.get("../etc/passwd")


async def test_foreign_and_tmp_files_ignored_and_survive_purge(
    repo: JsonConversationRepository, data_dir: Path
) -> None:
    await repo.save(make_record(started=NOW - timedelta(days=1)))
    notes = data_dir / "notes.json"
    readme = data_dir / "README.md"
    inflight = data_dir / ".x.tmp"
    for f in (notes, readme, inflight):
        f.write_text("{not json", encoding="utf-8")
    assert len(await repo.list()) == 1
    assert {c.conversation_id for c in await repo.purge_candidates(0)}.isdisjoint({"notes"})
    assert await repo.purge_older_than(0) == 1
    assert notes.exists() and readme.exists() and inflight.exists()


async def test_stale_tmp_removed_not_counted(
    repo: JsonConversationRepository, data_dir: Path
) -> None:
    data_dir.mkdir(parents=True)
    stale = data_dir / ".old.tmp"
    fresh = data_dir / ".new.tmp"
    stale.write_text("x", encoding="utf-8")
    fresh.write_text("x", encoding="utf-8")
    old_ts = (NOW - timedelta(hours=2)).timestamp()
    new_ts = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(stale, (old_ts, old_ts))
    os.utime(fresh, (new_ts, new_ts))
    assert await repo.purge_older_than(3650) == 0
    assert not stale.exists()
    assert fresh.exists()


async def test_save_leaves_no_temp_files(repo: JsonConversationRepository, data_dir: Path) -> None:
    await repo.save(make_record(started=NOW))
    assert [p.suffix for p in data_dir.iterdir()] == [".json"]


def test_make_repository(settings: Settings) -> None:
    assert isinstance(make_repository(settings), JsonConversationRepository)
    gcs = settings.model_copy(update={"storage": "gcs"})
    with pytest.raises(NotImplementedError, match="SPEC-016"):
        make_repository(gcs)


# -- CLI -------------------------------------------------------------------------------


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    data = tmp_path / "cli-data"
    monkeypatch.setenv("ACME_DATA_DIR", str(data))
    from acme_agent.config import get_settings

    get_settings.cache_clear()
    yield data
    get_settings.cache_clear()


def _seed(data: Path, *records: ConversationRecord) -> None:
    import asyncio

    repo = JsonConversationRepository(data)
    for r in records:
        asyncio.run(repo.save(r))


def test_cli_list_show_purge(cli_env: Path) -> None:
    runner = CliRunner()
    recent = make_record(started=datetime.now(UTC))
    old = make_record(started=datetime.now(UTC) - timedelta(days=90))
    _seed(cli_env, recent, old)

    res = runner.invoke(app, ["list", "--limit", "1"])
    assert res.exit_code == 0
    assert recent.conversation_id in res.output
    assert old.conversation_id not in res.output

    res = runner.invoke(app, ["show", recent.conversation_id])
    assert res.exit_code == 0
    assert json.loads(res.output)["conversation_id"] == recent.conversation_id

    res = runner.invoke(app, ["show", recent.conversation_id, "--summary"])
    assert res.exit_code == 0
    assert "delivery_rider" in res.output

    res = runner.invoke(app, ["show", f"c_{ULID()}"])
    assert res.exit_code == 1
    assert "not found" in res.output
    assert runner.invoke(app, ["show", "../etc/passwd"]).exit_code == 2

    res = runner.invoke(app, ["purge"])
    assert res.exit_code == 0
    assert old.conversation_id in res.output
    assert len(list(cli_env.glob("*.json"))) == 2

    res = runner.invoke(app, ["purge", "--older-than", "30", "--yes"])
    assert res.exit_code == 0
    assert "Deleted 1" in res.output
    assert [p.stem for p in cli_env.glob("*.json")] == [recent.conversation_id]


def test_cli_list_empty(cli_env: Path) -> None:
    res = CliRunner().invoke(app, ["list"])
    assert res.exit_code == 0
    assert "No conversations" in res.output


def test_cli_show_corrupt(cli_env: Path) -> None:
    cli_env.mkdir(parents=True)
    cid = f"c_{ULID()}"
    (cli_env / f"{cid}.json").write_text("{not json", encoding="utf-8")
    res = CliRunner().invoke(app, ["show", cid])
    assert res.exit_code == 3
    assert f"Conversation {cid} is unreadable (corrupted file)" in res.output
    assert "Traceback" not in res.output
