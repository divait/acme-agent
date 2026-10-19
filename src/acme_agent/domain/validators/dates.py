"""Start date parser."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

import dateparser
from dateparser.search import search_dates

from acme_agent.domain.spoken import (
    normalise,
    numbers_to_digits,
    tokenize,
)
from acme_agent.domain.validators.base import (
    DAY_WORDS,
    DAYS,
    Issue,
    ParseContext,
    ParseResult,
    has_negation,
    words,
)

# --- start date -------------------------------------------------------------------------

_MAX_START_DAYS = 90
_IMMEDIATE_WORDS = frozenset(
    {"ya", "ahora", "inmediatamente", "inmediato", "asap", "now", "immediately", "hoy", "today"}
)
_IMMEDIATE_PHRASES = (
    "cuanto antes",
    "lo antes posible",
    "right away",
    "straight away",
    "as soon as possible",
    "desde ya",
    "ahora mismo",
    "right now",
)
_PAST_WORDS = frozenset(
    {"ayer", "anteayer", "yesterday", "ago", "hace", "pasado", "pasada", "anoche", "last"}
)
_PAST_EXCEPTIONS = ("pasado manana",)
_DATE_HINT = (
    "Ask for a concrete start date, such as 'next Monday' or 'November 5', "
    "within the next three months."
)
_FILLER_PREFIX = re.compile(
    r"^(?:(?:para|desde|a partir de|hasta|on|from|by|starting|the|este|this|el|la|del)\s+)+"
)
_RELATIVE_PREFIX = re.compile(r"\b(?:dentro de|within|en)\b")
_NEXT_PERIOD: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(?:la semana que viene|la proxima semana|next week)\b"),
        "in 1 week",
    ),
    (re.compile(r"\b(?:el mes que viene|el proximo mes|next month)\b"), "in 1 month"),
)
_MIN_HIT_WORDS = 3
_MIN_COVERAGE = 0.6
_START_CUE = re.compile(
    r"\b(?:empezar|empiezo|empezaria|comenzar|comienzo|start|starting|begin|a partir|from|"
    r"el dia|on)\s*(?:\w+\s+){0,2}$"
)
_MONTH_NAMES = frozenset(
    {
        *("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto"),
        *("septiembre", "setiembre", "octubre", "noviembre", "diciembre"),
        *("january", "february", "march", "april", "june", "july", "august"),
        *("september", "october", "november", "december"),
    }
)
_BOUND_KEYS = (
    ("antes", "de"),
    ("antes", "del"),
    ("before",),
    ("despues", "de"),
    ("despues", "del"),
    ("after",),
)
_FILLERS = frozenset(
    {
        *("puedo", "podria", "empezar", "empiezo", "comenzar", "comienzo", "start", "begin"),
        *("i", "can", "could", "would", "like", "to", "quiero", "quisiera", "me", "mi"),
        *("pues", "bueno", "vale", "claro", "eh", "um", "uh", "well", "please", "por", "favor"),
        *("mismo", "yes", "yeah", "ok", "okay", "si", "the", "it", "its", "is", "s", "m", "ll"),
        *("d", "y", "and", "oh"),
    }
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_SETTINGS_KEY = "RELATIVE_BASE"


def _dateparser_settings(today: date) -> dict[str, Any]:
    return {
        "PREFER_DATES_FROM": "future",
        "DATE_ORDER": "DMY",
        _DATE_SETTINGS_KEY: datetime.combine(today, time()),
    }


def _weekday_date(tokens: list[str], today: date) -> date | None:
    """Next occurrence (strictly after today) of a weekday named without a calendar date."""
    named = [DAY_WORDS[t] for t in tokens if t in DAY_WORDS]
    if len(named) != 1 or any(t.isdigit() for t in tokens):
        return None
    delta = (DAYS.index(named[0]) - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def _trustworthy_hit(candidate: str, matched: str) -> bool:
    """A `search_dates` hit is only believed when it is a real date expression covering most of
    the utterance, or is anchored by a cue such as "empezar" / "a partir de" / "from"."""
    if not (any(ch.isdigit() for ch in matched) or len(matched.split()) >= _MIN_HIT_WORDS):
        return False
    text = candidate.strip()
    if len(matched) >= _MIN_COVERAGE * len(text):
        return True
    index = text.find(matched)
    return index > 0 and _START_CUE.search(text[:index]) is not None


def _parse_calendar(variants: list[str], today: date) -> date | None:
    settings = _dateparser_settings(today)
    candidates: list[str] = []
    for text in variants:
        for pattern, replacement in _NEXT_PERIOD:
            text = pattern.sub(replacement, text)
        if re.search(r"\bin\b|\d", text):
            text = _RELATIVE_PREFIX.sub("in", text)
        candidates.extend((text, _FILLER_PREFIX.sub("", text.strip())))
    for candidate in candidates:
        parsed = dateparser.parse(candidate, languages=["es", "en"], settings=settings)
        if parsed is not None:
            day: date = parsed.date()
            return day
    for candidate in candidates[:2]:
        for matched, found in (
            search_dates(candidate, languages=["es", "en"], settings=settings) or []
        ):
            if _trustworthy_hit(candidate, matched):
                return found.date()  # type: ignore[no-any-return]
    return None


def _is_immediate(tokens: list[str], padded: str) -> tuple[bool, bool]:
    """(mentions an immediate word, is essentially only that phrase plus fillers)."""
    mentioned = bool(_IMMEDIATE_WORDS.intersection(tokens)) or any(
        f" {phrase} " in padded for phrase in _IMMEDIATE_PHRASES
    )
    rest = padded
    for phrase in _IMMEDIATE_PHRASES:
        rest = rest.replace(f" {phrase} ", " ")
    leftover = [t for t in rest.split() if t not in _IMMEDIATE_WORDS and t not in _FILLERS]
    return mentioned, not leftover


def _has_bound(tokens: list[str]) -> bool:
    return any(tuple(tokens[i : i + len(k)]) == k for k in _BOUND_KEYS for i in range(len(tokens)))


def _month_without_day(tokens: list[str]) -> bool:
    return any(t in _MONTH_NAMES for t in tokens) and not any(t.isdigit() for t in tokens)


def _check_range(result: date, ctx: ParseContext) -> ParseResult[date]:
    if result < ctx.today:
        return Issue(
            "past_date",
            "That date is already in the past. Ask for a start date from today onwards.",
        )
    if result > ctx.today + timedelta(days=_MAX_START_DAYS):
        return Issue(
            "too_far",
            "We can only plan start dates within the next three months. Ask for an earlier date.",
        )
    return result


def parse_start_date(raw: str, ctx: ParseContext) -> ParseResult[date]:
    """Natural-language date in Spanish or English, resolved against `ctx.today`."""
    normalised = normalise(raw)[:200]
    tokens = tokenize(normalised)
    padded = f" {' '.join(tokens)} "
    issue = Issue("unrecognized", _DATE_HINT)
    result: date | None = None
    if not tokens or (len(tokens) == 1 and tokens[0].isdigit()):
        return issue
    if _ISO_DATE.match(normalised):  # DMY ordering would misread ISO dates
        try:
            result = date.fromisoformat(normalised)
        except ValueError:
            return issue
        return _check_range(result, ctx)
    mentioned, clean = _is_immediate(tokens, padded)
    negated = has_negation(words(normalised))
    if negated:
        return issue
    spoken_tokens = numbers_to_digits(tokens)
    if mentioned and clean:
        result = ctx.today
    elif "pasado manana" in padded or "day after tomorrow" in padded:
        result = ctx.today + timedelta(days=2)
    elif _PAST_WORDS.intersection(tokens) and not any(p in padded for p in _PAST_EXCEPTIONS):
        return Issue(
            "past_date",
            "That date is already in the past. Ask for a start date from today onwards.",
        )
    elif _has_bound(tokens):
        return Issue(
            "not_a_start_date",
            "That is a deadline or a lower bound, not a start date. "
            "Ask on which exact day they can start.",
        )
    elif _month_without_day(spoken_tokens):
        return Issue(
            "month_only",
            "They only gave a month. Ask for the concrete day they can start, "
            "such as 'November 5'.",
        )
    else:
        result = _weekday_date(tokens, ctx.today)
        if result is None:
            try:
                spoken = " ".join(spoken_tokens)
                variants = [spoken, normalised] if re.search("[a-z]", normalised) else [normalised]
                result = _parse_calendar(variants, ctx.today)
            except (ValueError, OverflowError, TypeError, KeyError, IndexError):
                result = None
    if result is None:
        return issue
    return _check_range(result, ctx)
