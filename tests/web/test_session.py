"""InterviewSession with a fake live runner: offline, millisecond timings."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
import structlog
from fastapi import WebSocket
from fastapi.testclient import TestClient
from google.adk.events import Event as AdkEvent
from google.auth.exceptions import RefreshError
from google.genai import types
from ulid import ULID

from acme_agent.bootstrap import AppContainer, SaveOnlyFinalizer, build_container
from acme_agent.config import Settings
from acme_agent.domain.models import ConversationRecord, EndReason
from acme_agent.web.app import create_app
from acme_agent.web.session import InterviewSession, RunnerSetup, Timings

NOW = datetime(2026, 10, 18, 20, 30, tzinfo=UTC)
ORIGIN = {"origin": "http://localhost:8000"}
CREW = [
    ("role", "crew_member"),
    ("full_name", "Laura Gil"),
    ("phone", "600 123 456"),
    ("preferred_store_id", "Sol"),
    ("availability", "mon:morning,sat:night"),
    ("weekly_hours", "25"),
    ("start_date", "2026-11-03"),
    ("right_to_work", "yes"),
    ("is_18_or_over", "yes"),
    ("experience_months", "18"),
]
FAST = Timings(flush_s=0.02, silence_note_s=5, tick_s=0.005)


class FakeWebSocket:
    """Just enough of Starlette's WebSocket for `receive_frame` and the session's sends."""

    def __init__(self) -> None:
        self.incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.texts: list[dict[str, Any]] = []
        self.audio: list[bytes] = []
        self.frames: list[str] = []  # ordered: "audio" or the JSON message type

    def push_text(self, payload: dict[str, Any]) -> None:
        self.incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(payload)})

    def push_bytes(self, data: bytes) -> None:
        self.incoming.put_nowait({"type": "websocket.receive", "bytes": data})

    def disconnect(self) -> None:
        self.incoming.put_nowait({"type": "websocket.disconnect"})

    async def receive(self) -> dict[str, Any]:
        return await self.incoming.get()

    async def send_text(self, data: str) -> None:
        self.texts.append(json.loads(data))
        self.frames.append(self.texts[-1]["type"])

    async def send_bytes(self, data: bytes) -> None:
        self.audio.append(data)
        self.frames.append("audio")

    def types(self) -> list[str]:
        return [m["type"] for m in self.texts]


Script = Callable[[RunnerSetup], AsyncIterator[AdkEvent]]


def audio(data: bytes = b"\x01\x02") -> AdkEvent:
    part = types.Part(inline_data=types.Blob(data=data, mime_type="audio/pcm;rate=24000"))
    return AdkEvent(author="ana", content=types.Content(role="model", parts=[part]))


def said(text: str, finished: bool = True) -> AdkEvent:
    return AdkEvent(
        author="ana", output_transcription=types.Transcription(text=text, finished=finished)
    )


def heard(text: str, finished: bool = True) -> AdkEvent:
    return AdkEvent(
        author="user", input_transcription=types.Transcription(text=text, finished=finished)
    )


def call(name: str) -> AdkEvent:
    part = types.Part(function_call=types.FunctionCall(name=name, args={}))
    return AdkEvent(author="ana", content=types.Content(role="model", parts=[part]))


def done() -> AdkEvent:
    return AdkEvent(author="ana", turn_complete=True)


async def hold() -> None:
    await asyncio.sleep(30)


@pytest.fixture
def container(settings: Settings) -> AppContainer:
    return build_container(settings, clock=lambda: NOW)


def make_session(
    ws: FakeWebSocket,
    container: AppContainer,
    script: Script,
    cid: str | None = None,
    timings: Timings = FAST,
) -> InterviewSession:
    return InterviewSession(
        ws,  # type: ignore[arg-type]
        cid or f"c_{ULID()}",
        container,
        runner_factory=script,
        timings=timings,
    )


async def stored(container: AppContainer, session: InterviewSession) -> ConversationRecord:
    record = await container.repository.get(session._cid)
    assert record is not None
    return record


async def run_to_end(session: InterviewSession, timeout: float = 5) -> None:
    await asyncio.wait_for(session.run(), timeout)


async def test_happy_path(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield audio()
        yield heard("sí aceptó", finished=False)
        yield heard("Sí, acepto")
        yield call("record_field")
        setup.tools["record_field"]("consent_recording", "yes", "sí acepto")
        await asyncio.sleep(0.01)
        yield said("Gracias. ¿Cómo te", finished=False)
        yield said("Gracias. ¿Cómo te llamas?")
        yield done()
        yield call("end_interview")
        setup.tools["end_interview"]("completed")
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start", "locale": "en-US"})
    ws.push_text({"type": "ping"})
    await run_to_end(session)

    kinds = ws.types()
    assert kinds[-2:] == ["ended", "completed"]
    assert {"pong", "transcript", "slot", "state"} <= set(kinds)
    assert ws.audio == [b"\x01\x02"]
    transcripts = [m for m in ws.texts if m["type"] == "transcript"]
    assert [(m["speaker"], m["final"]) for m in transcripts] == [
        ("candidate", False),
        ("candidate", True),
        ("agent", False),
        ("agent", True),
    ]
    slot = next(m for m in ws.texts if m["type"] == "slot")
    assert (slot["name"], slot["status"], slot["value"]) == ("consent_recording", "filled", "true")
    assert ws.texts[-2]["reason"] == "completed"
    last = ws.texts[-1]
    assert last == {
        "type": "completed",
        "summary": None,
        "status": last["status"],
        "reasons": last["reasons"],
        "end_reason": "completed",
        "sentiment": last["sentiment"],
        "profile": last["profile"],
        "complete": False,
    }
    assert last["profile"]["consent_recording"]["status"] == "filled"
    assert last["profile"]["full_name"] == {
        "value": None,
        "display": None,
        "status": "missing",
        "required": True,
    }
    # Date context and greeting go in ONE content turn: each turn makes the model reply, so
    # two turns made the real model greet twice.
    first = session.sent_content[0]
    assert first.startswith("[SYSTEM NOTE] Today is ")
    assert first.endswith("[SYSTEM NOTE] Greet the candidate as Ana in English.")
    assert not any("Greet the candidate" in c for c in session.sent_content[1:])

    record = await stored(container, session)
    assert record.channel == "web_voice"
    assert record.end_reason is EndReason.COMPLETED
    assert [t.speaker.value for t in record.transcript] == ["candidate", "agent"]
    assert record.language.detected == "en"
    m = record.metrics
    assert m["candidate_turns"] == 1 and m["agent_turns"] == 1
    assert m["tool_calls"] == 2 and m["interruptions"] == 0
    assert m["time_to_first_agent_audio_ms"] is not None
    assert m["turn_latencies_ms"] == [] or m["median_turn_latency_ms"] is not None


async def test_completed_frame_carries_the_post_call_summary(container: AppContainer) -> None:
    from acme_agent.domain.models import Summary

    class SummarisingFinalizer(SaveOnlyFinalizer):
        async def finalize(self, controller, transcript, **kw):  # type: ignore[no-untyped-def]
            record = await super().finalize(controller, transcript, **kw)
            record.summary = Summary(headline="H", key_points=["a", "b", "c"])
            return record

    container.finalizer = SummarisingFinalizer(container.repository)
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield said("hola")
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    ws.push_text({"type": "start", "locale": "en-US"})
    await run_to_end(make_session(ws, container, script))
    last = ws.texts[-1]
    assert last["type"] == "completed"
    assert last["summary"]["headline"] == "H" and last["summary"]["key_points"] == ["a", "b", "c"]


async def test_completed_frame_carries_the_final_profile(container: AppContainer) -> None:
    store = container.parse_context_factory().stores[0]

    class FillingFinalizer(SaveOnlyFinalizer):
        async def finalize(self, controller, transcript, **kw):  # type: ignore[no-untyped-def]
            controller.profile.email = "ana@example.com"  # a post-call fill
            controller.profile.preferred_store_id = store.id
            return await super().finalize(controller, transcript, **kw)

    container.finalizer = FillingFinalizer(container.repository)
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield said("hola")
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    ws.push_text({"type": "start", "locale": "en-US"})
    await run_to_end(make_session(ws, container, script))
    last = ws.texts[-1]
    profile = last["profile"]
    assert profile["email"] == {
        "value": "ana@example.com",
        "display": None,
        "status": "filled",
        "required": False,
    }
    assert profile["preferred_store_id"]["display"] == store.name
    assert profile["preferred_store_id"]["value"] == store.id
    assert "driving_licence" not in profile  # rider-only slot, role unknown
    assert last["complete"] is False  # required slots are still missing
    assert len(json.dumps(last)) < 100_000


async def test_ended_is_sent_before_post_call_and_completed_after(
    container: AppContainer,
) -> None:
    release = asyncio.Event()
    seen_at_finalize: list[list[str]] = []
    ws = FakeWebSocket()

    class SlowFinalizer(SaveOnlyFinalizer):
        async def finalize(self, controller, transcript, **kw):  # type: ignore[no-untyped-def]
            seen_at_finalize.append(ws.types())
            await release.wait()
            return await super().finalize(controller, transcript, **kw)

    container.finalizer = SlowFinalizer(container.repository)

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield said("hola")
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    task = asyncio.create_task(session.run())
    await _wait_for(lambda: "ended" in ws.types())
    assert not task.done() and "completed" not in ws.types()
    release.set()
    await asyncio.wait_for(task, 5)
    assert "ended" in seen_at_finalize[0]
    assert ws.types()[-2:] == ["ended", "completed"]


async def test_error_frame_precedes_ended(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield AdkEvent(author="ana", error_code="500", error_message="boom")

    ws.push_text({"type": "start"})
    await run_to_end(make_session(ws, container, script))
    types = ws.types()
    assert types.index("error") < types.index("ended") < types.index("completed")


async def test_store_slot_carries_display_name(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield call("record_field")
        setup.tools["record_field"]("consent_recording", "yes", "sí")
        setup.tools["record_field"]("preferred_store_id", "Sol", "Sol")
        await asyncio.sleep(0.05)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start", "locale": "en-US"})
    await run_to_end(session)
    slots = {m["name"]: m for m in ws.texts if m["type"] == "slot"}
    assert slots["preferred_store_id"]["status"] == "filled"
    assert slots["preferred_store_id"]["value"] == "mad-sol"
    assert slots["preferred_store_id"]["display"] == "Acme Burgers Sol"
    assert slots["consent_recording"]["display"] is None


async def test_audio_forwarded_upstream_after_start(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        await asyncio.sleep(0.02)
        for _ in range(3):
            blob = await asyncio.wait_for(setup.queue.get(), 1)
            if blob.blob is not None:
                assert blob.blob.mime_type == "audio/pcm;rate=16000"
                assert blob.blob.data == b"pcm"
                break
        yield done()
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_bytes(b"dropped-before-start")
    ws.push_text({"type": "start"})
    await asyncio.sleep(0)
    ws.push_bytes(b"pcm")
    await run_to_end(session)


async def test_latency_and_first_audio(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield audio()
        yield heard("hola")
        await asyncio.sleep(0.02)
        yield audio()
        yield done()
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    record = await stored(container, session)
    assert len(record.metrics["turn_latencies_ms"]) == 1
    assert record.metrics["turn_latencies_ms"][0] >= 15
    assert record.metrics["median_turn_latency_ms"] == record.metrics["turn_latencies_ms"][0]


async def test_latency_anchored_on_last_candidate_input(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield heard("hola", finished=False)  # partial only; never finalised by the model
        await asyncio.sleep(0.05)
        yield audio()  # flushes the partial, then the reply latency is measured
        yield said("Hola, soy Ana", finished=True)
        yield heard("vale", finished=False)
        await asyncio.sleep(0.05)
        yield said("Perfecto", finished=False)  # agent transcription arrives first
        yield audio()
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    record = await stored(container, session)
    lat = record.metrics["turn_latencies_ms"]
    assert len(lat) == 2 and all(v >= 45 for v in lat)


@pytest.mark.parametrize(
    ("locale", "language", "name"),
    [("es-ES", "es", "Spanish"), ("en-US", "en", "English")],
)
async def test_start_locale_sets_controller_language_and_greeting(
    container: AppContainer, locale: str, language: str, name: str
) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield done()
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start", "locale": locale})
    await run_to_end(session)
    assert f"Greet the candidate as Ana in {name}" in session.sent_content[0]
    assert session._language == language


async def test_text_turn_and_human_request_note(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield heard("quiero hablar con una persona")
        yield done()
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    ws.push_text({"type": "text", "text": "hola, quiero una persona real"})
    await run_to_end(session)
    notes = [c for c in session.sent_content if "recruiter" in c.lower() or "person" in c.lower()]
    assert len(notes) >= 2  # typed turn carries the note, and so does the spoken one
    assert any(c.endswith("hola, quiero una persona real") for c in session.sent_content)


async def test_interruption_forwarded(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        setup.tools["record_field"]("consent_recording", "yes", "sí acepto")
        yield audio()
        yield said("Un momento", finished=False)
        yield AdkEvent(author="ana", interrupted=True)
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert "interrupted" in ws.types()
    record = await stored(container, session)
    assert record.metrics["interruptions"] == 1
    assert [t.text for t in record.transcript] == ["Un momento"]


async def test_vad_start_without_agent_audio_is_not_an_interruption(
    container: AppContainer,
) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield AdkEvent(author="ana", interrupted=True)  # no audio yet
        yield audio()
        await asyncio.sleep(0.35)  # Ana stopped speaking a while ago
        yield AdkEvent(author="ana", interrupted=True)
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert ws.types().count("interrupted") == 2  # always forwarded
    assert (await stored(container, session)).metrics["interruptions"] == 0


async def test_said_unverified_metric_advisory(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        ctl = setup.controller
        ctl.record("consent_recording", "yes")
        yield heard("me llamo Marta Lopez")
        ctl.record("full_name", "Marta Lopez", "Marta Lopez")
        ctl.record("preferred_store_id", "Acme Burgers Sol", "Acme Burgers Sol")
        ctl.end(EndReason.COMPLETED)
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    record = await stored(container, session)
    assert record.metrics["said_unverified"] == ["preferred_store_id"]


def readback_script(agent_text: str) -> Script:
    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        ctl = setup.controller
        ctl.record("consent_recording", "yes")
        for field, value in CREW:
            ctl.record(field, value)
        setup.tools["confirm_profile"]()
        yield said(agent_text)
        yield done()
        yield done()  # a second turn must not send a second note
        ctl.end(EndReason.COMPLETED)
        yield done()

    return script


async def test_readback_guard_sends_one_note_when_details_missing(
    container: AppContainer,
) -> None:
    ws = FakeWebSocket()
    session = make_session(ws, container, readback_script("Perfecto, ¿todo bien?"))
    ws.push_text({"type": "start"})
    await run_to_end(session)
    notes = [c for c in session.sent_content if c.startswith("[SYSTEM NOTE] You have not read")]
    assert len(notes) == 1
    assert "Please confirm: role crew_member" in notes[0]
    assert not session.controller.readback_pending


async def test_readback_guard_silent_when_details_read(container: AppContainer) -> None:
    ws = FakeWebSocket()
    text = (
        "Confirmo: puesto de crew member, Laura Gil, teléfono 600 123 456, "
        "empiezas el 3 de noviembre "
        "en Acme Burgers Sol. ¿Es correcto?"
    )
    session = make_session(ws, container, readback_script(text))
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert not [c for c in session.sent_content if "have not read" in c]


async def test_silence_checkins_then_spoken_goodbye_and_abandon(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        await hold()
        yield done()

    timings = Timings(flush_s=0.02, silence_note_s=0.03, goodbye_s=0.05, tick_s=0.005)
    session = make_session(ws, container, script, timings=timings)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    notes = [c for c in session.sent_content if c.startswith("[SYSTEM NOTE]")]
    assert len([c for c in notes if "silent" in c]) == 3
    assert "not answering" in notes[-1] and "hasta luego" in notes[-1]
    assert ws.types()[-2:] == ["ended", "completed"]
    record = await stored(container, session)
    assert record.end_reason is EndReason.ABANDONED


async def test_client_end_after_escalation_ends_escalated(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        await hold()
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    session.controller.escalate("candidate_request")
    ws.push_text({"type": "end"})
    await run_to_end(session)
    record = await stored(container, session)
    assert record.end_reason is EndReason.ESCALATED
    assert next(m for m in ws.texts if m["type"] == "ended")["reason"] == "escalated"


async def test_candidate_speaking_resets_checkin_count(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        while len([c for c in session.sent_content if "silent" in c]) < 2:
            await asyncio.sleep(0.005)
        yield heard("Sigo aquí")
        await hold()
        yield done()

    timings = Timings(flush_s=0.02, silence_note_s=0.05, goodbye_s=0.05, tick_s=0.005)
    session = make_session(ws, container, script, timings=timings)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    # 2 check-ins, a reply, then a fresh round of 3 before the goodbye.
    assert len([c for c in session.sent_content if "silent" in c]) == 5
    assert len([c for c in session.sent_content if "not answering" in c]) == 1


async def test_wrapup_and_hard_stop(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        while True:
            await asyncio.sleep(0.005)
            yield audio()  # agent activity keeps the silence timer quiet

    timings = Timings(flush_s=0.02, wrapup_s=0.03, hard_stop_s=0.1, tick_s=0.005)
    session = make_session(ws, container, script, timings=timings)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert len([c for c in session.sent_content if "Wrap up" in c]) == 1
    assert (await stored(container, session)).end_reason is EndReason.ABANDONED


async def test_client_end_and_disconnect_abandon(container: AppContainer) -> None:
    for how in ("end", "disconnect"):
        ws = FakeWebSocket()

        async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
            await hold()
            yield done()

        session = make_session(ws, container, script)
        ws.push_text({"type": "start"})
        ws.push_text({"type": "bogus"})
        if how == "end":
            ws.push_text({"type": "end"})
        else:
            ws.disconnect()
        await run_to_end(session)
        assert (await stored(container, session)).end_reason is EndReason.ABANDONED
        assert ("error" in ws.types()) is True
        assert ws.texts[0]["code"] == "unknown_type"
        if how == "end":
            assert ws.types()[-2:] == ["ended", "completed"]
        else:
            assert "ended" not in ws.types()  # socket gone: nothing is sent


async def test_model_error_event_abandons_with_error_frame(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield AdkEvent(author="ana", error_code="500", error_message="boom")

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    err = next(m for m in ws.texts if m["type"] == "error")
    assert err["code"] == "session_failed"
    assert ws.types()[-2:] == ["ended", "completed"]
    assert (await stored(container, session)).end_reason is EndReason.ABANDONED


async def test_expired_credentials_log_operator_hint(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        raise RefreshError("expired")  # type: ignore[no-untyped-call]
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    with structlog.testing.capture_logs() as logs:
        await run_to_end(session)
    failed = next(entry for entry in logs if entry["event"] == "session_task_failed")
    assert failed["error"] == "RefreshError"
    assert failed["hint"] == "run: gcloud auth application-default login"
    err = next(m for m in ws.texts if m["type"] == "error")
    assert err["code"] == "session_failed"
    assert "gcloud" not in err["message"]


async def _wait_for(cond: Callable[[], bool]) -> None:
    for _ in range(500):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


@pytest.mark.parametrize("task", ["upstream", "downstream", "pump", "persister", "watchdog"])
async def test_exception_in_any_task_abandons_only_that_session(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch, task: str
) -> None:
    async def healthy(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        await asyncio.sleep(0.15)
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    async def idle(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        await hold()
        yield done()

    ws_bad, ws_ok = FakeWebSocket(), FakeWebSocket()
    bad = make_session(ws_bad, container, idle)
    ok = make_session(ws_ok, container, healthy)

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("injected")

    target = {
        "upstream": "_upstream",
        "pump": "_pump_controller_events",
        "persister": "_persister",
        "watchdog": "_watchdog",
    }.get(task)
    if target:
        monkeypatch.setattr(bad, target, boom)
    else:

        async def bad_script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
            raise RuntimeError("injected")
            yield done()  # pragma: no cover

        bad._runner_factory = bad_script
    for ws in (ws_bad, ws_ok):
        ws.push_text({"type": "start"})
    await asyncio.wait_for(asyncio.gather(bad.run(), ok.run()), 5)

    assert "error" in ws_bad.types() and ws_bad.types()[-2:] == ["ended", "completed"]
    if task == "upstream":  # never reached `start`: nothing stored
        assert await container.repository.get(bad._cid) is None
    else:
        assert (await stored(container, bad)).end_reason is EndReason.ABANDONED
    assert "error" not in ws_ok.types()
    assert (await stored(container, ok)).end_reason is EndReason.COMPLETED


class SlowRepository:
    """Wraps a repository; the first `save` (a periodic flush) stalls before writing."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.saves = 0
        self.started = asyncio.Event()  # set once the stalled flush is in flight
        self.release = asyncio.Event()

    async def save(self, record: ConversationRecord) -> None:
        self.saves += 1
        if self.saves == 1:
            self.started.set()
            await self.release.wait()  # stale flush: holds the pre-final record
        await self.inner.save(record)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


