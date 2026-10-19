"""Weekly hours, experience, free text and languages."""

from __future__ import annotations

import re
import unicodedata

from acme_agent.domain.spoken import normalise, scan_numbers, tokenize
from acme_agent.domain.validators.base import (
    NEGATION_WORDS,
    Issue,
    ParseContext,
    ParseResult,
    words,
)

# --- weekly hours -----------------------------------------------------------------------

_MIN_HOURS, _MAX_HOURS = 10, 40
_PART_TIME_HOURS = 20
_FULL_TIME = ("full time", "tiempo completo", "jornada completa")
_PART_TIME = ("part time", "media jornada", "medio tiempo", "jornada parcial", "tiempo parcial")
_HOURS_HINT = "Ask how many hours per week they can work, a number between 10 and 40."


_DAY_UNITS = frozenset({"dia", "dias", "day", "days"})
_PER_DAY = (
    "al dia", "por dia", "cada dia", "a diario", "a day", "per day", "each day", "every day",
    "diaria", "diarias", "diario", "diarios", "daily",
)  # fmt: skip
_PER_WEEK_HINT = (
    "That was days or hours per day. Ask for the total hours per week, a number between 10 and 40."
)


def parse_weekly_hours(raw: str, ctx: ParseContext) -> ParseResult[int]:
    """Hours per week from digits or words; "20 o 25" -> midpoint (rounded half up)."""
    tokens = tokenize(raw)
    padded = f" {' '.join(tokens)} "
    if any(f" {p} " in padded for p in _PER_DAY):
        return Issue("per_day", _PER_WEEK_HINT)
    scanned = scan_numbers(tokens)
    numbers = [v for v, _, end in scanned if not (end < len(tokens) and tokens[end] in _DAY_UNITS)]
    if scanned and not numbers:
        return Issue("per_day", _PER_WEEK_HINT)
    if not numbers:
        if any(f" {p} " in padded for p in _FULL_TIME):
            return _MAX_HOURS
        if any(f" {p} " in padded for p in _PART_TIME):
            return _PART_TIME_HOURS
        return Issue("unrecognized", _HOURS_HINT)
    joiners = {"o", "or", "a", "to", "y", "and", "entre", "between", "u"}
    is_range = len(numbers) == 2 and (joiners.intersection(tokens) or "-" in raw)
    hours = (numbers[0] + numbers[1] + 1) // 2 if is_range else numbers[0]
    if _MIN_HOURS <= hours <= _MAX_HOURS:
        return hours
    return Issue(
        "out_of_range",
        f"{hours} hours per week is outside what we offer. "
        f"Ask for a number between {_MIN_HOURS} and {_MAX_HOURS}.",
    )


# --- experience -------------------------------------------------------------------------

_MAX_MONTHS = 600
_YEAR_WORDS = frozenset({"ano", "anos", "year", "years", "yr", "yrs"})
_MONTH_WORDS = frozenset({"mes", "meses", "month", "months"})
_NO_EXPERIENCE = frozenset({"nada", "ninguna", "ninguno", "none", "nunca", "never", "cero", "zero"})
_MONTHS_HINT = (
    "Ask how long they have worked in similar jobs, in years or months, or whether they have none."
)


_VAGUE = frozenset(
    {*("few", "some", "several", "couple", "many", "unos", "unas", "varios", "varias")}
    | {*("algunos", "algunas", "pocos", "pocas", "muchos", "muchas", "par")}
)
_EXPERIENCE_WORDS = frozenset(
    {*("experiencia", "experience", "trabajado", "trabaje", "trabajando", "trabajo", "worked")}
    | {*("working", "work", "llevo", "llevaba", "cocinando", "cooking", "camarero")}
)
_AGE_CUES = frozenset({"tengo", "tiene", "soy", "am", "im", "aged", "edad", "old"})
_NEGATED_QUANTITY = NEGATION_WORDS - {"nunca", "never", "jamas"} | {"sin", "menos", "less", "ni"}
_PLAUSIBLE_AGE = 16
_UNIT_WORDS = _YEAR_WORDS | _MONTH_WORDS
_SINGULAR_YEAR = frozenset({"ano", "year", "yr"})
_UNCLEAR_MONTHS_HINT = (
    "That amount was vague or may not be work experience. Ask for a number of years or "
    "months of work experience, or whether they have none."
)
_NO_EXPERIENCE_PHRASES = (
    " sin experiencia ", " no experience ", " no experiencia ", " no tengo experiencia ",
    " nunca he trabajado ", " never worked ",
)  # fmt: skip


def _is_and_a_half(tokens: list[str], i: int) -> bool:
    return tokens[i : i + 2] in (["y", "medio"], ["y", "media"]) or tokens[i : i + 3] == [
        "and",
        "a",
        "half",
    ]


def _is_half_year(tokens: list[str], i: int) -> bool:
    """True for "medio año", "half a year" or "half year" starting at `tokens[i]`."""
    if tokens[i] not in ("medio", "half"):
        return False
    rest = tokens[i + 1 :]
    if rest[:1] == ["a"]:
        rest = rest[1:]
    return rest[:1] != [] and rest[0] in _YEAR_WORDS


