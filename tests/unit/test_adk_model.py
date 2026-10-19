"""build_adk_model binds ADK's Gemini to the Vertex client from Settings (offline)."""

from __future__ import annotations

from google.adk.models.base_llm import BaseLlm

from acme_agent.agent.models import build_adk_model
from acme_agent.config import Settings


def test_clients_are_vertex_from_settings() -> None:
    settings = Settings(google_cloud_project="p", google_cloud_location="us-central1")
    model = build_adk_model(settings, "gemini-2.5-flash")
    assert isinstance(model, BaseLlm)
    assert model.model == "gemini-2.5-flash"
    for client in (model.api_client, model._live_api_client):  # type: ignore[attr-defined]
        assert client.vertexai is True
        assert client._api_client.project == "p"
        assert client._api_client.location == "us-central1"
        assert not client._api_client.api_key