async def test_final_record_wins_over_in_flight_flush(container: AppContainer) -> None:
    slow = SlowRepository(container.repository)
    container.repository = slow
    container.finalizer = SaveOnlyFinalizer(slow)
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield said("hola")  # makes the session dirty -> a flush starts and stalls
        await slow.started.wait()
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    async def release_later() -> None:
        await slow.started.wait()
        await session._stop.wait()  # the session is ending; `_finish` now drains the flush
        slow.release.set()

    # A long flush interval keeps the drain timeout out of play: ordering is event-driven only.
    session = make_session(ws, container, script, timings=replace(FAST, flush_s=30))
    ws.push_text({"type": "start"})
    await asyncio.wait_for(asyncio.gather(session.run(), release_later()), 5)
    # The stalled flush finished first (drained), then the final save replaced it.
    assert slow.saves >= 2
    record = await stored(container, session)
    assert record.end_reason is EndReason.COMPLETED
    assert record.ended_at is not None


async def test_final_record_wins_after_timed_out_drain(container: AppContainer) -> None:
    slow = SlowRepository(container.repository)
    container.repository = slow
    container.finalizer = SaveOnlyFinalizer(slow)
    ws = FakeWebSocket()
    final_saved = asyncio.Event()
    orig_save = slow.save

    async def tracking_save(record: ConversationRecord) -> None:
        await orig_save(record)
        if record.ended_at is not None:
            final_saved.set()

    slow.save = tracking_save  # type: ignore[method-assign]

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield said("hola")  # dirty -> periodic flush starts and stalls
        await slow.started.wait()
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    async def release_later() -> None:
        await final_saved.wait()  # drain timed out and the final record is already stored
        slow.release.set()  # now the stale flush completes, with its older record

    session = make_session(
        ws, container, script, timings=replace(FAST, flush_s=0.02, stale_flush_s=10)
    )
    ws.push_text({"type": "start"})
    await asyncio.wait_for(asyncio.gather(session.run(), release_later()), 5)
    record = await stored(container, session)
    assert record.end_reason is EndReason.COMPLETED
    assert record.ended_at is not None
    assert ws.types()[-2:] == ["ended", "completed"]


