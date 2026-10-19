"""One live interview over one WebSocket (TECHNICAL_DESIGN sections 1-3, ADR-003, ADR-009).

`InterviewSession.run()` owns the controller, the transcript, the `LiveRequestQueue` and five
tasks under one `asyncio.TaskGroup`: upstream (client frames), downstream (model events),
controller-event pump (slot/state/faq frames), persister and watchdog. Whatever ends the
session, `_finish` runs once: stop input, close the queue, cancel the persister and wait for
any flush already in flight, send `ended`, then hand the controller and transcript to the
finalizer (post-call) and send `completed`.
Every stored version comes from `controller.build_record`, never from raw model events.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import statistics
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from fastapi import WebSocket
from google import genai
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.events import Event as AdkEvent
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.genai import types
from pydantic_core import to_jsonable_python
from ulid import ULID

from acme_agent.agent.live import stream_live_events
from acme_agent.agent.tools import build_tools
from acme_agent.analysis.sentiment import SentimentMonitor, SentimentResult
from acme_agent.bootstrap import AppContainer, Language
from acme_agent.domain.models import (
    ConversationRecord,
    EndReason,
    Event,
    ModelInfo,
    Speaker,
    TranscriptTurn,
)
from acme_agent.interview.closing import GOODBYE_NOTE, closing_line
from acme_agent.interview.controller import InterviewController, Phase
from acme_agent.interview.prompts import PROMPT_VERSION
from acme_agent.interview.slots import SLOTS
from acme_agent.web.frames import FrameTooLargeError, receive_frame
from acme_agent.web.protocol import (
    CompletedMessage,
    EndedMessage,
    EndMessage,
    ErrorMessage,
    FaqMessage,
    InterruptedMessage,
    PingMessage,
    PongMessage,
    ProtocolError,
    ServerMessage,
    SlotMessage,
    StartMessage,
    StateMessage,
    TextMessage,
    TranscriptMessage,
    dump_server_message,
)

CHANNEL = "web_voice"
BARGE_IN_WINDOW_S = 0.3
AUDIO_MIME = "audio/pcm;rate=16000"
LANGUAGE_NAMES = {"es": "Spanish (en español)", "en": "English"}
START_NOTE = "[SYSTEM NOTE] Greet the candidate as Ana in {language_name}."
READBACK_NOTE = (
    "[SYSTEM NOTE] You have not read the details back yet. Read them now, in the "
    "candidate's language, then ask them to confirm: {say}"
)
SILENCE_NOTE = (
    "[SYSTEM NOTE] The candidate has been silent for a while. Check in briefly and ask "
    "whether they are still there."
)
WRAPUP_NOTE = (
    "[SYSTEM NOTE] The interview is running long. Wrap up: finish the current question, "
    "then close the interview politely."
)
USER_ERROR_MESSAGE = "Something went wrong with the interview. We are saving your answers so far."
CREDENTIALS_HINT = "run: gcloud auth application-default login"
USER_ERROR_MESSAGE_UNSAVED = "Something went wrong with the interview and it could not be saved."


@dataclass(frozen=True)
class Timings:
    """All durations in seconds; tests shrink them to milliseconds."""

    flush_s: float = 5.0
    stale_flush_s: float = 30.0  # bound on waiting out a flush the drain gave up on
    silence_note_s: float = 20.0
    silence_checkins: int = 3  # check-ins before abandoning, each after silence_note_s
    wrapup_s: float = 480.0
    hard_stop_s: float = 600.0
    tick_s: float = 1.0
    goodbye_s: float = 8.0  # bound on waiting for the goodbye after the end note
    monotonic: Callable[[], float] = time.monotonic


@dataclass
class RunnerSetup:
    """What a runner factory gets: enough to drive ADK, or to fake it and call real tools."""

    controller: InterviewController
    container: AppContainer
    queue: LiveRequestQueue
    conversation_id: str
    tools: dict[str, Callable[..., Any]] = field(default_factory=dict)


RunnerFactory = Callable[[RunnerSetup], AsyncIterator[AdkEvent]]


def _adk_runner(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
    return stream_live_events(setup.controller, setup.container, setup.queue, setup.conversation_id)


class LiveModelError(Exception):
    """The live model reported an error event."""


def _language_from_locale(locale: str) -> Language:
    return "en" if locale.lower().startswith("en") else "es"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InterviewSession:
    """Runs one interview until it ends, the socket closes, or a task fails."""

    def __init__(
        self,
        ws: WebSocket,
        conversation_id: str,
        container: AppContainer,
        *,
        runner_factory: RunnerFactory | None = None,
        clock: Callable[[], datetime] | None = None,
        timings: Timings | None = None,
        sentiment_client: genai.Client | None = None,
    ) -> None:
        self._ws = ws
        self._cid = conversation_id
        self._container = container
        self._clock = clock or _utc_now
        self._timings = timings or Timings()
        self._mono = self._timings.monotonic
        self._runner_factory = runner_factory or _adk_runner
        self._log = structlog.get_logger(__name__).bind(conversation_id=conversation_id)

        self._events: asyncio.Queue[Event] = asyncio.Queue()
        self.controller = InterviewController(
            container.parse_context_factory("es"),
            self._clock,
            lambda: f"t_{ULID()}",
            self._events.put_nowait,  # sync and non-blocking, as the controller requires
            on_said_unverified=lambda field: self._log.warning(
                "said_not_in_transcript", field=field
            ),
        )
        self._queue = LiveRequestQueue()
        self._sentiment: SentimentMonitor | None = None
        if sentiment_client is not None or container.settings.sentiment == "on":
            self._sentiment = SentimentMonitor(
                (lambda: sentiment_client)
                if sentiment_client is not None
                else (lambda: container.genai_client),
                container.settings,
                self._on_sentiment,
            )
        self.transcript: list[TranscriptTurn] = []
        self.sent_content: list[str] = []  # every text turn / steering note sent to the model
        self._started_at = self._clock()
        self._language: Language = "es"

        self._send_lock = asyncio.Lock()
        self._connected = True
        self._accepting = True
        self._started = asyncio.Event()
        self._started_mono: float | None = None
        self._stop = asyncio.Event()
        self._end_requested = False
        self._end_reason = EndReason.ABANDONED
        self._finished = False

        self._last_activity = self._mono()
        self._silence_checkins = 0
        self._wrapup_noted = False
        self._goodbye_noted = False
        self._goodbye_task: asyncio.Task[None] | None = None
        self._goodbye_deadline = 0.0  # loop time; pushed out while Ana speaks, capped
        self._goodbye_cap = 0.0

        self._partial = {Speaker.CANDIDATE: "", Speaker.AGENT: ""}
        self._agent_turn_texts: list[str] = []
        self._agent_output = False  # the agent said something since the last turn_complete

        self._dirty = False
        self._flush_wanted = asyncio.Event()
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_abandoned = False  # the drain timed out; that flush may land late

        self._candidate_turns = 0
        self._agent_turns = 0
        self._tool_calls = 0
        self._interruptions = 0
        self._last_agent_audio: float | None = None
        self._first_audio_ms: float | None = None
        self._latencies_ms: list[float] = []
        self._awaiting_reply_since: float | None = None
        self._last_candidate_input_mono: float | None = None

    # -- lifecycle -----------------------------------------------------------------------

    async def run(self) -> None:
        failure: BaseException | None = None
        try:
            try:
                async with asyncio.TaskGroup() as tg:
                    tasks = [
                        tg.create_task(self._upstream()),
                        tg.create_task(self._downstream()),
                        tg.create_task(self._pump_controller_events()),
                        tg.create_task(self._persister()),
                        tg.create_task(self._watchdog()),
                    ]
                    await self._stop.wait()
                    for task in tasks:
                        task.cancel()
            except* Exception as group:
                failure = next(
                    (e for e in group.exceptions if isinstance(e, FrameTooLargeError)),
                    group.exceptions[0],
                )
                extra: dict[str, str] = {}
                if isinstance(failure, RefreshError | DefaultCredentialsError):
                    extra["hint"] = CREDENTIALS_HINT
                self._log.error("session_task_failed", error=type(failure).__name__, **extra)
        except asyncio.CancelledError:
            await asyncio.shield(self._finish(None))
            raise
        await self._finish(failure)
        if isinstance(failure, FrameTooLargeError):
            raise failure

    async def _finish(self, failure: BaseException | None) -> None:
        if self._finished:
            return
        self._finished = True
        self._accepting = False
        self._queue.close()
        if self._sentiment is not None:
            await self._sentiment.close()
        if self._goodbye_task is not None:
            self._goodbye_task.cancel()
        await self._drain_flush()
        ctl = self.controller
        if ctl.phase is not Phase.ENDED:
            ctl.end(self._end_reason)
        await self._drain_events()
        await self._flush_candidate_partial()
        settings = self._container.settings
        started = self._started.is_set()  # a socket that never sent `start` stores nothing
        # The live part is over: tell the client now, post-call can take a while.
        if failure is not None and not isinstance(failure, FrameTooLargeError):
            code, message = (
                ("session_failed", USER_ERROR_MESSAGE)
                if started
                else ("session_failed_unsaved", USER_ERROR_MESSAGE_UNSAVED)
            )
            await self._send(ErrorMessage(code=code, message=message))
        reason = (ctl.end_reason or EndReason.ABANDONED).value
        await self._send(EndedMessage(reason=reason))
        record: ConversationRecord | None = None
        try:
            if started:
                record = await self._container.finalizer.finalize(
                    ctl,
                    self.transcript,
                    conversation_id=self._cid,
                    started_at=self._started_at,
                    model_info=self._model_info(),
                    channel=CHANNEL,
                    metrics=self._metrics(),
                )
        except Exception as exc:  # the user already has `ended`; the failure is in the log
            self._log.error("finalize_failed", error=type(exc).__name__)
        if record is not None:
            await self._reassert_final(record)
        status = record.screening.status.value if record else "unknown"
        summary = record.summary.model_dump(mode="json") if record and record.summary else None
        reasons = record.screening.rule_ids if record else []
        sentiment = (
            record.sentiment.model_dump(mode="json") if record and record.sentiment else None
        )
        await self._send(
            CompletedMessage(
                status=status,
                summary=summary,
                reasons=reasons,
                end_reason=reason,
                sentiment=sentiment,
                profile=self._final_profile(record) if record else None,
                complete=bool(
                    record
                    and record.end_reason is EndReason.COMPLETED
                    and not record.candidate.missing_required()
                ),
            )
        )
        self._log.info(
            "session_finished",
            reason=reason,
            model=settings.live_model,
            ttfa_ms=self._first_audio_ms,
        )

    def _request_end(self, reason: EndReason = EndReason.ABANDONED) -> None:
        if self._end_requested:
            return
        self._end_requested = True
        self._accepting = False
        self._end_reason = reason
        self._stop.set()

    # -- helpers -------------------------------------------------------------------------

    def _model_info(self) -> ModelInfo:
        s = self._container.settings
        return ModelInfo(live=s.live_model, text=s.text_model, prompt_version=PROMPT_VERSION)

    async def _send(self, message: ServerMessage) -> None:
        if not self._connected:
            return
        try:
            async with self._send_lock:
                await self._ws.send_text(dump_server_message(message))
        except Exception:
            self._connected = False

    async def _send_audio(self, data: bytes) -> None:
        if not self._connected:
            return
        try:
            async with self._send_lock:
                await self._ws.send_bytes(data)
        except Exception:
            self._connected = False

    def _send_content(self, text: str) -> None:
        """Text turn or steering note to the model."""
        if not self._accepting:
            return
        self.sent_content.append(text)
        self._queue.send_content(types.Content(role="user", parts=[types.Part(text=text)]))

    def _touch(self) -> None:
        self._last_activity = self._mono()

    def _touch_candidate(self) -> None:
        """The candidate spoke or typed: also restart the check-in count."""
        self._touch()
        self._silence_checkins = 0

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _append_turn(self, speaker: Speaker, text: str) -> TranscriptTurn:
        turn = TranscriptTurn(
            turn=len(self.transcript) + 1, speaker=speaker, text=text, ts=self._clock()
        )
        self.transcript.append(turn)
        if speaker is Speaker.CANDIDATE:
            self._candidate_turns += 1
        else:
            self._agent_turns += 1
        self._mark_dirty()
        return turn

    def _metrics(self) -> dict[str, Any]:
        ctl = self.controller
        latencies = list(self._latencies_ms)
        return {
            "duration_s": round((self._clock() - self._started_at).total_seconds(), 3),
            "candidate_turns": self._candidate_turns,
            "agent_turns": self._agent_turns,
            "tool_calls": self._tool_calls,
            "validation_errors": sum(1 for e in ctl.events if e.type == "validation_failed"),
            "interruptions": self._interruptions,
            "said_unverified": list(ctl.said_unverified),
            "time_to_first_agent_audio_ms": self._first_audio_ms,
            "turn_latencies_ms": latencies,
            "median_turn_latency_ms": statistics.median(latencies) if latencies else None,
        }

    # -- upstream ------------------------------------------------------------------------

    async def _upstream(self) -> None:
        while True:
            frame = await receive_frame(self._ws)
            if frame is None:
                self._connected = False
                self._request_end()
                return
            if isinstance(frame, bytes):
                if self._accepting and self._started.is_set():
                    self._queue.send_realtime(types.Blob(data=frame, mime_type=AUDIO_MIME))
            elif isinstance(frame, ProtocolError):
                # A malformed frame is a client bug (e.g. stale cached script): log the reason only.
                self._log.warning("bad_frame", code=frame.code, reason=frame.message)
                await self._send(ErrorMessage(code=frame.code, message=frame.message))
            elif isinstance(frame, StartMessage):
                self._on_start(frame)
            elif isinstance(frame, TextMessage):
                await self._on_text(frame.text)
            elif isinstance(frame, EndMessage):
                self._request_end()
                return
            elif isinstance(frame, PingMessage):
                await self._send(PongMessage())

    def _on_start(self, message: StartMessage) -> None:
        if self._started.is_set():
            return
        self._language = _language_from_locale(message.locale)
        ctl = self.controller
        ctl.ctx = self._container.parse_context_factory(self._language)
        ctl.language = self._language
        ctl.start()
        self._started_mono = self._mono()
        self._touch()
        name = LANGUAGE_NAMES[self._language]
        # One content turn: each one triggers a model reply, so two made Ana greet twice.
        note = START_NOTE.format(language_name=name)
        self._send_content(f"{ctl.date_context()}\n{note}")
        self._started.set()
        self._log.info("session_started", language=self._language)

    async def _on_text(self, text: str) -> None:
        if not (self._started.is_set() and self._accepting):
            return
        self._touch()
        self._last_candidate_input_mono = self._mono()
        await self._candidate_final(text, typed=True)

    # -- downstream ----------------------------------------------------------------------

    async def _downstream(self) -> None:
        await self._started.wait()
        setup = RunnerSetup(
            controller=self.controller,
            container=self._container,
            queue=self._queue,
            conversation_id=self._cid,
            tools={f.__name__: f for f in build_tools(self.controller, self._container.retriever)},
        )
        async with contextlib.aclosing(
            cast(AsyncGenerator[AdkEvent], self._runner_factory(setup))
        ) as events:
            async for event in events:
                await self._on_model_event(event)
        self._request_end(self.controller.end_reason or EndReason.ABANDONED)

    async def _on_model_event(self, event: AdkEvent) -> None:
        if event.error_code or event.error_message:
            raise LiveModelError(event.error_code or "live model error")
        self._tool_calls += len(event.get_function_calls())
        if event.interrupted:
            await self._on_interrupted()
        if event.input_transcription is not None:
            await self._on_transcription(Speaker.CANDIDATE, event.input_transcription)
        if event.output_transcription is not None:
            await self._on_transcription(Speaker.AGENT, event.output_transcription)
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.inline_data and part.inline_data.data:
                    await self._on_audio(part.inline_data.data)
        if event.turn_complete:
            await self._on_turn_complete()

    async def _on_audio(self, data: bytes) -> None:
        now = self._mono()
        self._last_agent_audio = now
        if self._goodbye_noted:
            loop_now = asyncio.get_running_loop().time()
            self._goodbye_deadline = min(
                max(self._goodbye_deadline, loop_now + self._timings.goodbye_s), self._goodbye_cap
            )
        await self._flush_candidate_partial()
        self._agent_output = True
        self._touch()
        if self._first_audio_ms is None and self._started_mono is not None:
            self._first_audio_ms = round((now - self._started_mono) * 1000, 1)
            self._log.info("first_agent_audio", ms=self._first_audio_ms)
        if self._awaiting_reply_since is not None:
            self._latencies_ms.append(round((now - self._awaiting_reply_since) * 1000, 1))
            self._awaiting_reply_since = None
        await self._send_audio(data)

    async def _on_interrupted(self) -> None:
        last = self._last_agent_audio
        if last is not None and self._mono() - last <= BARGE_IN_WINDOW_S:
            self._interruptions += 1  # Ana was actually speaking, not just server VAD firing
        await self._send(InterruptedMessage())
        await self._finalize_agent_partial()

    async def _on_transcription(self, speaker: Speaker, tr: types.Transcription) -> None:
        text = tr.text or ""
        if speaker is Speaker.CANDIDATE:
            self._touch_candidate()
            if text or tr.finished:
                self._last_candidate_input_mono = self._mono()
        else:
            await self._flush_candidate_partial()
            self._agent_output = True
            self._touch()
        if tr.finished:
            full = text or self._partial[speaker]
            self._partial[speaker] = ""
            if not full.strip():
                return
            if speaker is Speaker.CANDIDATE:
                await self._candidate_final(full)
            else:
                await self._agent_final(full)
        elif text:
            self._partial[speaker] += text
            await self._send(
                TranscriptMessage(
                    speaker=speaker.value,
                    text=self._partial[speaker],
                    final=False,
                    turn=len(self.transcript) + 1,
                )
            )

    async def _flush_candidate_partial(self) -> None:
        text = self._partial[Speaker.CANDIDATE].strip()
        self._partial[Speaker.CANDIDATE] = ""
        if text:
            await self._candidate_final(text)

    async def _finalize_agent_partial(self) -> None:
        text = self._partial[Speaker.AGENT].strip()
        self._partial[Speaker.AGENT] = ""
        if text:
            await self._agent_final(text)

    async def _candidate_final(self, text: str, *, typed: bool = False) -> None:
        turn = self._append_turn(Speaker.CANDIDATE, text)
        self._awaiting_reply_since = self._last_candidate_input_mono or self._mono()
        await self._send(
            TranscriptMessage(speaker="candidate", text=text, final=True, turn=turn.turn)
        )
        note = self.controller.on_candidate_text(text)
        if typed:
            self._send_content(f"{note}\n{text}" if note else text)
        elif note:
            self._send_content(note)
        if self._sentiment is not None and self.controller.consented:
            self._sentiment.submit(turn.turn, self.transcript)  # background; never awaited

    def _on_sentiment(self, turn: int, result: SentimentResult) -> None:
        """A score arrived: store it, feed the controller rule, steer once if it fires."""
        if 0 < turn <= len(self.transcript) and self.transcript[turn - 1].turn == turn:
            self.transcript[turn - 1].sentiment = result.score
            self._mark_dirty()
        note = self.controller.on_sentiment(result.score, result.frustration)
        if note and not self._goodbye_noted:
            self._send_content(note)

    async def _agent_final(self, text: str) -> None:
        turn = self._append_turn(Speaker.AGENT, text)
        self._agent_turn_texts.append(text)
        await self._send(TranscriptMessage(speaker="agent", text=text, final=True, turn=turn.turn))

    async def _on_turn_complete(self) -> None:
        await self._flush_candidate_partial()
        await self._finalize_agent_partial()
        spoken = " ".join(self._agent_turn_texts)
        said_something = self._agent_output
        self._agent_turn_texts = []
        self._agent_output = False
        self._touch()
        ctl = self.controller
        if ctl.readback_pending and said_something and not ctl.readback_complete(spoken):
            self._send_content(READBACK_NOTE.format(say=ctl.readback_say()))
            ctl.drop_readback()  # one re-prompt per confirm_profile, never a loop
        if ctl.phase is Phase.ENDED:
            if not said_something and not self._goodbye_noted:
                # The model ended without a goodbye: ask for it once, close on the next turn.
                self._start_goodbye(ctl.end_reason)
                return
            self._request_end(ctl.end_reason or EndReason.ABANDONED)

    def _start_goodbye(self, reason: EndReason | None) -> None:
        self._goodbye_noted = True
        ctl = self.controller
        self._send_content(
            GOODBYE_NOTE.format(say=closing_line(reason, ctl.has_phone, ctl.consented))
        )
        start = asyncio.get_running_loop().time()
        self._goodbye_deadline = start + self._timings.goodbye_s
        self._goodbye_cap = start + 3 * self._timings.goodbye_s
        self._goodbye_task = asyncio.create_task(self._goodbye_timeout())

    async def _goodbye_timeout(self) -> None:
        loop = asyncio.get_running_loop()
        while (remaining := self._goodbye_deadline - loop.time()) > 0:
            await asyncio.sleep(remaining)  # audio flowing moves the deadline (up to the cap)
        self._log.info("goodbye_timeout")
        self._request_end(self.controller.end_reason or EndReason.ABANDONED)

    # -- controller events -> frames -----------------------------------------------------

    async def _pump_controller_events(self) -> None:
        while True:
            event = await self._events.get()
            await self._handle_controller_event(event)

    async def _drain_events(self) -> None:
        while not self._events.empty():
            await self._handle_controller_event(self._events.get_nowait())

    async def _handle_controller_event(self, event: Event) -> None:
        self._mark_dirty()
        payload = event.payload
        match event.type:
            case "phase_changed":
                self._flush_wanted.set()
                await self._send(StateMessage(phase=str(payload.get("to"))))
            case "slot_filled" | "field_corrected":
                await self._send_slot(str(payload.get("field")), "filled")
            case "validation_failed":
                await self._send_slot(str(payload.get("field")), "invalid")
            case "slot_unresolved":
                await self._send_slot(str(payload.get("field")), "unresolved")
            case "faq_answered" | "faq_missed":
                source = payload.get("source")
                await self._send(
                    FaqMessage(
                        question=str(payload.get("question")),
                        source=str(source) if source else None,
                    )
                )

    async def _send_slot(self, name: str, status: Any) -> None:
        snap = self.controller.snapshot()
        slots: Any = snap["slots"]
        value: str | None = None
        if status == "filled":
            raw = slots.get(name, {}).get("value")
            if raw is None:
                return  # purged after a consent refusal; nothing to show
            value = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        progress: Any = snap["progress"]
        await self._send(
            SlotMessage(
                name=name,
                status=status,
                value=value,
                display=self._display_for(name, value),
                progress=float(progress),
            )
        )

    def _final_profile(self, record: ConversationRecord) -> dict[str, dict[str, Any]]:
        """Every active slot of the final record: value (JSON-able), display and status."""
        profile: dict[str, dict[str, Any]] = {}
        for spec in SLOTS:
            if not spec.active(record.candidate):
                continue
            raw = to_jsonable_python(getattr(record.candidate, spec.name.value))
            filled = raw is not None and raw != []
            text = None if not filled else raw if isinstance(raw, str) else json.dumps(raw)
            profile[spec.name.value] = {
                "value": raw if filled else None,
                "display": self._display_for(spec.name.value, text),
                "status": "filled" if filled else "missing",
                "required": spec.required,
            }
        return profile

    def _display_for(self, name: str, value: str | None) -> str | None:
        """Human-readable value the client can show instead of the raw one (store name)."""
        if name != "preferred_store_id" or value is None:
            return None
        store = next((s for s in self.controller.ctx.stores if s.id == value), None)
        return store.name if store else None

    # -- persister -----------------------------------------------------------------------

    async def _persister(self) -> None:
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._flush_wanted.wait(), self._timings.flush_s)
            self._flush_wanted.clear()
            if not self._dirty:
                continue
            # The save runs as its own task so cancelling this loop never abandons it halfway;
            # `_finish` waits for it before the final record is written.
            self._flush_task = asyncio.create_task(self._persist_once())
            await asyncio.shield(self._flush_task)

    async def _persist_once(self) -> None:
        self._dirty = False
        if not self._started.is_set():
            return
        record = self._build_record()
        await self._container.repository.save(record)

    def _build_record(self) -> ConversationRecord:
        return self.controller.build_record(
            self._cid,
            self._started_at,
            self._model_info(),
            channel=CHANNEL,
            transcript=self.transcript,
            metrics=self._metrics(),
        )

    async def _drain_flush(self) -> None:
        task = self._flush_task
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), self._timings.flush_s)
            except Exception as exc:  # includes TimeoutError
                self._flush_abandoned = isinstance(exc, TimeoutError)
                self._log.error("persist_failed", error=type(exc).__name__)

    async def _reassert_final(self, record: ConversationRecord) -> None:
        """The final record must win even when the drain gave up on a slow periodic flush.

        That flush still holds an older record and may land after the final save. Wait for it
        (bounded); if it is done, write the final record again so it is the last version stored.
        """
        task = self._flush_task
        if not self._flush_abandoned or task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), self._timings.stale_flush_s)
        except TimeoutError:
            self._log.error("stale_flush_unresolved")
            return
        except Exception as exc:  # the stale save failed: it wrote nothing, final stands
            self._log.error("persist_failed", error=type(exc).__name__)
            return
        try:
            await self._container.repository.save(record)
        except Exception as exc:
            self._log.error("final_resave_failed", error=type(exc).__name__)

    # -- watchdog ------------------------------------------------------------------------

    async def _watchdog(self) -> None:
        t = self._timings
        while True:
            await asyncio.sleep(t.tick_s)
            now = self._mono()
            idle = now - self._last_activity
            if self._started_mono is None:
                if idle >= t.silence_note_s * (t.silence_checkins + 1):  # never started
                    self._log.info("watchdog_silence_abandon")
                    self._request_end(EndReason.ABANDONED)
                    return
                continue
            elapsed = now - self._started_mono
            if elapsed >= t.hard_stop_s:
                self._log.info("watchdog_hard_stop")
                self._request_end(EndReason.ABANDONED)
                return
            if elapsed >= t.wrapup_s and not self._wrapup_noted:
                self._wrapup_noted = True
                self._send_content(WRAPUP_NOTE)
            if (
                idle >= t.silence_note_s
                and not self._goodbye_noted
                and self.controller.phase is not Phase.ENDED
            ):
                if self._silence_checkins < t.silence_checkins:
                    self._silence_checkins += 1
                    self._last_activity = now  # next check-in a full interval from now
                    self._send_content(SILENCE_NOTE)
                else:
                    self._log.info("watchdog_silence_abandon")
                    self.controller.end(EndReason.ABANDONED)
                    self._start_goodbye(EndReason.ABANDONED)
