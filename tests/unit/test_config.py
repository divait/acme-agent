from __future__ import annotations

from pathlib import Path

import pytest

from acme_agent.config import Settings, get_settings


def test_defaults() -> None:
    s = Settings()
    assert s.google_cloud_location == "us-central1"
    assert s.google_genai_use_vertexai is True
    assert s.live_model == "gemini-live-2.5-flash-native-audio"
    assert s.text_model == "gemini-2.5-flash"
    assert s.sentiment_model == "gemini-2.5-flash-lite"
    assert s.embedding_model == "text-embedding-005"
    assert s.voice == "Aoede"
    assert s.storage == "json"
    assert s.data_dir == Path("data/conversations")
    assert s.bucket is None
    assert s.retention_days == 30
    assert s.log_level == "INFO"
    assert "http://localhost:8000" in s.allowed_origins


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACME_LIVE_MODEL", "custom-live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    monkeypatch.setenv("ACME_ALLOWED_ORIGINS", '["https://example.com"]')
    s = Settings()
    assert s.live_model == "custom-live"
    assert s.google_cloud_project == "my-proj"
    assert s.allowed_origins == ["https://example.com"]


def test_dotenv_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("ACME_VOICE=Puck\n")
    assert Settings().voice == "Puck"


def test_no_api_key_setting() -> None:
    assert not any("key" in name for name in Settings.model_fields)


def test_get_settings_cached() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()


@pytest.mark.parametrize("raw", [",", " , ", ""])
def test_empty_transcription_languages_rejected(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("ACME_TRANSCRIPTION_LANGUAGES", raw)
    with pytest.raises(ValueError, match="must not be empty"):
        Settings()
