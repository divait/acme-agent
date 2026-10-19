"""FAQ loader. Cross-language id parity is covered by test_knowledge_content (ADR-012.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from acme_agent.knowledge.faq import load_faq

KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"


def test_load_real_files() -> None:
    chunks = load_faq([KNOWLEDGE / "faq_es.md", KNOWLEDGE / "faq_en.md"])
    es = [c for c in chunks if c.language == "es"]
    en = [c for c in chunks if c.language == "en"]
    assert len(es) == len(en) == 26
    rider = next(c for c in es if c.id == "pay-rider")
    assert rider.source == "faq_es.md#pay-rider"
    assert rider.title.startswith("¿Cuánto cobra un repartidor")
    assert "10,50 a 12,50 EUR" in rider.text
    assert "<!--" not in rider.text


def test_splits_and_parses_ids(tmp_path: Path) -> None:
    f = tmp_path / "faq_en.md"
    f.write_text(
        "# Title\n\n## Q one?\n<!-- id: one -->\nAnswer one.\nMore.\n\n"
        "## Q two?\n<!-- id: two-b -->\nAnswer two.\n",
        encoding="utf-8",
    )
    chunks = load_faq([f])
    assert [(c.id, c.language, c.title, c.text) for c in chunks] == [
        ("one", "en", "Q one?", "Answer one.\nMore."),
        ("two-b", "en", "Q two?", "Answer two."),
    ]


def test_missing_id_raises(tmp_path: Path) -> None:
    f = tmp_path / "faq_es.md"
    f.write_text("## Pregunta\nSin id.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="id"):
        load_faq([f])


def test_bad_filename_raises(tmp_path: Path) -> None:
    f = tmp_path / "other.md"
    f.write_text("## Q\n<!-- id: a -->\nx\n", encoding="utf-8")
    with pytest.raises(ValueError, match="faq_<lang>"):
        load_faq([f])