async def test_consent_refusal_every_version_redacted(container: AppContainer) -> None:
    saved: list[ConversationRecord] = []
    inner = container.repository

    class Spy:
        async def save(self, record: ConversationRecord) -> None:
            saved.append(record.model_copy(deep=True))
            await inner.save(record)

    container.repository = Spy()  # type: ignore[assignment]
    container.finalizer = SaveOnlyFinalizer(Spy())  # type: ignore[arg-type]
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        setup.tools["record_field"]("consent_recording", "no", "no")
        setup.tools["record_field"]("consent_recording", "no", "no")
        setup.tools["record_field"]("full_name", "Laura Gil", "Laura Gil")
        yield said("Entendido, gracias.")
        await asyncio.sleep(0.08)  # let a periodic flush run
        setup.tools["end_interview"]("declined_consent")
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert len(saved) >= 2
    for record in saved:
        assert record.candidate.full_name is None
        assert set(record.slot_meta) <= {"consent_recording"}
        assert not [e for e in record.events if e.payload.get("field") == "full_name"]
    assert saved[-1].end_reason is EndReason.DECLINED_CONSENT
    assert saved[-1].channel == "web_voice"
    for record in saved:
        assert record.transcript == []
        assert "said_unverified" not in record.metrics
        assert "candidate_turns" in record.metrics


