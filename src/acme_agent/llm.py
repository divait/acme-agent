"""Vertex AI client factory."""

from __future__ import annotations

from google import genai

from acme_agent.config import Settings


def make_genai_client(settings: Settings) -> genai.Client:
    """Build a google-genai client in Vertex mode using Application Default Credentials."""
    return genai.Client(
        vertexai=True,
        project=settings.google_cloud_project or None,
        location=settings.google_cloud_location,
    )
