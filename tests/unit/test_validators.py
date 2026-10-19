"""Slot parsers: each has Spanish and English passing cases and failing cases (ADR-005.3)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from acme_agent.domain.models import Role, SlotName
from acme_agent.domain.validators import (
    PARSERS,
    Issue,
    ParseContext,
    parse_bool,
    parse_email,
    parse_name,
    parse_phone,
    parse_role,
    parse_store,
)

MakeCtx = Callable[..., ParseContext]


def test_issue_is_frozen() -> None:
    issue = Issue("x", "y")
    with pytest.raises(AttributeError):
        issue.code = "z"  # type: ignore[misc]


def test_registry_maps_slots_to_parsers() -> None:
    assert PARSERS[SlotName.ROLE] is parse_role
    assert PARSERS[SlotName.PHONE] is parse_phone
    assert PARSERS[SlotName.PREFERRED_STORE_ID] is parse_store
    for slot in (SlotName.CONSENT_RECORDING, SlotName.RIGHT_TO_WORK, SlotName.IS_18_OR_OVER):
        assert PARSERS[slot] is parse_bool


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sí", True), ("Si", True), ("claro", True), ("vale", True), ("por supuesto", True),
        ("correcto", True), ("sí, claro que sí", True),
        ("yes", True), ("Yeah", True), ("sure", True), ("of course", True), ("Yes, please!", True),
        ("no", False), ("para nada", False), ("claro que no", False), ("no, gracias", False),
        ("nope", False), ("not really", False), ("of course not", False), ("No.", False),
        ("no, no tengo", False), ("sí, sí", True),
    ],
)  # fmt: skip
def test_parse_bool_passes(make_ctx: MakeCtx, raw: str, expected: bool) -> None:
    assert parse_bool(raw, make_ctx()) is expected


@pytest.mark.parametrize("raw", ["", "???", "quizás", "maybe", "no sé", "I don't know", "banana"])
def test_parse_bool_fails(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_bool(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "unrecognized"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("cajero", Role.CREW_MEMBER), ("mostrador", Role.CREW_MEMBER),
        ("el drive", Role.CREW_MEMBER), ("Cocina", Role.KITCHEN),
        ("de cocinero", Role.KITCHEN), ("repartidora", Role.DELIVERY_RIDER),
        ("moto", Role.DELIVERY_RIDER), ("counter", Role.CREW_MEMBER),
        ("cashier", Role.CREW_MEMBER), ("I want to be a cook", Role.KITCHEN),
        ("kitchen", Role.KITCHEN), ("rider", Role.DELIVERY_RIDER),
        ("delivery", Role.DELIVERY_RIDER),
    ],
)  # fmt: skip
def test_parse_role_passes(make_ctx: MakeCtx, raw: str, expected: Role) -> None:
    assert parse_role(raw, make_ctx()) is expected


@pytest.mark.parametrize("raw", ["", "???", "astronauta", "cook or rider", "cajero o cocina"])
def test_parse_role_fails_with_options(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_role(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "unrecognized"
    assert "kitchen" in result.hint
    assert "delivery rider" in result.hint
    assert "crew member" in result.hint


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("me llamo maría josé", "María José"),
        ("Soy Juan Pérez", "Juan Pérez"),
        ("mi nombre es ana-belén", "Ana-Belén"),
        ("my name is john o'brien", "John O'Brien"),
        ("I'm Sarah Connor.", "Sarah Connor"),
        ("hola, me llamo luis", "Luis"),
        ("Müller", "Müller"),
        ("Jo", "Jo"),
    ],
)
def test_parse_name_passes(make_ctx: MakeCtx, raw: str, expected: str) -> None:
    assert parse_name(raw, make_ctx()) == expected


@pytest.mark.parametrize("raw", ["", "???", "a", "me llamo", "juan 3", "x" * 101, "😀😀"])
def test_parse_name_fails(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_name(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "invalid_name"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("juan punto perez arroba gmail punto com", "juan.perez@gmail.com"),
        ("maria guion lopez arroba hotmail punto es", "maria-lopez@hotmail.es"),
        ("ana guion bajo ruiz arroba correo punto com", "ana_ruiz@correo.com"),
        ("john dot smith at gmail dot com", "john.smith@gmail.com"),
        ("sarah at example dot co dot uk", "sarah@example.co.uk"),
        ("Pedro@Mail.com", "pedro@mail.com"),
        ("at@example.com", "at@example.com"),
        ("mary at outlook dot com", "mary@outlook.com"),
        ("tom dash lee at mail dot org", "tom-lee@mail.org"),
        ("bob underscore jones at gmail dot com", "bob_jones@gmail.com"),
    ],
)
def test_parse_email_passes(make_ctx: MakeCtx, raw: str, expected: str) -> None:
    assert parse_email(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    "raw", ["", "???", "juan", "juan arroba gmail", "juan@", "@gmail.com", "a@b", "a..b@c.com"]
)
def test_parse_email_fails(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_email(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "invalid_email"


@pytest.mark.parametrize(
    ("raw", "country", "expected"),
    [
        ("seis cero cero, uno dos tres, cuatro cinco seis", "ES", "+34600123456"),
        ("600 123 456", "ES", "+34600123456"),
        ("seis doble cero uno dos tres cuatro cinco seis", "ES", "+34600123456"),
        ("six zero zero, one two three, four five six", "ES", "+34600123456"),
        ("+34 600-123-456", "ES", "+34600123456"),
        ("55 1234 5678", "MX", "+525512345678"),
        ("cinco cinco, uno dos tres cuatro, cinco seis siete ocho", "MX", "+525512345678"),
        ("five five one two three four five six seven eight", "MX", "+525512345678"),
    ],
)
def test_parse_phone_passes(make_ctx: MakeCtx, raw: str, country: str, expected: str) -> None:
    assert parse_phone(raw, make_ctx(country=country)) == expected


@pytest.mark.parametrize(
    ("raw", "country", "code"),
    [
        ("", "ES", "too_short"),
        ("???", "MX", "too_short"),
        ("seis cero cero", "ES", "too_short"),
        ("123", "MX", "too_short"),
        ("6001234567890", "ES", "too_long"),
        ("55123456789012", "MX", "too_long"),
        ("111 111 111", "ES", "invalid_number"),
        ("one one one one one one one one one one", "MX", "invalid_number"),
    ],
)
def test_parse_phone_fails(make_ctx: MakeCtx, raw: str, country: str, code: str) -> None:
    result = parse_phone(raw, make_ctx(country=country))
    assert isinstance(result, Issue)
    assert result.code == code
    assert "digit" in result.hint


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ruzafa", "vlc-ruzafa"),
        ("Ruzafa", "vlc-ruzafa"),
        ("el de Chamberí", "mad-chamberi"),
        ("gracia", "bcn-gracia"),
        ("Polanco", "cdmx-polanco"),
        ("la de roma norte", "cdmx-roma"),
        ("andares", "gdl-andares"),
        ("the Condesa one", "cdmx-condesa"),
        ("Eixample", "bcn-eixample"),
        ("the one in Ruzafa please", "vlc-ruzafa"),
        ("Chamberí store", "mad-chamberi"),
        ("near Condesa", "cdmx-condesa"),
        ("el de Ruzafa", "vlc-ruzafa"),
        ("la tienda de Chamberí", "mad-chamberi"),
        ("la de Gracia", "bcn-gracia"),
        ("Ruzafa, en Valencia", "vlc-ruzafa"),
        ("Me viene bien el de Ruzafa, en Valencia", "vlc-ruzafa"),
        ("the Ruzafa one in Valencia", "vlc-ruzafa"),
        ("Valencia Ruzafa", "vlc-ruzafa"),
        ("Condesa, Ciudad de México", "cdmx-condesa"),
        ("Chamberí, Madrid", "mad-chamberi"),
        ("la de Chamberí en Madrid", "mad-chamberi"),
        ("Gràcia, Barcelona", "bcn-gracia"),
    ],
)
def test_parse_store_passes(make_ctx: MakeCtx, raw: str, expected: str) -> None:
    assert parse_store(raw, make_ctx()) == expected


def test_parse_store_madrid_is_ambiguous(make_ctx: MakeCtx) -> None:
    result = parse_store("Madrid", make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "ambiguous"
    assert "Sol" in result.hint
    assert "Chamberí" in result.hint


@pytest.mark.parametrize(
    ("raw", "present", "absent"),
    [
        ("Valencia", ("Ruzafa", "Centro"), ("Madrid", "México", "Barcelona")),
        ("Madrid", ("Sol", "Chamberí"), ("Valencia", "México", "Barcelona")),
    ],
)
def test_parse_store_city_only_lists_that_city(
    make_ctx: MakeCtx, raw: str, present: tuple[str, ...], absent: tuple[str, ...]
) -> None:
    result = parse_store(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "ambiguous"
    assert all(word in result.hint for word in present)
    assert not any(word in result.hint for word in absent)


@pytest.mark.parametrize("raw", ["Ruzafa, en Madrid", "Barcelona centro"])
def test_parse_store_city_contradicting_area_never_guesses(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_store(raw, make_ctx())
    assert isinstance(result, Issue)


def test_parse_store_ambiguous_lists_at_most_three(make_ctx: MakeCtx) -> None:
    result = parse_store("Guadalajara", make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "ambiguous"
    assert result.hint.count("Acme Burgers") == 3


@pytest.mark.parametrize("raw", ["", "???", "Sevilla", "Tokyo", "zzzz qqqq"])
def test_parse_store_not_found_lists_cities(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_store(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "not_found"
    for city in ("Madrid", "Barcelona", "Valencia", "Ciudad de México", "Guadalajara"):
        assert city in result.hint


def test_parse_store_without_stores(make_ctx: MakeCtx) -> None:
    result = parse_store("Madrid", make_ctx(stores=[]))
    assert isinstance(result, Issue)
    assert result.code == "not_found"


@pytest.mark.parametrize("raw", ["sí, no", "yes no", "no, sí", "yes and no"])
def test_parse_bool_contradictory(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_bool(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "contradictory"
    assert result.hint


@pytest.mark.parametrize(
    ("raw", "country", "expected"),
    [("55 1234 5678", "ES", "+525512345678"), ("600 123 456", "MX", "+34600123456")],
)
def test_parse_phone_falls_back_to_the_other_country(
    make_ctx: MakeCtx, raw: str, country: str, expected: str
) -> None:
    assert parse_phone(raw, make_ctx(country=country)) == expected


def test_parse_phone_reports_the_session_country_when_neither_is_valid(make_ctx: MakeCtx) -> None:
    result = parse_phone("111 111 111", make_ctx(country="MX"))
    assert isinstance(result, Issue)
    assert "Mexican" in result.hint
