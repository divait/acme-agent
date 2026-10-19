"""Spoken-input helpers shared by the slot parsers (Spanish and English).

Pure functions only: normalisation for matching, spoken number words to integers and
digit-sequence extraction for phone-like input.
"""

from __future__ import annotations

import re
import unicodedata

_SEGMENT_SPLIT = re.compile(r"[,;.:]+")
_TOKEN = re.compile(r"\d+|[a-z]+")

_UNITS: dict[str, int] = {
    "cero": 0, "uno": 1, "una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}  # fmt: skip

_TEENS: dict[str, int] = {
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiuno": 21, "veintiun": 21, "veintiuna": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip

_ES_TENS: dict[str, int] = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}  # fmt: skip

_EN_TENS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip

_ES_HUNDREDS: dict[str, int] = {
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200,
    "trescientos": 300, "trescientas": 300, "cuatrocientos": 400, "cuatrocientas": 400,
    "quinientos": 500, "quinientas": 500, "seiscientos": 600, "seiscientas": 600,
    "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
    "novecientos": 900, "novecientas": 900,
}  # fmt: skip

_REPEATERS: dict[str, int] = {"doble": 2, "double": 2, "triple": 3}
_CONNECTORS = frozenset({"y", "and"})
_ALL_TENS = {**_ES_TENS, **_EN_TENS}
_MAX_DIGIT_RUN = 6  # longer digit runs are never a quantity; also avoids huge int() parses


def normalise(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace. For matching only, never for output."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.split())


def tokenize(text: str) -> list[str]:
    """Normalised alphabetic words and digit runs; punctuation and hyphens are dropped."""
    return _TOKEN.findall(normalise(text))


def _is_connector_before_number(tokens: list[str], i: int) -> bool:
    return (
        i + 1 < len(tokens)
        and tokens[i] in _CONNECTORS
        and (tokens[i + 1] in _UNITS or tokens[i + 1] in _TEENS or tokens[i + 1] in _ALL_TENS)
    )


def _number_at(tokens: list[str], i: int) -> tuple[int, int] | None:
    """Parse one number (0-999) starting at `tokens[i]`; returns (value, next index)."""
    n = len(tokens)
    j = i
    total = 0
    has_hundreds = False
    tok = tokens[j]
    if tok in _ES_HUNDREDS:
        total, j, has_hundreds = _ES_HUNDREDS[tok], j + 1, True
    elif tok in _UNITS and _UNITS[tok] > 0 and j + 1 < n and tokens[j + 1] == "hundred":
        total, j, has_hundreds = _UNITS[tok] * 100, j + 2, True
    if has_hundreds and _is_connector_before_number(tokens, j):
        j += 1
    if j < n:
        tok = tokens[j]
        if tok in _TEENS:
            return total + _TEENS[tok], j + 1
        if tok in _ALL_TENS:
            total += _ALL_TENS[tok]
            j += 1
            if j < n:
                if tok in _EN_TENS and tokens[j] in _UNITS and _UNITS[tokens[j]] > 0:
                    return total + _UNITS[tokens[j]], j + 1
                if (
                    tokens[j] == "y"
                    and j + 1 < n
                    and tokens[j + 1] in _UNITS
                    and _UNITS[tokens[j + 1]] > 0
                ):
                    return total + _UNITS[tokens[j + 1]], j + 2
            return total, j
        if tok in _UNITS and ((has_hundreds and _UNITS[tok] > 0) or not has_hundreds):
            return total + _UNITS[tok], j + 1
    if has_hundreds:
        return total, j
    return None


def words_to_int(text: str) -> int | None:
    """Whole `text` as one number written in digits or words (0-999), else None.

    "treinta y dos" -> 32, "twenty-one" -> 21, "six hundred" -> 600, "18" -> 18.
    """
    tokens = [t for t in tokenize(text) if t not in ("de", "of")]
    if not tokens:
        return None
    if len(tokens) == 1 and tokens[0].isdigit():
        return int(tokens[0]) if len(tokens[0]) <= _MAX_DIGIT_RUN else None
    parsed = _number_at(tokens, 0)
    if parsed is None or parsed[1] != len(tokens):
        return None
    return parsed[0]


def extract_digits(text: str) -> str:
    """Digits spoken or typed in `text`, in order; other words and separators are ignored.

    "seis cero cero, uno dos tres" -> "600123"; "doble tres" -> "33"; "55 1234" -> "551234".
    """
    out: list[str] = []
    for segment in _SEGMENT_SPLIT.split(normalise(text)):
        tokens = _TOKEN.findall(segment)
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.isdigit():
                out.append(tok)
                i += 1
            elif tok in _REPEATERS and i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if nxt in _UNITS:
                    out.append(str(_UNITS[nxt]) * _REPEATERS[tok])
                    i += 2
                elif len(nxt) == 1 and nxt.isdigit():
                    out.append(nxt * _REPEATERS[tok])
                    i += 2
                else:
                    i += 1
            else:
                parsed = _number_at(tokens, i)
                if parsed is None:
                    i += 1
                else:
                    out.append(str(parsed[0]))
                    i = parsed[1]
    return "".join(out)


def scan_numbers(tokens: list[str]) -> list[tuple[int, int, int]]:
    """Every number in `tokens` as (value, start, end) with `end` exclusive.

    Digit runs and spoken numbers (0-999) are found; digit runs over six digits and the
    phone-style "oh" are skipped.
    """
    found: list[tuple[int, int, int]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.isdigit():
            if len(tok) <= _MAX_DIGIT_RUN:
                found.append((int(tok), i, i + 1))
            i += 1
            continue
        parsed = None if tok == "oh" else _number_at(tokens, i)
        if parsed is None:
            i += 1
        else:
            found.append((parsed[0], i, parsed[1]))
            i = parsed[1]
    return found


def find_numbers(text: str) -> list[int]:
    """Numbers written in digits or words in `text`, in order of appearance."""
    return [value for value, _, _ in scan_numbers(tokenize(text))]


def numbers_to_digits(tokens: list[str]) -> list[str]:
    """Replace spoken numbers in `tokens` with digit tokens ("dos semanas" -> "2 semanas")."""
    out: list[str] = []
    last = 0
    for value, start, end in scan_numbers(tokens):
        out.extend(tokens[last:start])
        out.append(str(value))
        last = end
    out.extend(tokens[last:])
    return out
