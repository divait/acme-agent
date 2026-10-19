"""Regression tests for review round 1: parsers must not return values the candidate never said."""

from __future__ import annotations

import random
import unicodedata
from collections.abc import Callable
from datetime import date

import pytest

from acme_agent.domain.models import Availability, Day, Role, Shift, SlotName, Store
from acme_agent.domain.validators import (
    PARSERS,
    Issue,
    ParseContext,
    parse_availability,
    parse_bool,
    parse_email,
    parse_languages,
    parse_months,
    parse_name,
    parse_role,
    parse_start_date,
    parse_store,
    parse_text,
    parse_weekly_hours,
)

MakeCtx = Callable[..., ParseContext]
_DAYS = list(Day)
_SHIFTS = list(Shift)


def _pairs(result: object) -> set[tuple[Day, Shift]]:
    assert isinstance(result, list)
    return {(a.day, a.shift) for a in result if isinstance(a, Availability)}


def _grid(days: list[Day], shifts: list[Shift]) -> set[tuple[Day, Shift]]:
    return {(d, s) for d in days for s in shifts}


# --- availability -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "days", "shifts"),
    [
        ("every day except sunday", _DAYS[:6], _SHIFTS),
        ("todos los días menos el domingo", _DAYS[:6], _SHIFTS),
        ("todos los días excepto el domingo", _DAYS[:6], _SHIFTS),
        ("mornings but not fridays", [*_DAYS[:4], Day.SAT, Day.SUN], [Shift.MORNING]),
        ("weekends only, not sunday", [Day.SAT], _SHIFTS),
        ("de lunes a viernes salvo los martes", [Day.MON, *_DAYS[2:5]], _SHIFTS),
    ],
)
def test_availability_subtracts_clear_exclusions(
    make_ctx: MakeCtx, raw: str, days: list[Day], shifts: list[Shift]
) -> None:
    assert _pairs(parse_availability(raw, make_ctx())) == _grid(days, shifts)


@pytest.mark.parametrize(
    "raw",
    [
        "no puedo los lunes",
        "no",
        "nunca",
        "not on fridays",
        "everyday except",
        "mornings but not",
        "mañana por la tarde",
        "mañana por la noche",
    ],
)
def test_availability_negation_and_tomorrow_are_issues(make_ctx: MakeCtx, raw: str) -> None:
    assert isinstance(parse_availability(raw, make_ctx()), Issue)


def test_availability_morning_with_article_is_still_a_shift(make_ctx: MakeCtx) -> None:
    result = parse_availability("lunes por la mañana y martes por la tarde", make_ctx())
    assert _pairs(result) == {(Day.MON, Shift.MORNING), (Day.TUE, Shift.AFTERNOON)}


def test_availability_time_qualifier_with_exclusion(make_ctx: MakeCtx) -> None:
    result = parse_availability("after 6pm but not fridays", make_ctx())
    assert _pairs(result) == _grid([*_DAYS[:4], Day.SAT, Day.SUN], [Shift.NIGHT])


# --- start date -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12/11", date(2026, 11, 12)),
        ("3/11", date(2026, 11, 3)),
        ("01/12", date(2026, 12, 1)),
        ("2026-11-20", date(2026, 11, 20)),
        ("ya", date(2026, 10, 18)),
        ("ahora mismo", date(2026, 10, 18)),
        ("lo antes posible", date(2026, 10, 18)),
        ("asap", date(2026, 10, 18)),
        ("right away", date(2026, 10, 18)),
        ("puedo empezar ya", date(2026, 10, 18)),
        ("hoy", date(2026, 10, 18)),
        ("I can start on November 5", date(2026, 11, 5)),
    ],
)
def test_start_date_dmy_and_clean_immediacy(make_ctx: MakeCtx, raw: str, expected: date) -> None:
    assert parse_start_date(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ahora estoy estudiando, hasta enero no",
        "ya veremos",
        "ya te digo que no lo sé",
        "now I'm not sure, maybe next month",
        "hoy no puedo hablar de eso",
        "en diciembre",
        "en enero",
        "in December",
        "antes del 10 de noviembre",
        "before November 10",
        "2026-13-45",
    ],
)
def test_start_date_refuses_to_guess(make_ctx: MakeCtx, raw: str) -> None:
    assert isinstance(parse_start_date(raw, make_ctx()), Issue)


