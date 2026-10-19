"""Shared types for the slot parsers (ADR-005)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from acme_agent.domain.models import Day, Store
from acme_agent.domain.spoken import normalise


@dataclass(frozen=True)
class ParseContext:
    """Everything a parser may depend on besides the raw text."""

    today: date
    country: Literal["ES", "MX"]
    stores: Sequence[Store]
    language: Literal["es", "en"]


@dataclass(frozen=True)
class Issue:
    """A failed parse: machine `code` plus an English `hint` telling the model what to do."""

    code: str
    hint: str


type ParseResult[T] = T | Issue
# A slot parser: raw candidate text and context in, a typed value or `Issue` out. The value
# type differs per slot (bool, str, date, list...), so the result is `object` for callers.
type Parser = Callable[[str, ParseContext], object]


# Day-of-week vocabulary (accent-stripped) shared by availability and start-date parsing.
DAY_WORDS: dict[str, Day] = {}
for day_, names_ in {
    Day.MON: ("lunes", "monday", "mondays"),
    Day.TUE: ("martes", "tuesday", "tuesdays"),
    Day.WED: ("miercoles", "wednesday", "wednesdays"),
    Day.THU: ("jueves", "thursday", "thursdays"),
    Day.FRI: ("viernes", "friday", "fridays"),
    Day.SAT: ("sabado", "sabados", "saturday", "saturdays"),
    Day.SUN: ("domingo", "domingos", "sunday", "sundays"),
}.items():
    DAY_WORDS.update(dict.fromkeys(names_, day_))
DAYS = list(Day)


# Negation vocabulary (accent-stripped, apostrophes removed) shared by the parsers that must
# refuse to guess when the candidate says "not" something (principle 3).
NEGATION_WORDS = frozenset(
    {"no", "not", "nunca", "jamas", "never", "nope", "nah", "dont", "cant", "cannot", "wont"}
)
_WORD = re.compile(r"[a-z]+|\d+")


def words(raw: str) -> list[str]:
    """Normalised words and digit runs with apostrophes dropped, so "don't" -> "dont"."""
    return _WORD.findall(normalise(raw).replace("'", "").replace("\u2019", ""))


def has_negation(tokens: Sequence[str]) -> bool:
    """True when any token is a negation word."""
    return any(t in NEGATION_WORDS for t in tokens)
