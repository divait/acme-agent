"""ADK model construction bound to the Vertex client built from Settings."""

from __future__ import annotations

from google.adk.models import Gemini
from google.adk.models.base_llm import BaseLlm

from acme_agent.config import Settings
from acme_agent.llm import make_genai_client


def build_adk_model(settings: Settings, model_name: str) -> BaseLlm:
    """Gemini model whose text and live clients are the Vertex client from Settings.

    ADK's `Gemini.client` field is used by both `api_client` and `_live_api_client`,
    so nothing is read from the process environment and no API key is involved.
    """
    return Gemini(model=model_name, client=make_genai_client(settings))
