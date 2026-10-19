"""Offline checks on the fictional knowledge content in `knowledge/`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from acme_agent.domain.models import Store

KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FAQ_FILES = ["faq_en.md", "faq_es.md"]
ID_COMMENT = re.compile(r"^<!-- id: ([a-z0-9-]+) -->$")


def _sections(name: str) -> list[tuple[str, str]]:
    text = (KNOWLEDGE / name).read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.M)[1:]
    out: list[tuple[str, str]] = []
    for part in parts:
        lines = part.splitlines()
        match = ID_COMMENT.match(lines[1].strip()) if len(lines) > 1 else None
        assert match, f"{name}: section {lines[0]!r} lacks an id comment under the heading"
        out.append((match.group(1), "\n".join(lines[2:]).strip()))
    return out


def _raw() -> list[dict[str, str]]:
    data = json.loads((KNOWLEDGE / "stores.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def test_stores_valid_and_match_fixture(stores: list[Store]) -> None:
    raw = _raw()
    assert len(raw) == 12
    ids = [s["id"] for s in raw]
    assert len(set(ids)) == 12
    assert all(KEBAB.match(i) for i in ids)
    assert sum(s["city"] == "Madrid" for s in raw) >= 2
    fields = Store.model_fields.keys()
    parsed = [Store(**{k: v for k, v in s.items() if k in fields}) for s in raw]
    assert parsed == stores
    assert all(s["address"].strip() and s["opening_hours"].strip() for s in raw)


def test_faq_ids_match_across_languages() -> None:
    en = [i for i, _ in _sections("faq_en.md")]
    es = [i for i, _ in _sections("faq_es.md")]
    assert en == es
    assert len(en) == len(set(en))
    assert all(KEBAB.match(i) for i in en)


@pytest.mark.parametrize("name", FAQ_FILES)
def test_faq_sections_short(name: str) -> None:
    sections = _sections(name)
    assert len(sections) >= 20
    for sid, body in sections:
        assert body, f"{name}:{sid} is empty"
        assert len(body.split()) <= 80, f"{name}:{sid} exceeds 80 words"


@pytest.mark.parametrize("name", [*FAQ_FILES, "README.md", "stores.json"])
def test_only_example_domains(name: str) -> None:
    text = (KNOWLEDGE / name).read_text(encoding="utf-8")
    for url in re.findall(r"https?://([^/\s)]+)", text):
        assert url.rstrip(".,").endswith(".example"), url
    for email in re.findall(r"[\w.+-]+@([\w.-]+)", text):
        assert email.rstrip(".,").endswith(".example"), email


_REAL_STREETS = (
    "Esparteros", "Fuencarral", "Verdi", "Aribau", "Cuba", "Barques",
    "Orizaba", "Michoacán", "Newton", "Guadalupe", "Marsella", "Puerta de Hierro",
)  # fmt: skip


def test_store_addresses_use_no_real_street_names() -> None:
    raw = json.loads((KNOWLEDGE / "stores.json").read_text(encoding="utf-8"))
    for s in raw:
        for street in _REAL_STREETS:
            assert street.lower() not in s["address"].lower(), s["id"]


_FORBIDDEN = (
    "date of birth", "fecha de nacimiento", "how old", "qué edad", "cannot continue",
    "no podemos continuar", "6 months", "6 meses", "minimum wage", "salario mínimo",
    "proof of concept", "prueba de concepto", "bicycle", "bicicleta",
)  # fmt: skip


@pytest.mark.parametrize("name", FAQ_FILES)
def test_faq_has_no_forbidden_phrases(name: str) -> None:
    text = (KNOWLEDGE / name).read_text(encoding="utf-8").lower()
    for phrase in _FORBIDDEN:
        assert phrase not in text, f"{name} contains {phrase!r}"


def test_pay_numbers_match_across_languages() -> None:
    def numbers(name: str) -> dict[str, list[str]]:
        return {
            sid: re.findall(r"\d+(?:\.\d+)?", body.replace(",", "."))
            for sid, body in _sections(name)
            if sid.startswith("pay-")
        }

    en, es = numbers("faq_en.md"), numbers("faq_es.md")
    assert en.keys() == es.keys() and en
    for sid in en:
        assert [float(n) for n in en[sid]] == [float(n) for n in es[sid]], sid
