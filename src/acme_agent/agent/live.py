"""Live (voice) agent: the same instruction and tools as text mode, on a Gemini Live model.

All live-specific ADK details live here (ADR-003). Per-session: build one agent per
controller (ADR-003.2).

Affective dialog and proactivity exist on `RunConfig` (`enable_affective_dialog`,
`proactivity`) but are left off: they are not verified against the pinned Vertex native-audio
model and an unsupported flag fails the whole live connection. Enable after a live check.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from google.adk.agents import Agent
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode  # type: ignore[attr-defined]
from google.adk.events import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from acme_agent.agent.models import build_adk_model
from acme_agent.agent.tools import build_tools
from acme_agent.bootstrap import AppContainer
from acme_agent.config import Settings
from acme_agent.interview.controller import InterviewController
from acme_agent.interview.prompts import SYSTEM_INSTRUCTION

AGENT_NAME = "ana"
LIVE_APP_NAME = "acme_agent_live"


_END_SENSITIVITY = {
    "high": types.EndSensitivity.END_SENSITIVITY_HIGH,
    "low": types.EndSensitivity.END_SENSITIVITY_LOW,
    "default": types.EndSensitivity.END_SENSITIVITY_UNSPECIFIED,
}


def build_run_config(settings: Settings, *, phrases: Sequence[str] = ()) -> RunConfig:
    """Bidirectional audio with transcription of both sides (ADR-002.3) and resumption.

    Transcription is constrained to `settings.transcription_languages` (several codes keep
    mid-call language switching) and biased towards `phrases` (proper nouns).
    """
    return RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=list(settings.transcription_languages),
            custom_vocabulary=list(phrases) or None,
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=list(settings.transcription_languages)
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.voice)
            )
        ),
        session_resumption=types.SessionResumptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                end_of_speech_sensitivity=_END_SENSITIVITY[settings.vad_end_sensitivity],
                silence_duration_ms=settings.vad_silence_ms,
            )
        ),
    )


def build_live_agent(
    controller: InterviewController,
    container: AppContainer,
    *,
    model: BaseLlm | str | None = None,
) -> Agent:
    """Ana on the live model, with tools bound to this session's controller."""
    settings = container.settings
    return Agent(
        name=AGENT_NAME,
        model=model if model is not None else build_adk_model(settings, settings.live_model),
        instruction=SYSTEM_INSTRUCTION,
        tools=build_tools(controller, container.retriever),
    )


LIVE_USER_ID = "candidate"


async def stream_live_events(
    controller: InterviewController,
    container: AppContainer,
    queue: LiveRequestQueue,
    conversation_id: str,
) -> AsyncIterator[Event]:
    """Run the ADK live loop for one session and yield its events (the only `run_live` caller)."""
    sessions = InMemorySessionService()
    await sessions.create_session(
        app_name=LIVE_APP_NAME, user_id=LIVE_USER_ID, session_id=conversation_id
    )
    runner = Runner(
        app_name=LIVE_APP_NAME,
        agent=build_live_agent(controller, container),
        session_service=sessions,
    )
    async for event in runner.run_live(
        user_id=LIVE_USER_ID,
        session_id=conversation_id,
        live_request_queue=queue,
        run_config=build_run_config(container.settings, phrases=container.vocabulary),
    ):
        yield event