def test_start_date_month_only_asks_for_a_day(make_ctx: MakeCtx) -> None:
    result = parse_start_date("en diciembre", make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "month_only"


def _noise() -> str:
    rng = random.Random(1234)
    return "".join(chr(rng.randrange(32, 0x2FFF)) for _ in range(1000))


def test_start_date_noise_is_an_issue(make_ctx: MakeCtx) -> None:
    assert isinstance(parse_start_date(_noise(), make_ctx()), Issue)


def test_start_date_long_sentence_with_cue_is_trusted(make_ctx: MakeCtx) -> None:
    raw = "bueno pues la verdad es que podría empezar el 5 de noviembre sin problema"
    assert parse_start_date(raw, make_ctx()) == date(2026, 11, 5)


def test_start_date_long_sentence_without_cue_is_not_trusted(make_ctx: MakeCtx) -> None:
    raw = "mi hermana nació el 5 de noviembre y a mi madre le gusta mucho cocinar en casa"
    assert isinstance(parse_start_date(raw, make_ctx()), Issue)


# --- months -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("two and a half years", 30),
        ("dos años y medio", 30),
        ("a year and a half", 18),
        ("a year", 12),
        ("ninguna en hostelería pero 2 años en tiendas", 24),
        ("nunca en cocina, pero 3 años de camarero", 36),
        ("tengo 2 años de experiencia", 24),
        ("nada", 0),
        ("no tengo experiencia", 0),
    ],
)
def test_months_values(make_ctx: MakeCtx, raw: str, expected: int) -> None:
    assert parse_months(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "a few years",
        "unos meses",
        "varios años",
        "some time",
        "tengo 25 años",
        "30 years",
        "menos de 2 años",
        "no tengo 2 años de experiencia",
    ],
)
def test_months_vague_or_age_is_an_issue(make_ctx: MakeCtx, raw: str) -> None:
    assert isinstance(parse_months(raw, make_ctx()), Issue)


# --- bool and role ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["vale no", "right, no", "sure no", "ok so no", "claro, pero no tengo carnet", "no, sí que sí"],
)
def test_bool_contradictions_are_issues(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_bool(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "contradictory"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("claro que no", False),
        ("no, no tengo", False),
        ("sí, sí", True),
        ("no problem", True),
        ("no hay problema", True),
        ("sin problema", True),
        ("of course not", False),
    ],
)
def test_bool_keeps_clear_answers(make_ctx: MakeCtx, raw: str, expected: bool) -> None:
    assert parse_bool(raw, make_ctx()) is expected


def test_bool_unsure_anywhere_is_an_issue(make_ctx: MakeCtx) -> None:
    assert isinstance(parse_bool("sí, no sé", make_ctx()), Issue)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("la caja", Role.CREW_MEMBER),
        ("quiero repartir", Role.DELIVERY_RIDER),
        ("repartos", Role.DELIVERY_RIDER),
        ("reparto", Role.DELIVERY_RIDER),
    ],
)
def test_role_new_synonyms(make_ctx: MakeCtx, raw: str, expected: Role) -> None:
    assert parse_role(raw, make_ctx()) == expected


@pytest.mark.parametrize("raw", ["no quiero cocina, prefiero repartir", "cocina o caja"])
def test_role_negated_or_multiple_is_an_issue(make_ctx: MakeCtx, raw: str) -> None:
    assert isinstance(parse_role(raw, make_ctx()), Issue)


# --- name, email, languages -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Me llamo Juan y vivo en Madrid", "Juan"),
        ("my name is Anna and I live in Leeds", "Anna"),
        ("sí, me llamo Juan Pérez", "Juan Pérez"),
        ("Hola Ana García", "Ana García"),
        ("mi nombre es María José, encantada", "María José"),
        ("O'Brien", "O'Brien"),
    ],
)
def test_name_cuts_clauses(make_ctx: MakeCtx, raw: str, expected: str) -> None:
    assert parse_name(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "yes",
        "sí",
        "hola",
        "okay",
        "vale",
        "soy de Madrid",
        "I'm from London",
        "no te lo quiero decir",
        "uno dos tres cuatro cinco seis",
        "Ana Maria Perez Lopez Garcia Ruiz",
    ],
)
def test_name_rejects_non_names(make_ctx: MakeCtx, raw: str) -> None:
    assert isinstance(parse_name(raw, make_ctx()), Issue)


