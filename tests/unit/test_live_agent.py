"""Live run config and agent, offline."""

from __future__ import annotations

from datetime import UTC, datetime

from google.adk.models import Gemini

from acme_agent.agent.live import build_live_agent, build_run_config
from acme_agent.agent.tools import build_tools
from acme_agent.bootstrap import build_container
from acme_agent.config import Settings
from acme_agent.interview.controller import InterviewController
from acme_agent.interview.prompts import SYSTEM_INSTRUCTION


def _controller(container_factory) -> InterviewController:  # type: ignore[no-untyped-def]
    return InterviewController(
        container_factory("es"),
        lambda: datetime(2026, 10, 18, tzinfo=UTC),
        lambda: "t_1",
        lambda e: None,
    )


def test_run_config_fields() -> None:
    cfg = build_run_config(Settings(google_cloud_project="p", voice="Puck"))
    assert cfg.streaming_mode.name == "BIDI"
    assert [str(m.value) for m in cfg.response_modalities or []] == ["AUDIO"]
    assert cfg.input_audio_transcription is not None
    assert cfg.output_audio_transcription is not None
    assert cfg.session_resumption is not None
    assert cfg.speech_config is not None
    assert cfg.speech_config.voice_config is not None
    assert cfg.speech_config.voice_config.prebuilt_voice_config is not None
    assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
    assert cfg.realtime_input_config is not None
    aad = cfg.realtime_input_config.automatic_activity_detection
    assert aad is not None and aad.end_of_speech_sensitivity is not None
    assert aad.silence_duration_ms == 300
    assert aad.end_of_speech_sensitivity.name == "END_SENSITIVITY_HIGH"


def test_run_config_vad_is_configurable() -> None:
    cfg = build_run_config(
        Settings(google_cloud_project="p", vad_silence_ms=700, vad_end_sensitivity="low")
    )
    assert cfg.realtime_input_config is not None
    aad = cfg.realtime_input_config.automatic_activity_detection
    assert aad is not None and aad.end_of_speech_sensitivity is not None
    assert aad.silence_duration_ms == 700
    assert aad.end_of_speech_sensitivity.name == "END_SENSITIVITY_LOW"


def test_run_config_transcription_languages_and_phrases() -> None:
    cfg = build_run_config(Settings(google_cloud_project="p"), phrases=["Acme Burgers", "Chamberí"])
    assert cfg.input_audio_transcription is not None
    assert cfg.output_audio_transcription is not None
    assert cfg.input_audio_transcription.language_codes == ["es-ES", "en-US"]
    assert cfg.output_audio_transcription.language_codes == ["es-ES", "en-US"]
    assert cfg.input_audio_transcription.custom_vocabulary == ["Acme Burgers", "Chamberí"]


def test_transcription_languages_env_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ACME_TRANSCRIPTION_LANGUAGES", "es-ES")
    settings = Settings(google_cloud_project="p")
    assert settings.transcription_languages == ["es-ES"]
    cfg = build_run_config(settings)
    assert cfg.input_audio_transcription is not None
    assert cfg.input_audio_transcription.language_codes == ["es-ES"]
    assert cfg.input_audio_transcription.custom_vocabulary is None


def test_container_vocabulary_from_stores(settings: Settings) -> None:
    vocab = build_container(settings).vocabulary
    assert vocab[0] == "Acme Burgers"
    assert "Madrid" in vocab and "Chamberí" in vocab and "Acme Burgers Sol" in vocab
    assert len(vocab) == len(set(vocab))


def test_live_agent_shares_instruction_and_tools(settings: Settings) -> None:
    container = build_container(settings)
    controller = _controller(container.parse_context_factory)
    agent = build_live_agent(controller, container)
    assert agent.instruction == SYSTEM_INSTRUCTION
    names = [t.__name__ for t in agent.tools]  # type: ignore[union-attr]
    expected = [t.__name__ for t in build_tools(controller, container.retriever)]
    assert names == expected
    assert len(names) == 5


def test_live_agent_model_comes_from_settings(settings: Settings) -> None:
    container = build_container(settings.model_copy(update={"live_model": "live-x"}))
    agent = build_live_agent(_controller(container.parse_context_factory), container)
    assert isinstance(agent.model, Gemini)
    assert agent.model.model == "live-x"


def test_two_agents_have_independent_tools(settings: Settings) -> None:
    container = build_container(settings)
    c1, c2 = (_controller(container.parse_context_factory) for _ in range(2))
    a1, a2 = build_live_agent(c1, container), build_live_agent(c2, container)
    assert a1.tools[0] is not a2.tools[0]
