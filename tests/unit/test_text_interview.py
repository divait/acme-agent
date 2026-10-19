"""TextInterview and `acme-agent chat` offline, with a scripted fake ADK model."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr
from structlog.testing import capture_logs
from typer.testing import CliRunner

import acme_agent.cli as cli
from acme_agent.agent.text import TextInterview
from acme_agent.bootstrap import build_container
from acme_agent.config import Settings
from acme_agent.domain.models import EndReason, Speaker
from acme_agent.storage.json_repo import validate_conversation_id

NOW = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)


def call(name: str, **args: Any) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def say(text: str) -> types.Part:
    return types.Part(text=text)


class FakeLlm(BaseLlm):
    """Pops one scripted list of parts per model call and records every request."""

    model: str = "fake"
    _script: list[list[types.Part]] = PrivateAttr(default_factory=list)
    _requests: list[LlmRequest] = PrivateAttr(default_factory=list)

    def __init__(self, script: list[list[types.Part]]) -> None:
        super().__init__(model="fake")
        self._script = list(script)

    @property
    def requests(self) -> list[LlmRequest]:
        return self._requests

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self._requests.append(llm_request)
        parts = self._script.pop(0) if self._script else [say("...")]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def user_texts(request: LlmRequest) -> list[str]:
    return [p.text for c in request.contents if c.role == "user" for p in (c.parts or []) if p.text]


def make(settings: Settings, script: list[list[types.Part]]) -> tuple[TextInterview, FakeLlm]:
    llm = FakeLlm(script)
    container = build_container(settings, clock=lambda: NOW)
    return TextInterview(container, language="es", clock=lambda: NOW, model=llm), llm


async def test_start_greets_and_sends_date_note(settings: Settings) -> None:
    ti, llm = make(settings, [[say("Hola, soy Ana. ¿Aceptas que grabemos?")]])
    assert await ti.start() == "Hola, soy Ana. ¿Aceptas que grabemos?"
    assert any("Today is 2026-10-18" in t for t in user_texts(llm.requests[0]))
    assert ti.controller.phase.value == "consent"
    validate_conversation_id(ti.conversation_id)
    assert ti.conversation_id.startswith("c_")


async def test_tool_calls_reach_controller_and_transcript(settings: Settings) -> None:
    script = [
        [say("Hola")],
        [call("record_field", field="consent_recording", value="yes", said="sí")],
        [say("Gracias. ¿Qué puesto buscas?")],
    ]
    ti, _ = make(settings, script)
    await ti.start()
    reply = await ti.send("sí, acepto")
    assert reply == "Gracias. ¿Qué puesto buscas?"
    assert ti.controller.profile.consent_recording is True
    assert [(t.turn, t.speaker) for t in ti.transcript] == [
        (1, Speaker.AGENT),
        (2, Speaker.CANDIDATE),
        (3, Speaker.AGENT),
    ]
    assert ti.transcript[1].text == "sí, acepto"
    assert not ti.is_over


async def test_human_request_note_prepended(settings: Settings) -> None:
    ti, llm = make(settings, [[say("Hola")], [say("Claro")]])
    await ti.start()
    await ti.send("quiero hablar con una persona")
    last = user_texts(llm.requests[-1])[-1]
    assert last.startswith("[SYSTEM NOTE]")
    assert last.endswith("quiero hablar con una persona")
    assert ti.transcript[1].text == "quiero hablar con una persona"


async def test_end_interview_tool_ends_session(settings: Settings) -> None:
    script = [
        [say("Hola")],
        [call("end_interview", reason="abandoned")],
        [say("Adiós")],
    ]
    ti, _ = make(settings, script)
    await ti.start()
    await ti.send("adiós")
    assert ti.is_over


async def test_close_saves_record(settings: Settings) -> None:
    script = [
        [say("Hola")],
        [call("record_field", field="consent_recording", value="yes", said="sí")],
        [say("Gracias")],
    ]
    ti, _ = make(settings, script)
    await ti.start()
    await ti.send("sí")
    record = await ti.close()
    assert record.end_reason is EndReason.ABANDONED
    assert record.model.text == settings.text_model
    assert record.model.prompt_version == "ana-v8"
    assert len(record.transcript) == 3
    assert any(e.type == "slot_filled" for e in record.events)
    saved = settings.data_dir.rglob("*.json")
    assert any(json.loads(p.read_text())["conversation_id"] == ti.conversation_id for p in saved)
    assert (await ti.close()).end_reason is EndReason.ABANDONED


async def test_close_after_escalation_without_end_interview_is_escalated(
    settings: Settings,
) -> None:
    script = [
        [say("Hola")],
        [call("escalate_to_human", reason="frustration")],
        [say("Un reclutador te llamará. Adiós")],
    ]
    ti, _ = make(settings, script)
    await ti.start()
    await ti.send("sí, que me llame una persona")
    assert not ti.is_over
    record = await ti.close()
    assert record.end_reason is EndReason.ESCALATED


async def test_text_record_has_metrics(settings: Settings) -> None:
    script = [
        [say("Hola")],
        [call("record_field", field="consent_recording", value="yes", said="sí")],
        [say("Gracias")],
    ]
    ti, _ = make(settings, script)
    await ti.start()
    await ti.send("sí")
    record = await ti.close()
    for key in ("duration_s", "candidate_turns", "agent_turns", "tool_calls", "validation_errors"):
        assert key in record.metrics, key
    assert record.metrics["candidate_turns"] == 1
    assert record.metrics["agent_turns"] == 2
    assert record.metrics["tool_calls"] == 1


def test_progress_line() -> None:
    snap: dict[str, Any] = {
        "slots": {
            "phone": {"status": "filled"},
            "preferred_store_id": {"status": "invalid"},
            "weekly_hours": {"status": "empty"},
            "driving_licence": {"status": "not_applicable"},
            "experience_summary": {"status": "empty"},
        }
    }
    assert cli.progress_line(snap) == "[1/3 slots] phone ✓ store ? hours ·"


def test_chat_command_quit(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    script = [[say("Hola, soy Ana.")], [say("¿Qué puesto buscas?")]]
    container = build_container(settings, clock=lambda: NOW)

    def factory(language: str) -> TextInterview:
        return TextInterview(container, language="es", clock=lambda: NOW, model=FakeLlm(script))

    monkeypatch.setattr(cli, "_make_interview", factory)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    result = CliRunner().invoke(cli.app, ["chat"], input="hola\n/quit\n")
    assert result.exit_code == 0, result.output
    assert "Ana: Hola, soy Ana." in result.output
    assert "Ana: ¿Qué puesto buscas?" in result.output
    assert "[0/" in result.output
    assert "abandoned" in result.output


def test_chat_model_error_is_one_line(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def boom(language: str) -> TextInterview:
        raise RuntimeError("no credentials")

    monkeypatch.setattr(cli, "_make_interview", boom)
    result = CliRunner().invoke(cli.app, ["chat", "--lang", "en"])
    assert result.exit_code == 1
    assert "gcloud auth application-default login" in result.output
    assert "GOOGLE_CLOUD_PROJECT" in result.output
    assert "Traceback" not in result.output


def test_chat_rejects_bad_lang() -> None:
    assert CliRunner().invoke(cli.app, ["chat", "--lang", "fr"]).exit_code == 2


class RaisingLlm(FakeLlm):
    def __init__(self, script: list[list[types.Part]]) -> None:
        super().__init__(script)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if self.requests:
            raise RuntimeError("model exploded")
        async for r in super().generate_content_async(llm_request, stream):
            yield r


def test_chat_model_failure_mid_interview_saves_abandoned(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = build_container(settings, clock=lambda: NOW)

    def factory(language: str) -> TextInterview:
        return TextInterview(
            container, language="es", clock=lambda: NOW, model=RaisingLlm([[say("Hola")]])
        )

    monkeypatch.setattr(cli, "_make_interview", factory)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    result = CliRunner().invoke(cli.app, ["chat"], input="hola\n")
    assert result.exit_code == 1
    assert "model exploded" in result.output
    assert "Traceback" not in result.output
    records = asyncio.run(container.repository.list(None))
    assert len(records) == 1
    assert records[0].end_reason is EndReason.ABANDONED
    assert records[0].conversation_id in result.output


def test_chat_without_project_prints_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(GOOGLE_CLOUD_PROJECT=""))
    result = CliRunner().invoke(cli.app, ["chat"])
    assert result.exit_code == 1
    assert "GOOGLE_CLOUD_PROJECT is not set. Copy .env.example to .env" in result.output
    assert "validation error" not in result.output


async def test_text_interview_saves_text_channel(settings: Settings) -> None:
    ti, _ = make(settings, [[say("Hola")]])
    await ti.start()
    record = await ti.close()
    assert record.channel == "text"


async def test_start_note_states_language_and_sets_marker(settings: Settings) -> None:
    llm = FakeLlm([[say("Hi")]])
    container = build_container(settings, clock=lambda: NOW)
    ti = TextInterview(container, language="en", clock=lambda: NOW, model=llm)
    await ti.start()
    assert any("Greet them as Ana in English" in t for t in user_texts(llm.requests[0]))
    assert ti.controller.language == "en"


# -- read-back guard ---------------------------------------------------------------------

LEAD_IN = "Para confirmar, tus datos son:"
DETAILS = (
    "Puesto crew, Laura Gil, teléfono 600 12 34 56, tienda Sol, empiezas el 3 de noviembre. "
    "¿Correcto?"
)


async def at_confirm(
    settings: Settings, script: list[list[types.Part]]
) -> tuple[TextInterview, FakeLlm]:
    ti, llm = make(settings, [[say("Hola")], *script])
    await ti.start()
    ti.controller.record("consent_recording", "yes")
    for field, value in [
        ("role", "crew_member"),
        ("full_name", "Laura Gil"),
        ("phone", "600 123 456"),
        ("preferred_store_id", "Sol"),
        ("availability", "mon:morning"),
        ("weekly_hours", "25"),
        ("start_date", "2026-11-03"),
        ("right_to_work", "yes"),
        ("is_18_or_over", "yes"),
        ("experience_months", "18"),
    ]:
        ti.controller.record(field, value)
    return ti, llm


async def test_leadin_only_reply_triggers_one_reprompt(settings: Settings) -> None:
    ti, llm = await at_confirm(
        settings, [[call("confirm_profile")], [say(LEAD_IN)], [say(DETAILS)]]
    )
    reply = await ti.send("ya")
    assert len(llm.requests) == 4  # greeting, tool call, lead-in, re-prompt
    note = user_texts(llm.requests[-1])[-1]
    assert note.startswith("[SYSTEM NOTE] You have not read the details back yet")
    assert "Please confirm: role crew_member" in note
    assert reply == f"{LEAD_IN}\n{DETAILS}"
    assert not ti.controller.readback_pending
    assert all("[SYSTEM NOTE]" not in t.text for t in ti.transcript)
    assert ti.transcript[-1].text == reply


async def test_reply_with_details_does_not_reprompt(settings: Settings) -> None:
    ti, llm = await at_confirm(settings, [[call("confirm_profile")], [say(DETAILS)]])
    reply = await ti.send("ya")
    assert len(llm.requests) == 3
    assert reply == DETAILS
    assert not ti.controller.readback_pending


async def test_failed_reprompt_is_not_repeated_and_warns(settings: Settings) -> None:
    ti, llm = await at_confirm(
        settings,
        [[call("confirm_profile")], [say(LEAD_IN)], [say("Un momento.")], [say("sigo")]],
    )
    with capture_logs() as logs:
        reply = await ti.send("ya")
    assert reply == f"{LEAD_IN}\nUn momento."
    assert len(llm.requests) == 4
    assert [e["event"] for e in logs if e["log_level"] == "warning"] == [
        "readback_missing_after_reprompt"
    ]
    assert not ti.controller.readback_pending
    await ti.send("sí")  # no further re-prompt on the next turn
    assert len(llm.requests) == 5


def test_chat_invalid_configuration_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> Settings:
        return Settings(storage="nope")

    monkeypatch.setattr(cli, "get_settings", boom)
    result = CliRunner().invoke(cli.app, ["chat"])
    assert result.exit_code == 1
    assert "Invalid configuration" in result.output


async def test_said_unverified_in_text_mode_record(settings: Settings) -> None:
    script = [
        [say("Hola")],
        [call("record_field", field="consent_recording", value="yes", said="sí")],
        [say("Gracias")],
        [call("record_field", field="preferred_store_id", value="Sol", said="Acme Burgers Sol")],
        [say("ok")],
    ]
    ti, _ = make(settings, script)
    await ti.start()
    await ti.send("sí")
    await ti.send("no sé, mañana puedo")
    record = await ti.close()
    assert record.metrics["said_unverified"] == ["preferred_store_id"]


async def test_silent_end_gets_one_goodbye_reprompt(settings: Settings) -> None:
    script = [
        [say("Hola")],
        [call("end_interview", reason="completed")],
        [say("")],  # the model ends the call without a word
        [say("Gracias, hasta pronto.")],
    ]
    ti, llm = make(settings, script)
    await ti.start()
    reply = await ti.send("sí, es correcto")
    assert ti.is_over
    assert reply == "Gracias, hasta pronto."
    notes = [t for t in user_texts(llm.requests[-1]) if "The interview has ended" in t]
    assert len(notes) == 1 and "hiring team" in notes[0]
    assert len(llm.requests) == 4


async def test_silent_escalated_end_without_phone_gets_no_callback_goodbye(
    settings: Settings,
) -> None:
    script = [
        [say("Hola")],
        [call("record_field", field="consent_recording", value="yes", said="sí")],
        [say("ok")],
        [call("escalate_to_human", reason="frustration")],
        [call("end_interview", reason="escalated")],
        [say("")],
        [say("Hasta luego.")],
    ]
    ti, llm = make(settings, script)
    await ti.start()
    await ti.send("sí")
    await ti.send("quiero hablar con una persona")
    notes = [t for t in user_texts(llm.requests[-1]) if "The interview has ended" in t]
    assert len(notes) == 1 and "will call" not in notes[0] and "hiring team" in notes[0]


async def test_spoken_goodbye_does_not_reprompt(settings: Settings) -> None:
    script = [[say("Hola")], [call("end_interview", reason="completed")], [say("Adiós")]]
    ti, llm = make(settings, script)
    await ti.start()
    await ti.send("adiós")
    assert ti.is_over
    assert len(llm.requests) == 3
