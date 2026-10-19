"""Spoken-number helpers (ES/EN), table driven."""

from __future__ import annotations

import pytest

from acme_agent.domain.spoken import extract_digits, normalise, tokenize, words_to_int


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cero", 0), ("uno", 1), ("una", 1), ("dos", 2), ("tres", 3), ("cuatro", 4),
        ("cinco", 5), ("seis", 6), ("siete", 7), ("ocho", 8), ("nueve", 9),
        ("diez", 10), ("once", 11), ("doce", 12), ("trece", 13), ("catorce", 14),
        ("quince", 15), ("dieciséis", 16), ("diecisiete", 17), ("dieciocho", 18),
        ("diecinueve", 19), ("veinte", 20), ("veintiuno", 21), ("veintiún", 21),
        ("veintidós", 22), ("veintitrés", 23), ("veinticinco", 25), ("veintinueve", 29),
        ("treinta", 30), ("treinta y dos", 32), ("cuarenta y cinco", 45),
        ("cincuenta", 50), ("sesenta y seis", 66), ("setenta y siete", 77),
        ("ochenta y ocho", 88), ("noventa y nueve", 99),
        ("cien", 100), ("ciento veinte", 120), ("ciento cinco", 105),
        ("doscientos", 200), ("trescientos cuarenta y dos", 342), ("quinientos", 500),
        ("seiscientos", 600), ("seiscientos cinco", 605), ("novecientos noventa y nueve", 999),
        ("zero", 0), ("one", 1), ("two", 2), ("nine", 9), ("ten", 10), ("eleven", 11),
        ("seventeen", 17), ("nineteen", 19), ("twenty", 20), ("twenty-one", 21),
        ("twenty one", 21), ("thirty two", 32), ("forty-five", 45), ("ninety nine", 99),
        ("one hundred", 100), ("six hundred", 600), ("six hundred and five", 605),
        ("two hundred forty five", 245), ("nine hundred ninety-nine", 999),
        ("18", 18), ("30", 30),
    ],
)  # fmt: skip
def test_words_to_int_parses(text: str, expected: int) -> None:
    assert words_to_int(text) == expected


@pytest.mark.parametrize(
    "text", ["", "???", "hola", "seis cero", "treinta y", "twenty hello", "uno dos", "hundred"]
)
def test_words_to_int_rejects(text: str) -> None:
    assert words_to_int(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("seis cero cero, uno dos tres", "600123"),
        ("seis cero cero, uno dos tres, cuatro cinco seis", "600123456"),
        ("six zero zero one two three", "600123"),
        ("six oh oh, one two three", "600123"),
        ("cincuenta y cinco, doce treinta y cuatro", "55" + "12" + "34"),
        ("doble tres", "33"),
        ("seis doble cero uno", "6001"),
        ("triple cinco", "555"),
        ("double five", "55"),
        ("six double zero triple seven", "600777"),
        ("doble 3", "33"),
        ("55 1234 5678", "5512345678"),
        ("600-123-456", "600123456"),
        ("+34 600 123 456", "34600123456"),
        ("my number is six hundred", "600"),
        ("seiscientos", "600"),
        ("mi número es el seis uno uno", "611"),
        ("treinta y dos", "32"),
        ("twenty-one", "21"),
        ("hola", ""),
        ("???", ""),
        ("", ""),
        ("doble", ""),
    ],
)
def test_extract_digits(text: str, expected: str) -> None:
    assert extract_digits(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Ñandú   ÁÉÍ  ", "nandu aei"),
        ("Hello,  WORLD", "hello, world"),
        ("Gràcia", "gracia"),
        ("", ""),
    ],
)
def test_normalise(text: str, expected: str) -> None:
    assert normalise(text) == expected


def test_tokenize_drops_punctuation_and_hyphens() -> None:
    assert tokenize("Twenty-one, Chamberí!") == ["twenty", "one", "chamberi"]