async def test_declined_consent_transcript_not_stored(container: AppContainer) -> None:
    ws = FakeWebSocket()
    pii = "No, no acepto. Me llamo Laura Gil, mi móvil es 600123456"

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield heard(pii)
        setup.tools["record_field"]("consent_recording", "no", "no acepto")
        setup.tools["record_field"]("consent_recording", "no", "no acepto")
        setup.tools["record_field"]("full_name", "Laura Gil", "Laura Gil")
        yield said("Entendido, gracias.")
        await asyncio.sleep(0.08)
        setup.tools["end_interview"]("declined_consent")
        yield done()

    saved: list[ConversationRecord] = []
    inner = container.repository

    class Spy:
        async def save(self, record: ConversationRecord) -> None:
            saved.append(record.model_copy(deep=True))
            await inner.save(record)

    container.repository = Spy()  # type: ignore[assignment]
    container.finalizer = SaveOnlyFinalizer(Spy())  # type: ignore[arg-type]
    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert saved
    for record in saved:
        assert record.transcript == []
        assert "said_unverified" not in record.metrics
        assert "Laura" not in record.model_dump_json()
    assert not session.controller._recent_candidate


async def test_abandoned_before_consent_stores_no_transcript(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield heard("Hola, me llamo Laura Gil")
        yield said("Hola")
        await hold()
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    ws.push_text({"type": "end"})
    await run_to_end(session)
    record = await stored(container, session)
    assert record.end_reason is EndReason.ABANDONED
    assert record.transcript == []
    assert "said_unverified" not in record.metrics


async def test_socket_without_start_stores_nothing(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "end"})
    await run_to_end(session)
    assert await container.repository.get(session._cid) is None