@pytest.mark.parametrize(
    "raw",
    [
        "my email is juan at gmail dot com",
        "my e-mail is juan at gmail dot com",
        "mi correo es juan arroba gmail punto com",
        "mi email es juan arroba gmail punto com",
        "mi mail es juan arroba gmail punto com",
        "it's juan at gmail dot com",
        "es juan arroba gmail punto com",
    ],
)
def test_email_strips_leading_fillers(make_ctx: MakeCtx, raw: str) -> None:
    assert parse_email(raw, make_ctx()) == "juan@gmail.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("inglés no, solo español", ["es"]),
        ("hablo español pero no inglés", ["es"]),
        ("entiendo el francés pero hablo inglés", ["fr", "en"]),
        ("español e inglés", ["es", "en"]),
    ],
)
def test_languages_drop_negated(make_ctx: MakeCtx, raw: str, expected: list[str]) -> None:
    assert parse_languages(raw, make_ctx()) == expected


@pytest.mark.parametrize("raw", ["no hablo inglés", "entiendo el francés pero no lo hablo"])
def test_languages_fully_negated_is_an_issue(make_ctx: MakeCtx, raw: str) -> None:
    assert isinstance(parse_languages(raw, make_ctx()), Issue)


# --- store, text, weekly hours ----------------------------------------------------------


def test_store_city_and_area(make_ctx: MakeCtx) -> None:
    assert parse_store("valencia centro", make_ctx()) == "vlc-centro"
    assert parse_store("el centro", make_ctx()) == "vlc-centro"


def test_store_shared_area_name_is_ambiguous() -> None:
    stores = [
        Store(id="a", name="Acme Centro", city="Madrid", area="Centro", country="ES"),
        Store(id="b", name="Acme Centro", city="Valencia", area="Centro", country="ES"),
    ]
    ctx = ParseContext(today=date(2026, 10, 18), country="ES", stores=stores, language="es")
    result = parse_store("el centro", ctx)
    assert isinstance(result, Issue)
    assert result.code == "ambiguous"
    assert parse_store("valencia centro", ctx) == "b"


def test_text_strips_control_characters(make_ctx: MakeCtx) -> None:
    assert parse_text("hola\x00\x07 mundo\x7f", make_ctx()) == "hola mundo"
    assert isinstance(parse_text("\x00\x01\x02", make_ctx()), Issue)


@pytest.mark.parametrize(
    "raw", ["3 días a la semana", "4 horas al día", "4 hours a day", "4 hours a day 5 days a week"]
)
def test_weekly_hours_days_and_per_day_are_issues(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_weekly_hours(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "per_day"
    assert "per week" in result.hint


def test_weekly_hours_ignores_day_counts_next_to_hours(make_ctx: MakeCtx) -> None:
    assert parse_weekly_hours("20 horas, 4 días", make_ctx()) == 20


# --- garbage ----------------------------------------------------------------------------


def _garbage() -> list[str]:
    return ["", "???", _noise(), "😀🍔🚀" * 20, "9" * 5000, "\x00\n\t  ", "a" * 10_000, "-" * 500]


@pytest.mark.parametrize("slot", list(SlotName))
def test_garbage_is_always_an_issue_except_free_text(make_ctx: MakeCtx, slot: SlotName) -> None:
    parser = PARSERS[slot]
    for raw in _garbage():
        result = parser(raw, make_ctx())
        if parser is parse_text:
            if isinstance(result, str):
                assert len(result) <= 300
                assert not any(unicodedata.category(c) == "Cc" for c in result)
            continue
        assert isinstance(result, Issue), (slot, raw[:20], result)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Иван Петров", "Иван Петров"),
        ("ωμέγα", "Ωμέγα"),
        ("日本", "日本"),
        ("わたし", "わたし"),
        ("ԋᎆ", "Ԋᎆ"),
    ],
)
def test_non_latin_names_are_accepted(make_ctx: MakeCtx, raw: str, expected: str) -> None:
    assert parse_name(raw, make_ctx()) == expected