def parse_months(raw: str, ctx: ParseContext) -> ParseResult[int]:
    """Experience as whole months: "dos años y medio" -> 30, "18 months" -> 18, "nada" -> 0."""
    tokens = tokenize(raw)
    padded = f" {' '.join(tokens)} "
    total = 0
    understood = False
    suspicious = False
    has_experience_word = bool(_EXPERIENCE_WORDS.intersection(tokens))
    numbers = {start: (value, end) for value, start, end in scan_numbers(tokens)}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        value, nxt = numbers.get(i, (None, i + 1))
        before = tokens[max(0, i - 3) : i]
        if value is not None and nxt < len(tokens) and tokens[nxt] in _UNIT_WORDS:
            is_year = tokens[nxt] in _YEAR_WORDS
            if _NEGATED_QUANTITY.intersection(before):
                suspicious = True
            if (
                is_year
                and not has_experience_word
                and (value >= _PLAUSIBLE_AGE or _AGE_CUES.intersection(before))
            ):
                suspicious = True
            total += value * 12 if is_year else value
            understood = True
            i = nxt + 1
            if is_year and _is_and_a_half(tokens, i):
                total += 6
                i += 3 if tokens[i] == "and" else 2
        elif (
            value is not None
            and _is_and_a_half(tokens, nxt)
            and nxt + (3 if tokens[nxt] == "and" else 2) < len(tokens)
            and tokens[nxt + (3 if tokens[nxt] == "and" else 2)] in _YEAR_WORDS
        ):
            total += value * 12 + 6  # "two and a half years"
            understood = True
            i = nxt + (4 if tokens[nxt] == "and" else 3)
        elif tok in _SINGULAR_YEAR and _is_and_a_half(tokens, i + 1):
            total += 18  # "a year and a half"
            understood = True
            i += 4 if tokens[i + 1] == "and" else 3
        elif _is_half_year(tokens, i):
            total += 6
            understood = True
            i += 3 if tokens[i + 1] == "a" else 2
        elif tok in _SINGULAR_YEAR and before[-1:] == ["a"]:
            total += 12  # "a year"
            understood = True
            i += 1
        else:
            if tok in _UNIT_WORDS and before[-1:] and before[-1] in _VAGUE:
                suspicious = True  # "a few years", "unos meses"
            i += 1
    if suspicious and total <= _MAX_MONTHS:
        return Issue("unrecognized", _UNCLEAR_MONTHS_HINT)
    if not understood:
        if _NO_EXPERIENCE.intersection(tokens) or any(p in padded for p in _NO_EXPERIENCE_PHRASES):
            return 0  # only when no quantity is present: "pero 2 años en tiendas" is 24
        return Issue("unrecognized", _MONTHS_HINT)
    if 0 <= total <= _MAX_MONTHS:
        return total
    return Issue(
        "out_of_range",
        f"{total} months of experience is not plausible. Ask them to confirm how long.",
    )


# --- free text --------------------------------------------------------------------------

_MAX_TEXT = 300


def parse_text(raw: str, ctx: ParseContext) -> ParseResult[str]:
    """Collapse whitespace and trim to 300 characters at a word boundary; reject empty."""
    text = " ".join("".join(" " if unicodedata.category(c) == "Cc" else c for c in raw).split())
    if not text:
        return Issue("unrecognized", "Ask them to describe it again in a short sentence.")
    if len(text) > _MAX_TEXT:
        head = text[:_MAX_TEXT]
        if text[_MAX_TEXT] != " " and " " in head:
            head = head.rsplit(" ", 1)[0]
        text = head.rstrip()
    return text


# --- languages --------------------------------------------------------------------------

_LANGUAGE_WORDS: dict[str, str] = {}
for _code, _names in {
    "es": ("espanol", "spanish", "castellano", "castilian"),
    "en": ("ingles", "english"),
    "fr": ("frances", "french"),
    "pt": ("portugues", "portuguese"),
    "it": ("italiano", "italian"),
    "de": ("aleman", "german"),
    "ca": ("catalan", "catala", "catalonian"),
    "ar": ("arabe", "arabic"),
    "ro": ("rumano", "romanian"),
    "zh": ("chino", "chinese", "mandarin", "cantonese", "cantones"),
}.items():
    _LANGUAGE_WORDS.update(dict.fromkeys(_names, _code))

# ISO 639-1 codes the languages parser knows, in declaration order (single source of truth).
LANGUAGE_CODES: tuple[str, ...] = tuple(dict.fromkeys(_LANGUAGE_WORDS.values()))


_CLAUSE_SPLIT = re.compile(r"[,;.]|\b(?:pero|but|y|and|e|ni)\b")
_LANGUAGES_HINT = "Ask which languages they speak, for example Spanish or English."


def parse_languages(raw: str, ctx: ParseContext) -> ParseResult[list[str]]:
    """Language names -> ISO 639-1 codes in order of mention; negated languages are dropped."""
    codes: list[str] = []
    previous: list[str] = []  # languages of the previous clause, dropped by a bare "no lo hablo"
    for clause in _CLAUSE_SPLIT.split(normalise(raw)):
        tokens = words(clause)
        found = [c for t in tokens if (c := _LANGUAGE_WORDS.get(t)) is not None]
        negated = any(t in NEGATION_WORDS for t in tokens)
        if found and negated:
            previous = []
        elif found:
            previous = found
            codes.extend(c for c in found if c not in codes)
        elif negated:
            codes = [c for c in codes if c not in previous]
            previous = []
    if codes:
        return codes
    return Issue("unrecognized", _LANGUAGES_HINT)
