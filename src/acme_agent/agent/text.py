"""Text-mode interview: the shared tools and instruction driven through ADK, turn by turn.

No flow logic lives here (ADR-010.3): the controller decides, this module relays messages,
keeps the transcript and hands the finished session to the finalizer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from google import genai
from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from ulid import ULID

from acme_agent.agent.models import build_adk_model
from acme_agent.agent.tools import build_tools
from acme_agent.analysis.sentiment import SentimentMonitor, SentimentResult
from acme_agent.bootstrap import AppContainer, Language
from acme_agent.domain.models import (
    ConversationRecord,
    EndReason,
    ModelInfo,
    Speaker,
    TranscriptTurn,
)
from acme_agent.interview.closing import GOODBYE_NOTE, closing_line
from acme_agent.interview.controller import InterviewController, Phase
from acme_agent.interview.prompts import PROMPT_VERSION, SYSTEM_INSTRUCTION
from acme_agent.knowledge.retriever import LazyRetriever

APP_NAME = "acme_agent_text"
USER_ID = "candidate"
START_NOTE = (
    "[SYSTEM NOTE] The candidate has just joined. Greet them as Ana in {language_name}, "
    "introduce yourself briefly and follow next_goal."
)
READBACK_NOTE = (
    "[SYSTEM NOTE] You have not read the details back yet. Read them now, in the "
    "candidate's language, then ask them to confirm: {say}"
)
LANGUAGE_NAMES = {"es": "Spanish (en español)", "en": "English"}


log = structlog.get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TextInterview:
    """One typed interview. Create, `await start()`, loop on `await send()`, `await close()`."""

    def __init__(
        self,
        container: AppContainer,
        *,
        language: Language = "es",
        clock: Callable[[], datetime] | None = None,
        model: BaseLlm | str | None = None,
        sentiment_client: genai.Client | None = None,
    ) -> None:
        self._container = container
        self._clock = clock or _utc_now
        self._conversation_id = f"c_{ULID()}"
        self._log = log.bind(conversation_id=self._conversation_id)
        self._started_at = self._clock()
        self._controller = InterviewController(
            container.parse_context_factory(language),
            self._clock,
            lambda: f"t_{ULID()}",
            lambda event: None,
            on_said_unverified=lambda field: self._log.warning(
                "said_not_in_transcript", field=field
            ),
        )
        self._controller.language = language  # read-back marker; detection is SPEC-013
        self._language = language
        self._transcript: list[TranscriptTurn] = []
        settings = container.settings
        agent = Agent(
            name="ana",
            model=model if model is not None else build_adk_model(settings, settings.text_model),
            instruction=SYSTEM_INSTRUCTION,
            tools=build_tools(self._controller, container.retriever),
        )
        self._sessions = InMemorySessionService()
        self._runner = Runner(app_name=APP_NAME, agent=agent, session_service=self._sessions)
        self._session_id = self._conversation_id
        self._session_ready = False
        self._closed = False
        self._tool_calls = 0
        self._sentiment: SentimentMonitor | None = None
        self._sentiment_notes: list[str] = []
        if sentiment_client is not None or settings.sentiment == "on":
            self._sentiment = SentimentMonitor(
                (lambda: sentiment_client)
                if sentiment_client is not None
                else (lambda: container.genai_client),
                settings,
                self._on_sentiment,
            )

    @property
    def controller(self) -> InterviewController:
        return self._controller

    @property
    def transcript(self) -> list[TranscriptTurn]:
        return self._transcript

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    @property
    def is_over(self) -> bool:
        return self._controller.phase is Phase.ENDED

    def start_faq_warmup(self) -> asyncio.Task[None] | None:
        """Begin building the FAQ index in the background (None if there is nothing to warm)."""
        retriever = self._container.retriever
        if not isinstance(retriever, LazyRetriever):
            return None

        async def warm() -> None:
            try:
                await retriever.warm()
            except Exception:
                self._log.warning("faq_index_warmup_failed", exc_info=True)

        return asyncio.create_task(warm())

    async def start(self) -> str:
        """Open the interview; returns Ana's greeting."""
        self._controller.start()
        name = LANGUAGE_NAMES.get(self._language, self._language)
        note = START_NOTE.format(language_name=name)
        message = f"{self._controller.date_context()}\n{note}"
        reply = await self._run_turn(message)
        self._append(Speaker.AGENT, reply)
        return reply

    async def send(self, text: str) -> str:
        """Send one candidate message; returns Ana's reply."""
        self._append(Speaker.CANDIDATE, text)
        note = self._controller.on_candidate_text(text)
        steering = await self._sentiment_notes_for(self._transcript[-1])
        notes = [n for n in (note, *steering) if n]
        message = "\n".join([*notes, text])
        reply = await self._run_turn(message)
        reply = await self._guard_readback(reply)
        reply = await self._guard_goodbye(reply)
        self._append(Speaker.AGENT, reply)
        return reply

    async def _sentiment_notes_for(self, turn: TranscriptTurn) -> list[str]:
        """Score the turn between turns (bounded wait) and return any steering note."""
        monitor = self._sentiment
        if monitor is None or not self._controller.consented:
            return []
        monitor.submit(turn.turn, self._transcript)
        await monitor.wait_idle()
        notes, self._sentiment_notes = self._sentiment_notes, []
        return notes

    def _on_sentiment(self, turn: int, result: SentimentResult) -> None:
        if 0 < turn <= len(self._transcript) and self._transcript[turn - 1].turn == turn:
            self._transcript[turn - 1].sentiment = result.score
        note = self._controller.on_sentiment(result.score, result.frustration)
        if note:
            self._sentiment_notes.append(note)

    async def _guard_readback(self, reply: str) -> str:
        """Code-side read-back guarantee: at most one re-prompt per confirm_profile call."""
        ctl = self._controller
        if not ctl.readback_pending or ctl.readback_complete(reply):
            return reply
        say = ctl.readback_say()
        extra = await self._run_turn(READBACK_NOTE.format(say=say))
        combined = f"{reply}\n{extra}" if reply and extra else (reply or extra)
        if ctl.readback_pending and not ctl.readback_complete(combined):
            self._log.warning("readback_missing_after_reprompt")
        ctl.drop_readback()
        return combined

    async def _guard_goodbye(self, reply: str) -> str:
        """If the interview ended in a turn with no agent text, re-prompt once for the goodbye."""
        ctl = self._controller
        if not self.is_over or reply:
            return reply
        return await self._run_turn(
            GOODBYE_NOTE.format(say=closing_line(ctl.end_reason, ctl.has_phone, ctl.consented))
        )

    async def close(self, reason: EndReason | None = None) -> ConversationRecord:
        """End the interview if needed, then finalize and return the stored record."""
        if self._sentiment is not None:
            await self._sentiment.close()
        if not self.is_over:
            self._controller.end(reason or EndReason.ABANDONED)
        settings = self._container.settings
        return await self._container.finalizer.finalize(
            self._controller,
            self._transcript,
            conversation_id=self._conversation_id,
            started_at=self._started_at,
            channel="text",
            model_info=ModelInfo(
                live=settings.live_model,
                text=settings.text_model,
                prompt_version=PROMPT_VERSION,
            ),
            metrics=self._metrics(),
        )

    def _metrics(self) -> dict[str, Any]:
        ctl = self._controller
        candidate = sum(1 for t in self._transcript if t.speaker is Speaker.CANDIDATE)
        return {
            "duration_s": round((self._clock() - self._started_at).total_seconds(), 3),
            "candidate_turns": candidate,
            "agent_turns": len(self._transcript) - candidate,
            "tool_calls": self._tool_calls,
            "validation_errors": sum(1 for e in ctl.events if e.type == "validation_failed"),
            "said_unverified": list(ctl.said_unverified),
        }

    def _append(self, speaker: Speaker, text: str) -> None:
        if speaker is Speaker.AGENT and not text:
            return
        self._transcript.append(
            TranscriptTurn(
                turn=len(self._transcript) + 1, speaker=speaker, text=text, ts=self._clock()
            )
        )

    async def _run_turn(self, message: str) -> str:
        if not self._session_ready:
            await self._sessions.create_session(
                app_name=APP_NAME, user_id=USER_ID, session_id=self._session_id
            )
            self._session_ready = True
        content = types.Content(role="user", parts=[types.Part(text=message)])
        pieces: list[str] = []
        async for event in self._runner.run_async(
            user_id=USER_ID, session_id=self._session_id, new_message=content
        ):
            if event.partial or not event.content or not event.content.parts:
                continue
            if event.author == "user":
                continue
            self._tool_calls += len(event.get_function_calls())
            pieces.extend(
                part.text for part in event.content.parts if part.text and not part.thought
            )
        return "\n".join(p.strip() for p in pieces if p.strip())
