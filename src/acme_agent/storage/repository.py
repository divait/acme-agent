"""Conversation repository contract and list summary model."""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from acme_agent.domain.models import ConversationRecord, EndReason, Role, ScreeningStatus


class RepositoryError(Exception):
    """Base class for repository failures that are not caller input errors."""


class InvalidConversationIdError(ValueError):
    """The conversation id is not a valid ULID (optionally `c_`-prefixed)."""


class CorruptRecordError(RepositoryError):
    """A stored record exists but cannot be parsed."""


class PurgeCandidate(BaseModel):
    """A record that retention would delete; timestamp is started_at or file mtime."""

    conversation_id: str
    timestamp: datetime


class RecordSummary(BaseModel):
    """Lightweight view of a stored conversation, for listings."""

    conversation_id: str
    started_at: datetime
    ended_at: datetime | None = None
    role: Role | None = None
    status: ScreeningStatus
    end_reason: EndReason | None = None

    @classmethod
    def from_record(cls, record: ConversationRecord) -> RecordSummary:
        return cls(
            conversation_id=record.conversation_id,
            started_at=record.started_at,
            ended_at=record.ended_at,
            role=record.candidate.role,
            status=record.screening.status,
            end_reason=record.end_reason,
        )


class ConversationRepository(Protocol):
    """Persistence port for conversation records (ADR-006).

    All methods raise InvalidConversationIdError (a ValueError) for malformed ids
    and CorruptRecordError when a requested record exists but is unreadable.
    """

    async def save(self, record: ConversationRecord) -> None:
        """Create or atomically replace the record.

        Raises InvalidConversationIdError if the record's id is malformed.
        """
        ...

    async def get(self, conversation_id: str) -> ConversationRecord | None:
        """Return the record, or None if it does not exist.

        Raises InvalidConversationIdError for a malformed id and CorruptRecordError
        if the stored data cannot be parsed.
        """
        ...

    async def list(self, limit: int | None = None) -> list[RecordSummary]:
        """Summaries ordered newest first by started_at.

        `limit` caps the count (None means all; values <= 0 give an empty list).
        Unreadable records are skipped with a warning, not raised.
        """
        ...

    async def find_unfinished_by_phone(self, e164: str) -> ConversationRecord | None:
        """Most recently started unfinished conversation for the phone, or None.

        Unfinished means end_reason is None or abandoned. Unreadable records are skipped.
        """
        ...

    async def purge_older_than(self, days: int) -> int:
        """Delete records past retention and return how many were deleted.

        Retention is measured from started_at; unreadable files fall back to their
        mtime. Stale temp files from crashed writes (older than one hour) are also
        removed but not counted. Files that are not conversation records are never touched.
        """
        ...

    async def purge_candidates(self, days: int) -> builtins.list[PurgeCandidate]:
        """Dry run of purge_older_than: the records it would delete, without deleting."""
        ...
