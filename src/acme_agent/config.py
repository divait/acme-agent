"""Application settings. The only module allowed to read the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local `.env` file.

    Authentication uses Application Default Credentials on Vertex AI; there is
    deliberately no API-key setting.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    google_cloud_project: str = Field(default="", validation_alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(
        default="us-central1", validation_alias="GOOGLE_CLOUD_LOCATION"
    )
    google_genai_use_vertexai: bool = Field(
        default=True, validation_alias="GOOGLE_GENAI_USE_VERTEXAI"
    )

    live_model: str = Field(
        default="gemini-live-2.5-flash-native-audio", validation_alias="ACME_LIVE_MODEL"
    )
    text_model: str = Field(default="gemini-2.5-flash", validation_alias="ACME_TEXT_MODEL")
    sentiment_model: str = Field(
        default="gemini-2.5-flash-lite", validation_alias="ACME_SENTIMENT_MODEL"
    )
    embedding_model: str = Field(
        default="text-embedding-005", validation_alias="ACME_EMBEDDING_MODEL"
    )
    faq_threshold: float = Field(
        default=0.55, ge=0.0, le=1.0, validation_alias="ACME_FAQ_THRESHOLD"
    )
    faq_threshold_es: float | None = Field(
        default=None, ge=0.0, le=1.0, validation_alias="ACME_FAQ_THRESHOLD_ES"
    )
    faq_threshold_en: float | None = Field(
        default=None, ge=0.0, le=1.0, validation_alias="ACME_FAQ_THRESHOLD_EN"
    )
    faq_timeout_s: float = Field(default=2.0, gt=0.0, validation_alias="ACME_FAQ_TIMEOUT_S")
    faq_index_path: Path = Field(
        default=Path("data/index.npz"), validation_alias="ACME_FAQ_INDEX_PATH"
    )
    voice: str = Field(default="Aoede", validation_alias="ACME_VOICE")
    vad_silence_ms: int = Field(default=300, ge=0, validation_alias="ACME_VAD_SILENCE_MS")
    vad_end_sensitivity: Literal["high", "low", "default"] = Field(
        default="high", validation_alias="ACME_VAD_END_SENSITIVITY"
    )
    transcription_languages: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["es-ES", "en-US"],
        validation_alias="ACME_TRANSCRIPTION_LANGUAGES",
    )

    post_call: Literal["on", "off"] = Field(default="on", validation_alias="ACME_POST_CALL")

    sentiment: Literal["on", "off"] = Field(default="on", validation_alias="ACME_SENTIMENT")

    storage: Literal["json", "gcs"] = Field(default="json", validation_alias="ACME_STORAGE")
    data_dir: Path = Field(default=Path("data/conversations"), validation_alias="ACME_DATA_DIR")
    bucket: str | None = Field(default=None, validation_alias="ACME_BUCKET")
    retention_days: int = Field(default=30, ge=0, validation_alias="ACME_RETENTION_DAYS")

    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"],
        validation_alias="ACME_ALLOWED_ORIGINS",
    )
    log_level: str = Field(default="INFO", validation_alias="ACME_LOG_LEVEL")

    @property
    def faq_thresholds(self) -> dict[str, float]:
        """Cosine threshold per FAQ language (per-language overrides fall back to the default)."""
        return {
            "es": self.faq_threshold_es
            if self.faq_threshold_es is not None
            else self.faq_threshold,
            "en": self.faq_threshold_en
            if self.faq_threshold_en is not None
            else self.faq_threshold,
        }

    @field_validator("transcription_languages", mode="before")
    @classmethod
    def _split_languages(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("transcription_languages")
    @classmethod
    def _require_languages(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("transcription_languages must not be empty")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings."""
    return Settings()
