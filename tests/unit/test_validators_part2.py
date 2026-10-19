"""Availability, hours, date, experience, text and language parsers (ADR-005.3) and the guard."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import date

import pytest

from acme_agent.domain.models import Availability, Day, Shift, SlotName
from acme_agent.domain.spoken import find_numbers, numbers_to_digits, words_to_int
from acme_agent.domain.validators import (
    PARSERS,
    Issue,
    ParseContext,
    parse_availability,
    parse_languages,
    parse_months,
    parse_start_date,
    parse_text,
    parse_weekly_hours,
)

MakeCtx = Callable[..., ParseContext]

_D, _S = Day, Shift
_ALL = [Availability(day=d, shift=s) for d in Day for s in Shift]


def _av(*pairs: tuple[Day, Shift]) -> list[Availability]:
    return [Availability(day=d, shift=s) for d, s in pairs]


def _week(days: list[Day], shift: Shift) -> list[Availability]:
    return [Availability(day=d, shift=shift) for d in days]


def test_every_slot_has_exactly_one_parser() -> None:
    assert set(PARSERS) == set(SlotName)
    assert all(callable(p) for p in PARSERS.values())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("fines de semana por la noche", _av((_D.SAT, _S.NIGHT), (_D.SUN, _S.NIGHT))),
        ("weekday mornings", _week(list(Day)[:5], Shift.MORNING)),
        ("lunes y miércoles por la tarde", _av((_D.MON, _S.AFTERNOON), (_D.WED, _S.AFTERNOON))),
        ("de lunes a viernes por las mañanas", _week(list(Day)[:5], Shift.MORNING)),
        ("monday to friday evenings", _week(list(Day)[:5], Shift.NIGHT)),
        (
            "weekday mornings and saturday nights",
            [*_week(list(Day)[:5], Shift.MORNING), *_av((_D.SAT, _S.NIGHT))],
        ),
        ("cualquier día", _ALL),
        ("any time", _ALL),
        ("whenever", _ALL),
        ("finde", [a for a in _ALL if a.day in (_D.SAT, _D.SUN)]),
        ("tardes", [a for a in _ALL if a.shift == _S.AFTERNOON]),
        ("sunday", [a for a in _ALL if a.day == _D.SUN]),
        ("entre semana mornings", _week(list(Day)[:5], Shift.MORNING)),
        (
            "mañanas de lunes a viernes y tardes de sábado",
            [*_week(list(Day)[:5], Shift.MORNING), *_av((_D.SAT, _S.AFTERNOON))],
        ),
        ("friday to monday nights", _week([_D.MON, _D.FRI, _D.SAT, _D.SUN], Shift.NIGHT)),
        ("lunes lunes lunes por la noche", _av((_D.MON, _S.NIGHT))),
        ("any day after 5pm", [a for a in _ALL if a.shift != _S.MORNING]),
        ("weekdays after 6pm", _week(list(Day)[:5], Shift.NIGHT)),
        ("después de las 5 de la tarde", [a for a in _ALL if a.shift != _S.MORNING]),
        ("antes de la una", [a for a in _ALL if a.shift == _S.MORNING]),
        ("a partir de las 20", [a for a in _ALL if a.shift == _S.NIGHT]),
        ("after 10am", _ALL),
        ("after 5:30 pm", [a for a in _ALL if a.shift != _S.MORNING]),
        ("after 5 p.m.", [a for a in _ALL if a.shift != _S.MORNING]),
        ("monday after 8 a.m.", [a for a in _ALL if a.day == _D.MON]),
        ("después de las 9 de la mañana el lunes", [a for a in _ALL if a.day == _D.MON]),
        ("desde las 20 horas", [a for a in _ALL if a.shift == _S.NIGHT]),
        ("from monday to friday mornings", _week(list(Day)[:5], Shift.MORNING)),
        ("desde las 8 de la noche los sábados", _av((_D.SAT, _S.NIGHT))),
        ("saturday from 18:30", _av((_D.SAT, _S.NIGHT))),
        (
            "before 5pm on weekends",
            [a for a in _ALL if a.day in (_D.SAT, _D.SUN) and a.shift != _S.NIGHT],
        ),
    ],
)
def test_availability_ok(make_ctx: MakeCtx, raw: str, expected: list[Availability]) -> None:
    assert parse_availability(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "", "no sé", "hello there", "???", "after work", "después de clase", "after 9",
        "from 3 to 8", "mornings after 5pm", "after 5:75pm", "after 30", "before the weekend",
    ],
)  # fmt: skip
def test_availability_unrecognized(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_availability(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "unrecognized"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20", 20),
        ("veinte horas", 20),
        ("treinta y cinco", 35),
        ("20 o 25", 23),
        ("twenty five hours", 25),
        ("between 20 and 30", 25),
        ("more or less 40", 40),
        ("10-20", 15),
        ("unas treinta", 30),
        ("tiempo completo", 40),
        ("jornada completa", 40),
        ("full time", 40),
        ("full-time", 40),
        ("part time", 20),
        ("part-time", 20),
        ("media jornada", 20),
        ("medio tiempo", 20),
    ],
)
def test_weekly_hours_ok(make_ctx: MakeCtx, raw: str, expected: int) -> None:
    assert parse_weekly_hours(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("5", "out_of_range"),
        ("sesenta", "out_of_range"),
        ("a lot", "unrecognized"),
        ("", "unrecognized"),
    ],
)
def test_weekly_hours_issues(make_ctx: MakeCtx, raw: str, code: str) -> None:
    result = parse_weekly_hours(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("el lunes que viene", date(2026, 10, 19)),
        ("in two weeks", date(2026, 11, 1)),
        ("dentro de dos semanas", date(2026, 11, 1)),
        ("el 5 de noviembre", date(2026, 11, 5)),
        ("I can start on November 5", date(2026, 11, 5)),
        ("next monday", date(2026, 10, 19)),
        ("friday", date(2026, 10, 23)),
        ("el domingo", date(2026, 10, 25)),
        ("mañana", date(2026, 10, 19)),
        ("pasado mañana", date(2026, 10, 20)),
        ("tomorrow", date(2026, 10, 19)),
        ("la semana que viene", date(2026, 10, 25)),
        ("ya", date(2026, 10, 18)),
        ("cuanto antes", date(2026, 10, 18)),
        ("asap", date(2026, 10, 18)),
        ("right away", date(2026, 10, 18)),
        ("immediately", date(2026, 10, 18)),
        ("2026-11-15", date(2026, 11, 15)),
    ],
)
def test_start_date_ok(make_ctx: MakeCtx, raw: str, expected: date) -> None:
    assert parse_start_date(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("ayer", "past_date"),
        ("yesterday", "past_date"),
        ("hace dos semanas", "past_date"),
        ("last friday", "past_date"),
        ("2026-10-01", "past_date"),
        ("en un año", "too_far"),
        ("2027-05-01", "too_far"),
        ("blah", "unrecognized"),
        ("12", "unrecognized"),
        ("", "unrecognized"),
    ],
)
def test_start_date_issues(make_ctx: MakeCtx, raw: str, code: str) -> None:
    result = parse_start_date(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == code


def test_start_date_boundary_is_ninety_days(make_ctx: MakeCtx) -> None:
    assert parse_start_date("2027-01-16", make_ctx()) == date(2027, 1, 16)
    result = parse_start_date("2027-01-17", make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "too_far"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("dos años y medio", 30),
        ("18 months", 18),
        ("un año", 12),
        ("seis meses", 6),
        ("nada", 0),
        ("ninguna", 0),
        ("sin experiencia", 0),
        ("none", 0),
        ("no tengo experiencia", 0),
        ("nunca he trabajado", 0),
        ("never worked", 0),
        ("I have no experience", 0),
        ("no experience", 0),
        ("año y medio", 18),
        ("a year and a half", 18),
        ("1 year and a half", 18),
        ("2 years and 3 months", 27),
        ("un año y tres meses", 15),
        ("medio año", 6),
        ("half a year", 6),
        ("3 años", 36),
    ],
)
def test_months_ok(make_ctx: MakeCtx, raw: str, expected: int) -> None:
    assert parse_months(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("700 years", "out_of_range"),
        ("hello", "unrecognized"),
        ("cinco", "unrecognized"),
        ("", "unrecognized"),
    ],
)
def test_months_issues(make_ctx: MakeCtx, raw: str, code: str) -> None:
    result = parse_months(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  cajero en un   bar ", "cajero en un bar"),
        ("I worked\nat a cafe", "I worked at a cafe"),
        ("Dos años de cocina.", "Dos años de cocina."),
        ("Trabajé en una hamburguesería", "Trabajé en una hamburguesería"),
        ("Tengo experiencia de repartidor", "Tengo experiencia de repartidor"),
        ("I was a cashier for two years", "I was a cashier for two years"),
        ("Worked in a kitchen", "Worked in a kitchen"),
    ],
)
def test_text_ok(make_ctx: MakeCtx, raw: str, expected: str) -> None:
    assert parse_text(raw, make_ctx()) == expected


@pytest.mark.parametrize("raw", ["", "  \n "])
def test_text_issues(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_text(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "unrecognized"


def test_text_accepts_exactly_300(make_ctx: MakeCtx) -> None:
    assert parse_text("x" * 300, make_ctx()) == "x" * 300


def test_text_trims_at_word_boundary(make_ctx: MakeCtx) -> None:
    result = parse_text("palabra " * 50, make_ctx())
    assert result == ("palabra " * 37).strip()


def test_text_trims_without_spaces(make_ctx: MakeCtx) -> None:
    assert parse_text("x" * 500, make_ctx()) == "x" * 300


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("español e inglés", ["es", "en"]),
        ("Spanish, English and a bit of French", ["es", "en", "fr"]),
        ("solo castellano", ["es"]),
        ("portugués, italiano y alemán", ["pt", "it", "de"]),
        ("Catalan and Arabic", ["ca", "ar"]),
        ("rumano y chino", ["ro", "zh"]),
        ("english english", ["en"]),
    ],
)
def test_languages_ok(make_ctx: MakeCtx, raw: str, expected: list[str]) -> None:
    assert parse_languages(raw, make_ctx()) == expected


@pytest.mark.parametrize("raw", ["", "none", "klingon"])
def test_languages_unrecognized(make_ctx: MakeCtx, raw: str) -> None:
    result = parse_languages(raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "unrecognized"


def test_spoken_number_scanners() -> None:
    assert find_numbers("veinte o veinticinco") == [20, 25]
    assert find_numbers("oh 12 " + "9" * 20) == [12]
    assert numbers_to_digits(["en", "dos", "semanas"]) == ["en", "2", "semanas"]
    assert words_to_int("9" * 5000) is None


_NON_LATIN_NAMES = ("Иван Петров", "Ωμέγα", "日本", "محمد", "わたし", "ԋᎆ")


def _garbage_inputs() -> list[str]:
    rng = random.Random(1234)
    noise = "".join(chr(rng.randrange(32, 0x2FFF)) for _ in range(1000))
    return [
        "",
        "???",
        noise,
        "😀🍔🚀" * 20,
        "9" * 5000,
        "\x00\n\t  ",
        "a" * 10_000,
        "-" * 500,
        *_NON_LATIN_NAMES,
    ]


@pytest.mark.parametrize("slot", list(SlotName))
def test_parsers_never_raise_on_garbage(make_ctx: MakeCtx, slot: SlotName) -> None:
    parser = PARSERS[slot]
    for raw in _garbage_inputs():
        for ctx in (make_ctx(), make_ctx(country="MX", language="en")):
            result = parser(raw, ctx)
            if slot is SlotName.EXPERIENCE_SUMMARY:
                assert isinstance(result, Issue) or (
                    isinstance(result, str)
                    and len(result) <= 300
                    and not any(ord(c) < 32 or ord(c) == 127 for c in result)
                )
            elif slot is SlotName.FULL_NAME and raw in _NON_LATIN_NAMES:
                assert isinstance(result, (Issue, str))  # valid names in other scripts
            else:
                assert isinstance(result, Issue), (slot, raw[:20], result)
