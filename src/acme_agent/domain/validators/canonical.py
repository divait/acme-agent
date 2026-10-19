"""Strict validators for canonical slots (ADR-015).

The model passes these slots in a documented canonical format; code only checks the format
and applies the business limits. No natural-language interpretation happens here (ADR-015.2).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from acme_agent.domain.models import Availability, Day, Role, Shift
from acme_agent.domain.validators.base import Issue, ParseContext, ParseResult
from acme_agent.domain.validators.experience import LANGUAGE_CODES, parse_text

_MAX_START_DAYS = 90
_MIN_HOURS, _MAX_HOURS = 10, 40
_MAX_MONTHS = 600
_INT = re.compile(r"^[0-9]{1,6}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_LANG_CODE = re.compile(r"^[a-z]{2}$")

# ISO 639-1 codes of the languages the natural-language languages parser knows.
KNOWN_LANGUAGES = frozenset(LANGUAGE_CODES)


def _bad(expected: str) -> Issue:
    return Issue("bad_format", f"Invalid value. Expected format: {expected}")


def canonical_bool(value: str, ctx: ParseContext) -> ParseResult[bool]:
    """Exactly `yes` or `no`."""
    token = value.strip().lower()
    if token in ("yes", "no"):
        return token == "yes"
    return _bad("exactly 'yes' or 'no', for example: yes")


def canonical_role(value: str, ctx: ParseContext) -> ParseResult[Role]:
    """Exactly one of the Role values."""
    token = value.strip().lower()
    for role in Role:
        if token == role.value:
            return role
    options = " | ".join(r.value for r in Role)
    return _bad(f"exactly one of {options}, for example: crew_member")


_AVAILABILITY_FORMAT = (
    "comma-separated day:shift pairs, day in mon..sun and shift in "
    "morning|afternoon|night, for example: mon:morning,sat:night"
)


def canonical_availability(value: str, ctx: ParseContext) -> ParseResult[list[Availability]]:
    """Comma list of `day:shift`, de-duplicated and ordered mon..sun then morning..night."""
    days, shifts = list(Day), list(Shift)
    found: set[tuple[int, int]] = set()
    for part in value.split(","):
        day_s, sep, shift_s = (p.strip().lower() for p in part.partition(":"))
        if not sep:
            return _bad(_AVAILABILITY_FORMAT)
        try:
            found.add((days.index(Day(day_s)), shifts.index(Shift(shift_s))))
        except ValueError:
            return _bad(_AVAILABILITY_FORMAT)
    return [Availability(day=days[d], shift=shifts[s]) for d, s in sorted(found)]


def canonical_start_date(value: str, ctx: ParseContext) -> ParseResult[date]:
    """`YYYY-MM-DD` between today and today + 90 days."""
    text = value.strip()
    expected = "YYYY-MM-DD, for example: 2026-11-03"
    if not _DATE.match(text):
        return _bad(expected)
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return _bad(expected)
    if parsed < ctx.today:
        return Issue(
            "past_date",
            f"That date is in the past (today is {ctx.today.isoformat()}). "
            "Ask for a start date from today onwards, as YYYY-MM-DD.",
        )
    if parsed > ctx.today + timedelta(days=_MAX_START_DAYS):
        return Issue(
            "too_far",
            f"That date is more than {_MAX_START_DAYS} days away. "
            "Ask for an earlier start date, as YYYY-MM-DD.",
        )
    return parsed


def _integer(value: str, expected: str) -> int | Issue:
    text = value.strip()
    if not _INT.match(text):
        return _bad(expected)
    return int(text)


def canonical_weekly_hours(value: str, ctx: ParseContext) -> ParseResult[int]:
    """Integer string 10-40."""
    hours = _integer(value, "an integer number of hours per week, 10 to 40, for example: 25")
    if isinstance(hours, Issue) or _MIN_HOURS <= hours <= _MAX_HOURS:
        return hours
    return Issue(
        "out_of_range",
        f"{hours} hours per week is outside what we offer. "
        f"Ask for a number between {_MIN_HOURS} and {_MAX_HOURS}.",
    )


def canonical_months(value: str, ctx: ParseContext) -> ParseResult[int]:
    """Integer string 0-600 (months of experience)."""
    months = _integer(value, "an integer number of months, 0 to 600, for example: 18")
    if isinstance(months, Issue) or months <= _MAX_MONTHS:
        return months
    return Issue(
        "out_of_range",
        f"{months} months of experience is not plausible. Ask them to confirm how long.",
    )


def canonical_languages(value: str, ctx: ParseContext) -> ParseResult[list[str]]:
    """Comma list of known ISO 639-1 codes, de-duplicated, order preserved."""
    expected = f"comma-separated ISO 639-1 codes ({', '.join(LANGUAGE_CODES)}), e.g. es,en"
    codes: list[str] = []
    for part in value.split(","):
        code = part.strip().lower()
        if not _LANG_CODE.match(code) or code not in KNOWN_LANGUAGES:
            return _bad(expected)
        if code not in codes:
            codes.append(code)
    return codes


def canonical_summary(value: str, ctx: ParseContext) -> ParseResult[str]:
    """Short text: control characters removed, trimmed to 300 characters, non-empty."""
    result = parse_text(value, ctx)
    if isinstance(result, Issue):
        return _bad("a short non-empty sentence written by you, at most 300 characters")
    return result
