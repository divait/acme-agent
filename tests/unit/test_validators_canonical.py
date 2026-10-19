"""Canonical slot validators and registries (ADR-015)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pytest

from acme_agent.domain.models import Availability, Day, Role, Shift, SlotName
from acme_agent.domain.validators import (
    CANONICAL,
    CROSS_CHECKS,
    PARSERS,
    VERBATIM,
    Issue,
    ParseContext,
    parse_email,
    parse_name,
    parse_phone,
    parse_store,
)

MakeCtx = Callable[..., ParseContext]
TODAY = date(2026, 10, 18)
BOOLS = {
    SlotName.CONSENT_RECORDING,
    SlotName.RIGHT_TO_WORK,
    SlotName.IS_18_OR_OVER,
    SlotName.DRIVING_LICENCE,
    SlotName.OWN_VEHICLE,
}
NATURAL = ["next monday", "sí claro", "two years", "weekday mornings", "español", "yes please"]


def test_registries_partition_slots_as_adr_table() -> None:
    assert set(CANONICAL) | set(VERBATIM) == set(SlotName)
    assert not set(CANONICAL) & set(VERBATIM)
    assert set(VERBATIM) == {
        SlotName.FULL_NAME,
        SlotName.PHONE,
        SlotName.EMAIL,
        SlotName.PREFERRED_STORE_ID,
    }
    assert VERBATIM[SlotName.FULL_NAME] is parse_name
    assert VERBATIM[SlotName.PHONE] is parse_phone
    assert VERBATIM[SlotName.EMAIL] is parse_email
    assert VERBATIM[SlotName.PREFERRED_STORE_ID] is parse_store
    assert set(CROSS_CHECKS) == set(CANONICAL)
    assert PARSERS == {**CROSS_CHECKS, **VERBATIM}


@pytest.mark.parametrize("raw", ["yes", "YES", " No ", "no"])
def test_bool_accepts(make_ctx: MakeCtx, raw: str) -> None:
    for slot in BOOLS:
        assert CANONICAL[slot](raw, make_ctx()) is (raw.strip().lower() == "yes")


def test_role(make_ctx: MakeCtx) -> None:
    for role in Role:
        assert CANONICAL[SlotName.ROLE](f" {role.value.upper()} ", make_ctx()) is role


def test_availability_sorted_deduped(make_ctx: MakeCtx) -> None:
    got = CANONICAL[SlotName.AVAILABILITY](
        "sat:night, mon:night ,mon:morning,SAT:night", make_ctx()
    )
    assert got == [
        Availability(day=Day.MON, shift=Shift.MORNING),
        Availability(day=Day.MON, shift=Shift.NIGHT),
        Availability(day=Day.SAT, shift=Shift.NIGHT),
    ]


@pytest.mark.parametrize(
    "raw", ["mon", "mon:evening", "xxx:morning", "mon:morning,", "mon:morning;tue:night"]
)
def test_availability_rejects(make_ctx: MakeCtx, raw: str) -> None:
    result = CANONICAL[SlotName.AVAILABILITY](raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "bad_format"
    assert "mon:morning,sat:night" in result.hint


@pytest.mark.parametrize(
    ("offset", "code"),
    [(0, None), (90, None), (91, "too_far"), (-1, "past_date")],
)
def test_start_date_window(make_ctx: MakeCtx, offset: int, code: str | None) -> None:
    d = TODAY + timedelta(days=offset)
    result = CANONICAL[SlotName.START_DATE](d.isoformat(), make_ctx(today=TODAY))
    if code is None:
        assert result == d
    else:
        assert isinstance(result, Issue)
        assert result.code == code


@pytest.mark.parametrize("raw", ["2026-13-01", "2026-02-30", "18/10/2026", "2026-1-5", "20261105"])
def test_start_date_bad_format(make_ctx: MakeCtx, raw: str) -> None:
    result = CANONICAL[SlotName.START_DATE](raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "bad_format"
    assert "YYYY-MM-DD" in result.hint


@pytest.mark.parametrize(
    ("slot", "raw", "expected"),
    [
        (SlotName.WEEKLY_HOURS, "10", 10),
        (SlotName.WEEKLY_HOURS, "40", 40),
        (SlotName.WEEKLY_HOURS, " 25 ", 25),
        (SlotName.EXPERIENCE_MONTHS, "0", 0),
        (SlotName.EXPERIENCE_MONTHS, "600", 600),
    ],
)
def test_integer_boundaries_pass(
    make_ctx: MakeCtx, slot: SlotName, raw: str, expected: int
) -> None:
    assert CANONICAL[slot](raw, make_ctx()) == expected


@pytest.mark.parametrize(
    ("slot", "raw"),
    [
        (SlotName.WEEKLY_HOURS, "9"),
        (SlotName.WEEKLY_HOURS, "41"),
        (SlotName.EXPERIENCE_MONTHS, "601"),
    ],
)
def test_integer_out_of_range(make_ctx: MakeCtx, slot: SlotName, raw: str) -> None:
    result = CANONICAL[slot](raw, make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "out_of_range"


@pytest.mark.parametrize("raw", ["-5", "12.5", "ten", "20 hours", "1e3", ""])
def test_integer_bad_format(make_ctx: MakeCtx, raw: str) -> None:
    for slot in (SlotName.WEEKLY_HOURS, SlotName.EXPERIENCE_MONTHS):
        result = CANONICAL[slot](raw, make_ctx())
        assert isinstance(result, Issue)
        assert result.code == "bad_format"


def test_languages(make_ctx: MakeCtx) -> None:
    assert CANONICAL[SlotName.LANGUAGES]("es, EN,es,fr", make_ctx()) == ["es", "en", "fr"]
    for bad in ["", "spanish", "xx", "es,", "esp"]:
        result = CANONICAL[SlotName.LANGUAGES](bad, make_ctx())
        assert isinstance(result, Issue)
        assert result.code == "bad_format"


def test_summary(make_ctx: MakeCtx) -> None:
    fn = CANONICAL[SlotName.EXPERIENCE_SUMMARY]
    assert fn("  Worked\x00 at a cafe\n", make_ctx()) == "Worked at a cafe"
    long = fn("word " * 100, make_ctx())
    assert isinstance(long, str)
    assert len(long) <= 300
    assert not long.endswith(" ")
    result = fn("  \n", make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "bad_format"


@pytest.mark.parametrize("raw", NATURAL)
def test_natural_language_is_bad_format(make_ctx: MakeCtx, raw: str) -> None:
    for slot, fn in CANONICAL.items():
        if slot is SlotName.EXPERIENCE_SUMMARY:
            continue  # free text by definition
        result = fn(raw, make_ctx())
        assert isinstance(result, Issue), (slot, raw)
        assert result.code == "bad_format", (slot, raw)
        assert result.hint


def test_canonical_garbage(make_ctx: MakeCtx) -> None:
    garbage = ["", "???", "😀🍔🚀" * 20, "9" * 5000, "\x00\n\t  ", "a" * 10_000, "-" * 500]
    garbage += ["Иван Петров", "Ωμέγα", "日本", "محمد", "٢٠"]
    for slot, fn in CANONICAL.items():
        for raw in garbage:
            result = fn(raw, make_ctx())
            if slot is SlotName.EXPERIENCE_SUMMARY and isinstance(result, str):
                assert len(result) <= 300
            else:
                assert isinstance(result, Issue), (slot, raw[:10])


@pytest.mark.parametrize(
    "raw",
    [
        "pues mi correo es laura arroba gmail punto com",
        "pues laura arroba gmail punto com",
        "claro, laura arroba gmail punto com",
        "vale, mi correo es laura arroba gmail punto com",
        "bueno, es laura arroba gmail punto com",
        "ok it's laura at gmail dot com",
        "mi email: laura arroba gmail punto com",
        "mi mail: laura arroba gmail punto com",
        "sí, mira, mi correo es laura arroba gmail punto com",
        "laura arroba gmail punto com.",
    ],
)
def test_email_fillers(make_ctx: MakeCtx, raw: str) -> None:
    assert parse_email(raw, make_ctx()) == "laura@gmail.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("laura dos arroba gmail punto com", "laura2@gmail.com"),
        ("laura nueve nueve arroba gmail punto com", "laura99@gmail.com"),
        ("laura two at gmail dot com", "laura2@gmail.com"),
        ("laura punto cinco arroba gmail punto com", "laura.5@gmail.com"),
    ],
)
def test_email_spoken_digits(make_ctx: MakeCtx, raw: str, expected: str) -> None:
    assert parse_email(raw, make_ctx()) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "laura perez arroba gmail punto com",
        "laura arroba gmail punto com por favor",
        "laura arroba gmail punto com gracias",
        "pues mi correo es",
    ],
)
def test_email_never_concatenates_filler(make_ctx: MakeCtx, raw: str) -> None:
    assert isinstance(parse_email(raw, make_ctx()), Issue)


@pytest.mark.parametrize("slot", [SlotName.WEEKLY_HOURS, SlotName.EXPERIENCE_MONTHS])
def test_canonical_integers_are_ascii_only(make_ctx: MakeCtx, slot: SlotName) -> None:
    result = CANONICAL[slot]("٢٠", make_ctx())
    assert isinstance(result, Issue)
    assert result.code == "bad_format"
