"""Availability parser."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from acme_agent.domain.models import Availability, Day, Shift
from acme_agent.domain.spoken import (
    normalise,
    numbers_to_digits,
)
from acme_agent.domain.validators.base import (
    DAY_WORDS,
    DAYS,
    NEGATION_WORDS,
    Issue,
    ParseContext,
    ParseResult,
)

# --- availability -----------------------------------------------------------------------

_SHIFTS = list(Shift)
_SHIFT_WORDS: dict[str, Shift] = {
    **dict.fromkeys(("manana", "mananas", "morning", "mornings"), Shift.MORNING),
    **dict.fromkeys(("tarde", "tardes", "afternoon", "afternoons"), Shift.AFTERNOON),
    **dict.fromkeys(("noche", "noches", "night", "nights", "evening", "evenings"), Shift.NIGHT),
}
_RANGE_WORDS = frozenset({"a", "al", "hasta", "to", "through", "thru", "till", "until"})
_GROUP_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:cualquier (?:momento|hora|horario|turno)|cualquiera|cuando sea|"
            r"cuando quieran|any ?time|any shift|whenever|all the time|"
            r"full availability|disponibilidad total)\b"
        ),
        " xanytime ",
    ),
    (
        re.compile(
            r"\b(?:cualquier dia|todos los dias|cada dia|any day|every day|everyday|all days)\b"
        ),
        " xalldays ",
    ),
    (re.compile(r"\b(?:fines? de semana|finde|findes|weekends?)\b"), " xweekend "),
    (
        re.compile(r"\b(?:entre semana|dias laborables|dias laborales|weekdays?|week days?)\b"),
        " xweekdays ",
    ),
)
_MARKER_DAYS: dict[str, list[Day]] = {
    "xanytime": DAYS,
    "xalldays": DAYS,
    "xweekend": [Day.SAT, Day.SUN],
    "xweekdays": DAYS[:5],
}


@dataclass
class _Group:
    days: set[Day]
    shifts: set[Shift]
    shift_first: bool = False


def _day_run(tokens: list[str], i: int) -> tuple[list[Day], int]:
    """Days named at `tokens[i]` (a day or a marker), expanding "lunes a viernes" ranges."""
    tok = tokens[i]
    if tok in _MARKER_DAYS:
        return _MARKER_DAYS[tok], i + 1
    start = DAY_WORDS[tok]
    if i + 2 < len(tokens) and tokens[i + 1] in _RANGE_WORDS and tokens[i + 2] in DAY_WORDS:
        first, last = DAYS.index(start), DAYS.index(DAY_WORDS[tokens[i + 2]])
        span = (last - first) % 7
        return [DAYS[(first + k) % 7] for k in range(span + 1)], i + 3
    return [start], i + 1


_AFTER_KEYS = (("after",), ("despues", "de"), ("a", "partir", "de"), ("from",), ("desde",))
_BEFORE_KEYS = (("before",), ("antes", "de"))
_STRICT_KEYS = frozenset({("after",), ("despues", "de"), ("a", "partir", "de"), ("before",),
                          ("antes", "de")})  # fmt: skip
_ARTICLES = frozenset({"las", "la", "the", "at", "like"})
_PM_PERIOD = frozenset({"tarde", "noche"})
_HOUR_SUFFIX = frozenset({"horas", "hrs", "hr", "h"})
_SHIFT_START = {Shift.MORNING: 0.0, Shift.AFTERNOON: 12.0, Shift.NIGHT: 18.0}
_SHIFT_END = {Shift.MORNING: 12.0, Shift.AFTERNOON: 18.0, Shift.NIGHT: 24.0}
_MIN_BEFORE_OVERLAP = 2.0
_MAX_MINUTE = 59
_MAX_HOUR = 24
_EXCLUDERS = frozenset({"except", "excepto", "menos", "salvo"}) | NEGATION_WORDS
_MORNING_ARTICLES = frozenset({"la", "las", "tu", "mis", "mi", "de", "en"})
_NEGATION_HINT = (
    "The answer only said what they cannot do. Ask which days and shifts they CAN work "
    "(mornings, afternoons, nights)."
)
_TOMORROW_HINT = (
    "'Mañana' could mean tomorrow or the morning shift. Ask which days and which shifts "
    "(mornings, afternoons, nights) they can work."
)
_AVAILABILITY_HINT = (
    "Ask which days of the week and which shifts (mornings, afternoons, nights) they can work."
)


def _resolve_hour(hour: int, minute: int, marker: str | None) -> float | None:
    """Clock time as fractional 24h hours; None when am/pm cannot be told."""
    if hour > _MAX_HOUR or (hour == _MAX_HOUR and minute):
        return None
    if marker == "pm" and hour < 12:
        hour += 12
    elif marker == "am" and hour == 12:
        hour = 0
    elif marker is None:
        if 1 <= hour <= 6:
            hour += 12
        elif 7 <= hour <= 11:
            return None
    return hour + minute / 60


def _match_key(
    tokens: list[str], i: int, keys: Sequence[tuple[str, ...]]
) -> tuple[str, ...] | None:
    for key in keys:
        if tuple(tokens[i : i + len(key)]) == key:
            return key
    return None


def _time_qualifiers(tokens: list[str]) -> tuple[list[str], set[Shift] | None] | None:
    """Strip "after 5pm"-style qualifiers; returns (tokens, allowed shifts) or None if unclear."""
    rest: list[str] = []
    allowed: set[Shift] | None = None
    i = 0
    while i < len(tokens):
        key = _match_key(tokens, i, _AFTER_KEYS + _BEFORE_KEYS)
        if key is None:
            rest.append(tokens[i])
            i += 1
            continue
        j = i + len(key)
        if j < len(tokens) and tokens[j] in _ARTICLES:
            j += 1
        if j >= len(tokens) or not tokens[j].isdigit():
            if key in _STRICT_KEYS:
                return None
            rest.append(tokens[i])
            i += 1
            continue
        hour, minute = int(tokens[j]), 0
        j += 1
        if j < len(tokens) and tokens[j].isdigit() and len(tokens[j]) == 2:
            minute = int(tokens[j])
            j += 1
            if minute > _MAX_MINUTE:
                return None
        marker: str | None = None
        if j < len(tokens) and tokens[j] in ("am", "pm"):
            marker = tokens[j]
            j += 1
        elif tokens[j : j + 2] in (["a", "m"], ["p", "m"]):
            marker = tokens[j] + "m"
            j += 2
        elif tokens[j : j + 3] == ["de", "la", "manana"]:
            marker, j = "am", j + 3
        elif tokens[j : j + 3] in (["de", "la", "tarde"], ["de", "la", "noche"]):
            marker, j = "pm", j + 3
        if j < len(tokens) and tokens[j] in _HOUR_SUFFIX:
            j += 1
        if j < len(tokens) and tokens[j] in _RANGE_WORDS:
            return None
        when = _resolve_hour(hour, minute, marker)
        if when is None:
            return None
        if key in _BEFORE_KEYS:
            ok = {s for s in _SHIFTS if when - _SHIFT_START[s] >= _MIN_BEFORE_OVERLAP}
        else:
            ok = {s for s in _SHIFTS if _SHIFT_END[s] > when}
        allowed = ok if allowed is None else allowed & ok
        i = j
    return rest, allowed


def _collect(tokens: list[str], allowed: set[Shift] | None) -> set[tuple[Day, Shift]]:
    """(day, shift) pairs named by `tokens`, grouping "lunes y martes por la tarde"-style runs."""
    groups: list[_Group] = []
    cur = _Group(set(), set())
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in DAY_WORDS or tok in _MARKER_DAYS:
            days, i = _day_run(tokens, i)
            if cur.days and cur.shifts:
                groups.append(cur)
                cur = _Group(set(), set())
            cur.days.update(days)
            if tok == "xanytime":
                cur.shifts.update(_SHIFTS)
        elif tok in _SHIFT_WORDS:
            if cur.shift_first and cur.days and cur.shifts:
                groups.append(cur)
                cur = _Group(set(), set())
            if not cur.days and not cur.shifts:
                cur.shift_first = True
            cur.shifts.add(_SHIFT_WORDS[tok])
            i += 1
        else:
            i += 1
    if cur.days or cur.shifts or (allowed is not None and not groups):
        groups.append(cur)
    chosen: set[tuple[Day, Shift]] = set()
    for group in groups:
        for day in group.days or set(DAYS):
            chosen.update((day, shift) for shift in group.shifts or set(_SHIFTS))
    return chosen


def _tomorrow_ambiguous(tokens: list[str]) -> bool:
    """ "mañana por la tarde" may mean tomorrow: a bare "manana" next to another shift word."""
    if not any(_SHIFT_WORDS.get(t) not in (None, Shift.MORNING) for t in tokens):
        return False
    return any(
        t == "manana" and (k == 0 or tokens[k - 1] not in _MORNING_ARTICLES)
        for k, t in enumerate(tokens)
    )


def parse_availability(raw: str, ctx: ParseContext) -> ParseResult[list[Availability]]:
    """Days and shifts in either language -> ordered, de-duplicated `Availability` list."""
    text = f" {normalise(raw)} "
    for pattern, marker in _GROUP_MARKERS:
        text = pattern.sub(marker, text)
    tokens = re.findall(r"[a-z]+|\d+", text)
    tokens = numbers_to_digits(tokens)
    qualified = _time_qualifiers(tokens)
    if qualified is None:
        return Issue(
            "unrecognized",
            "The time of day was unclear. Ask for the exact time, with am or pm, "
            "or which shifts (mornings, afternoons, nights) they can work.",
        )
    tokens, allowed = qualified
    if _tomorrow_ambiguous(tokens):
        return Issue("unrecognized", _TOMORROW_HINT)
    cut = next((k for k, t in enumerate(tokens) if t in _EXCLUDERS), None)
    if cut is None:
        chosen = _collect(tokens, allowed)
    else:
        # "every day except sunday": subtract. A bare "no puedo los lunes" says nothing positive.
        chosen = _collect(tokens[:cut], allowed)
        excluded = _collect(tokens[cut + 1 :], None)
        if not chosen or not excluded:
            return Issue("unrecognized", _NEGATION_HINT)
        chosen -= excluded
    if allowed is not None:
        chosen = {pair for pair in chosen if pair[1] in allowed}
    if not chosen:
        return Issue("unrecognized", _AVAILABILITY_HINT)
    ordered = sorted(chosen, key=lambda pair: (DAYS.index(pair[0]), _SHIFTS.index(pair[1])))
    return [Availability(day=day, shift=shift) for day, shift in ordered]
