"""JSON-file conversation repository with atomic writes (ADR-006)."""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from pydantic import ValidationError
from ulid import ULID

from acme_agent.config import Settings
from acme_agent.domain.models import ConversationRecord, EndReason
from acme_agent.storage.repository import (
    ConversationRepository,
    CorruptRecordError,
    InvalidConversationIdError,
    PurgeCandidate,
    RecordSummary,
)

log = structlog.get_logger(__name__)

Clock = Callable[[], datetime]

_ID_PREFIX = "c_"
_TMP_SUFFIX = ".tmp"
_STALE_TMP_AGE = timedelta(hours=1)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def validate_conversation_id(conversation_id: str) -> str:
    """Return the id if it is a ULID (optionally `c_`-prefixed); else raise.

    Raises InvalidConversationIdError (a ValueError).
    """
    body = conversation_id.removeprefix(_ID_PREFIX)
    try:
        ULID.from_str(body)
    except (ValueError, TypeError) as exc:
        raise InvalidConversationIdError(f"invalid conversation id: {conversation_id!r}") from exc
    if len(body) != 26 or not body.isalnum():
        raise InvalidConversationIdError(f"invalid conversation id: {conversation_id!r}")
    return conversation_id


def _fsync_dir(directory: Path) -> None:
    """Flush the directory entry after a rename (POSIX); skip where unsupported."""
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


def _is_record_file(path: Path) -> bool:
    """True for `<valid conversation id>.json`; everything else is foreign."""
    if path.suffix != ".json":
        return False
    try:
        validate_conversation_id(path.stem)
    except InvalidConversationIdError:
        return False
    return True


class JsonConversationRepository:
    """Stores each record as `{data_dir}/{conversation_id}.json`."""

    def __init__(self, data_dir: Path, clock: Clock = _utc_now) -> None:
        self._dir = Path(data_dir)
        self._clock = clock

    def _path(self, conversation_id: str) -> Path:
        return self._dir / f"{validate_conversation_id(conversation_id)}.json"

    # -- sync helpers (run in threads) -------------------------------------------------

    def _write(self, record: ConversationRecord) -> None:
        path = self._path(record.conversation_id)
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = record.model_dump_json(indent=2, exclude_none=False)
        fd, tmp_name = tempfile.mkstemp(dir=self._dir, prefix=".", suffix=_TMP_SUFFIX)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
            _fsync_dir(self._dir)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def _read(self, path: Path) -> ConversationRecord | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return ConversationRecord.model_validate_json(raw)

    def _record_paths(self) -> list[Path]:
        return sorted(p for p in self._dir.glob("*.json") if _is_record_file(p))

    def _read_all(self) -> list[ConversationRecord]:
        if not self._dir.is_dir():
            return []
        records: list[ConversationRecord] = []
        for path in self._record_paths():
            try:
                record = self._read(path)
            except (ValidationError, ValueError, OSError) as exc:
                log.warning("skipping unreadable record", file=path.name, error=type(exc).__name__)
                continue
            if record is not None:
                records.append(record)
        return records

    def _candidates(self, days: int) -> list[tuple[Path, PurgeCandidate]]:
        """Files past retention. Unparseable files fall back to their mtime."""
        if not self._dir.is_dir():
            return []
        cutoff = self._clock() - timedelta(days=days)
        found: list[tuple[Path, PurgeCandidate]] = []
        for path in self._record_paths():
            try:
                record = self._read(path)
            except (ValidationError, ValueError, OSError) as exc:
                try:
                    when = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                except OSError:
                    continue
                log.warning(
                    "unreadable record checked by file age",
                    file=path.name,
                    error=type(exc).__name__,
                )
            else:
                if record is None:
                    continue
                when = record.started_at
            if when < cutoff:
                found.append((path, PurgeCandidate(conversation_id=path.stem, timestamp=when)))
        return found

    def _purge_stale_tmp(self) -> None:
        """Remove temp files left by crashed writes (older than one hour)."""
        if not self._dir.is_dir():
            return
        cutoff = (self._clock() - _STALE_TMP_AGE).timestamp()
        for path in self._dir.glob(f".*{_TMP_SUFFIX}"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    log.warning("removed stale temp file", file=path.name)
            except OSError:
                continue

    def _purge(self, days: int) -> int:
        self._purge_stale_tmp()
        deleted = 0
        for path, _ in self._candidates(days):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            deleted += 1
        return deleted

    # -- async API ---------------------------------------------------------------------

    async def save(self, record: ConversationRecord) -> None:
        validate_conversation_id(record.conversation_id)
        await asyncio.to_thread(self._write, record)

    async def get(self, conversation_id: str) -> ConversationRecord | None:
        path = self._path(conversation_id)
        try:
            return await asyncio.to_thread(self._read, path)
        except (ValidationError, ValueError) as exc:
            raise CorruptRecordError(conversation_id) from exc

    async def list(self, limit: int | None = None) -> list[RecordSummary]:
        records = await asyncio.to_thread(self._read_all)
        records.sort(key=lambda r: r.started_at, reverse=True)
        if limit is not None:
            records = records[: max(limit, 0)]
        return [RecordSummary.from_record(r) for r in records]

    async def find_unfinished_by_phone(self, e164: str) -> ConversationRecord | None:
        records = await asyncio.to_thread(self._read_all)
        matches = [
            r
            for r in records
            if r.candidate.phone == e164 and r.end_reason in (None, EndReason.ABANDONED)
        ]
        return max(matches, key=lambda r: r.started_at, default=None)

    async def purge_candidates(self, days: int) -> builtins.list[PurgeCandidate]:
        found = await asyncio.to_thread(self._candidates, days)
        return [c for _, c in found]

    async def purge_older_than(self, days: int) -> int:
        return await asyncio.to_thread(self._purge, days)


def make_repository(settings: Settings) -> ConversationRepository:
    """Build the repository selected by `ACME_STORAGE`."""
    if settings.storage == "json":
        return JsonConversationRepository(settings.data_dir)
    raise NotImplementedError("GCS storage arrives with SPEC-016; set ACME_STORAGE=json")