def test_session_factory_through_gateway(container: AppContainer) -> None:
    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield audio()
        setup.controller.end(EndReason.COMPLETED)
        yield done()

    def factory(ws: WebSocket, conversation_id: str, container: AppContainer) -> InterviewSession:
        return InterviewSession(ws, conversation_id, container, runner_factory=script, timings=FAST)

    client = TestClient(create_app(container, session_factory=factory))
    cid = client.post("/api/interviews").json()["conversation_id"]
    with client.websocket_connect(f"/ws/interview/{cid}", headers=ORIGIN) as ws:
        ws.send_text('{"type":"start","locale":"es-ES"}')
        seen: list[str] = []
        while True:
            msg = ws.receive()
            if msg.get("bytes") is not None:
                seen.append("audio")
                assert msg["bytes"] == b"\x01\x02"
                continue
            kind = json.loads(msg["text"])["type"]
            if kind == "completed":
                break
            seen.append(kind)
        assert "audio" in seen
        assert seen[-1] == "ended"


def goodbye_notes(session: InterviewSession) -> list[str]:
    return [
        c for c in session.sent_content if c.startswith("[SYSTEM NOTE] The interview has ended")
    ]


async def test_silent_end_sends_one_goodbye_note_and_closes_after_next_turn(
    container: AppContainer,
) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        setup.tools["end_interview"]("completed")
        yield done()  # ended without a word: the note goes out
        await asyncio.sleep(0.02)
        assert len(goodbye_notes(session)) == 1
        yield audio(b"bye")
        yield said("Gracias, hasta pronto.")
        yield done()
        await hold()

    session = make_session(ws, container, script, timings=replace(FAST, goodbye_s=10))
    ws.push_text({"type": "start"})
    await run_to_end(session)
    notes = goodbye_notes(session)
    assert len(notes) == 1 and "hiring team" in notes[0]
    assert ws.audio == [b"bye"]
    assert ws.frames.index("audio") < ws.frames.index("ended")
    kinds = ws.types()
    assert kinds[-2:] == ["ended", "completed"]
    assert kinds.index("ended") > max(
        i for i, m in enumerate(ws.texts) if m["type"] == "transcript"
    )


