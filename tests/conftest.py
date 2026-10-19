"""Shared fixtures. No test may require Google credentials or network access."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from acme_agent.config import Settings
from acme_agent.domain.models import Store
from acme_agent.domain.validators import ParseContext


@pytest.fixture(autouse=True)
def _isolated_environment(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Strip project env vars and run from an empty dir so no `.env` or ADC leaks in.

    No-op for `live` and `eval` tests, which need the developer's real configuration.
    """
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("eval"):
        return
    for key in list(os.environ):
        if key.startswith(("ACME_", "GOOGLE_")):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def live_settings(tmp_path: Path) -> Settings:
    """Real settings from the repo-root `.env`, with records going to a tmp data dir.

    Skips the test when no Google Cloud project is configured.
    """
    loaded = Settings(_env_file=REPO_ROOT / ".env")
    if not loaded.google_cloud_project:
        pytest.skip("live test needs GOOGLE_CLOUD_PROJECT (set it in the repo-root .env)")
    return loaded.model_copy(
        update={"data_dir": tmp_path / "conversations", "faq_index_path": tmp_path / "index.npz"}
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with a temp data dir and a fake project id."""
    return Settings(
        google_cloud_project="test-project",
        data_dir=tmp_path / "conversations",
        faq_index_path=tmp_path / "index.npz",
        post_call="off",  # tests never reach a model; post-call tests build the finalizer
        sentiment="off",  # likewise; sentiment tests inject a fake client
    )


_STORE_ROWS: list[tuple[str, str, str, str, str]] = [
    ("mad-sol", "Acme Burgers Sol", "Madrid", "Sol", "ES"),
    ("mad-chamberi", "Acme Burgers Chamberí", "Madrid", "Chamberí", "ES"),
    ("bcn-gracia", "Acme Burgers Gràcia", "Barcelona", "Gràcia", "ES"),
    ("bcn-eixample", "Acme Burgers Eixample", "Barcelona", "Eixample", "ES"),
    ("vlc-ruzafa", "Acme Burgers Ruzafa", "Valencia", "Ruzafa", "ES"),
    ("vlc-centro", "Acme Burgers Valencia Centro", "Valencia", "Centro", "ES"),
    ("cdmx-roma", "Acme Burgers Roma Norte", "Ciudad de México", "Roma Norte", "MX"),
    ("cdmx-condesa", "Acme Burgers Condesa", "Ciudad de México", "Condesa", "MX"),
    ("cdmx-polanco", "Acme Burgers Polanco", "Ciudad de México", "Polanco", "MX"),
    ("gdl-chapalita", "Acme Burgers Chapalita", "Guadalajara", "Chapalita", "MX"),
    ("gdl-providencia", "Acme Burgers Providencia", "Guadalajara", "Providencia", "MX"),
    ("gdl-andares", "Acme Burgers Andares", "Guadalajara", "Andares", "MX"),
]


@pytest.fixture
def stores() -> list[Store]:
    """Fictional store list mirroring the planned `knowledge/stores.json` (12 stores)."""
    return [Store(id=i, name=n, city=c, area=a, country=k) for i, n, c, a, k in _STORE_ROWS]


@pytest.fixture
def make_ctx(stores: list[Store]) -> Callable[..., ParseContext]:
    """Build a `ParseContext` with sensible defaults; override any field by keyword."""

    def _make(**overrides: Any) -> ParseContext:
        values: dict[str, Any] = {
            "today": date(2026, 10, 18),
            "country": "ES",
            "stores": stores,
            "language": "es",
        }
        values.update(overrides)
        return ParseContext(**values)

    return _make
