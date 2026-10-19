"""Background sentiment scoring of candidate turns (ADR-011, TECHNICAL_DESIGN section 9).

The monitor is fire-and-forget: `submit` never blocks, at most one model call is in flight, a
newer submit replaces a queued one, each call has a 3 s bound, and failures are logged (error
type only, never candidate text) and ignored. The escalation decision itself is a controller
rule; this module only produces scores.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from acme_agent.config import Settings
from acme_agent.domain.models import Speaker, TranscriptTurn
from acme_agent.domain.sentiment import TREND_THRESHOLD, aggregate

__all__ = [
    "TREND_THRESHOLD",
    "SentimentMonitor",
    "SentimentResult",
    "aggregate",
]

log = structlog.get_logger(__name__)

CALL_TIMEOUT_S = 3.0
LAST_TURNS = 3

INSTRUCTION = """\
You rate the emotional state of a job candidate during a recruiting phone interview, from the
last few turns (the final line is the one to rate). Return score from -1 (very upset) to 1
(very positive); 0 is neutral. Set frustration to true only when the candidate shows clear
irritation, impatience, anger or exasperation (for example complaining, insulting, or saying
the call is a waste of time). Terse, calm or hesitant answers are NOT frustration. reason: one
short sentence in English, without quoting personal data.
"""


class SentimentResult(BaseModel):
    score: float = Field(ge=-1.0, le=1.0)
    frustration: bool
    reason: str = ""


ClientProvider = Callable[[], genai.Client]
ResultHandler = Callable[[int, SentimentResult], Awaitable[None] | None]


class SentimentMonitor:
    """Scores the latest candidate turn in the background and reports via `on_result`."""

    def __init__(
        self,
        client_provider: ClientProvider,
        settings: Settings,
        on_result: ResultHandler,
        *,
        timeout: float = CALL_TIMEOUT_S,
    ) -> None:
        self._client_provider = client_provider
        self._settings = settings
        self._on_result = on_result
        self._timeout = timeout
        self._pending: tuple[int, str] | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    def submit(self, turn_index: int, last_turns: Sequence[TranscriptTurn]) -> None:
        """Queue the turn for scoring; never blocks. Replaces a request still waiting."""
        if self._closed:
            return
        self._pending = (turn_index, _prompt(last_turns[-LAST_TURNS:]))
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain())

    async def wait_idle(self, timeout: float = CALL_TIMEOUT_S) -> None:
        """Wait (bounded) until nothing is queued or in flight; for turn-based text mode."""
        task = self._task
        if task is not None and not task.done():
            await asyncio.wait({task}, timeout=timeout)

    async def close(self) -> None:
        """Cancel anything in flight or queued; no result is delivered afterwards."""
        self._closed = True
        self._pending = None
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _drain(self) -> None:
        while self._pending is not None and not self._closed:
            turn_index, prompt = self._pending
            self._pending = None
            try:
                result = await self._score(prompt)
            except Exception as exc:  # network, timeout, quota or invalid structured output
                log.warning("sentiment_failed", error=type(exc).__name__)
                continue
            if self._closed:
                return
            try:
                outcome = self._on_result(turn_index, result)
                if outcome is not None:
                    await outcome
            except Exception as exc:
                log.warning("sentiment_handler_failed", error=type(exc).__name__)

    async def _score(self, prompt: str) -> SentimentResult:
        client = self._client_provider()
        config = types.GenerateContentConfig(
            system_instruction=INSTRUCTION,
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=SentimentResult,
        )
        async with asyncio.timeout(self._timeout):
            response: Any = await client.aio.models.generate_content(
                model=self._settings.sentiment_model, contents=prompt, config=config
            )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, SentimentResult):
            return parsed
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("empty model response")
        return SentimentResult.model_validate_json(text)


def _prompt(turns: Sequence[TranscriptTurn]) -> str:
    return "\n".join(
        f"{'Candidate' if t.speaker is Speaker.CANDIDATE else 'Agent'}: {t.text}" for t in turns
    )