async def test_spoken_goodbye_sends_no_note(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        yield audio()
        yield said("Gracias, hasta pronto.")
        setup.tools["end_interview"]("completed")
        yield done()

    session = make_session(ws, container, script)
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert goodbye_notes(session) == []


async def test_silent_end_without_another_turn_closes_after_timeout(
    container: AppContainer,
) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        setup.tools["end_interview"]("declined_consent")
        yield done()
        await hold()

    session = make_session(ws, container, script, timings=replace(FAST, goodbye_s=0.05))
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert len(goodbye_notes(session)) == 1
    assert "nothing" in goodbye_notes(session)[0]
    assert ws.types()[-2:] == ["ended", "completed"]


async def test_goodbye_audio_near_deadline_is_not_cut(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        setup.tools["end_interview"]("completed")
        yield done()
        await asyncio.sleep(0.15)  # just before the 0.2 s deadline
        for _ in range(4):
            yield audio(b"bye")
            await asyncio.sleep(0.1)  # runs well past the original deadline
        yield said("Gracias, hasta pronto.")
        yield done()
        await hold()

    session = make_session(ws, container, script, timings=replace(FAST, goodbye_s=0.2))
    ws.push_text({"type": "start"})
    await run_to_end(session)
    assert ws.audio == [b"bye"] * 4
    assert ws.frames.index("ended") > max(i for i, f in enumerate(ws.frames) if f == "audio")


async def test_user_end_during_goodbye_wait_closes_at_once(container: AppContainer) -> None:
    ws = FakeWebSocket()

    async def script(setup: RunnerSetup) -> AsyncIterator[AdkEvent]:
        setup.tools["end_interview"]("completed")
        yield done()
        await hold()

    session = make_session(ws, container, script, timings=replace(FAST, goodbye_s=30))
    ws.push_text({"type": "start"})
    run = asyncio.create_task(session.run())
    await asyncio.sleep(0.1)
    assert len(goodbye_notes(session)) == 1
    ws.push_text({"type": "end"})
    await asyncio.wait_for(run, 2)
    assert ws.types()[-2:] == ["ended", "completed"]
