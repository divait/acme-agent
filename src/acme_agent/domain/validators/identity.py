"""Name, email and phone parsers."""

from __future__ import annotations

import re
from typing import Literal

import phonenumbers
from phonenumbers import NumberParseException, ValidationResult

from acme_agent.domain.spoken import (
    extract_digits,
    normalise,
)
from acme_agent.domain.validators.base import (
    Issue,
    ParseContext,
    ParseResult,
    has_negation,
    words,
)

# --- name -------------------------------------------------------------------------------

_NAME_FILLER = re.compile(
    r"^\s*(?:(?:hola|hello|hi|hey|buenas|buenos dias|buenas tardes|good (?:morning|afternoon))"
    r"[\s,.!]*)?"
    r"(?:me llamo|mi nombre es|mi nombre completo es|me dicen|soy|my name is|my name\u2019s|"
    r"my name's|my full name is|i am|i\u2019m|i'm|this is|it's|it is|es)(?:\s+|$)",
    re.IGNORECASE,
)
_NAME_SHAPE = re.compile(r"^[^\W\d_]+(?:[ '\u2019\-][^\W\d_]+)*$")
_LEADING_ACK = re.compile(
    r"^\s*(?:(?:hola|hello|hi|hey|buenas|buenos d[ií]as|buenas tardes|good (?:morning|afternoon)|"
    r"s[ií]|vale|ok|okay|claro|yes|yeah|sure|bueno|pues)(?:[\s,.!]+|$))+",
    re.IGNORECASE,
)
_CLAUSE_START = re.compile(
    r"\s*,.*$|\s+(?:y|and)\s+(?:vivo|soy|tengo|estoy|trabajo|quiero|busco|i|im)\b.*$|\s+que\b.*$",
    re.IGNORECASE,
)
_MAX_NAME_WORDS = 5
_NOT_A_NAME_START = frozenset({"de", "from", "no", "not"})


def _strip_ack(text: str) -> str:
    return _LEADING_ACK.sub("", text, count=1)


def parse_name(raw: str, ctx: ParseContext) -> ParseResult[str]:
    """Strip fillers and trailing clauses, validate letters, title-case; never accept non-names."""
    text = _strip_ack(raw.strip()).strip().strip('.,!?;:"')
    text = _NAME_FILLER.sub("", text).strip().strip('.,!?;:"')
    text = _CLAUSE_START.sub("", text).strip().strip('.,!?;:"')
    text = " ".join(text.split())
    tokens = words(text)
    plausible = (
        2 <= len(text) <= 100
        and _NAME_SHAPE.match(text) is not None
        and len(tokens) <= _MAX_NAME_WORDS
        and (not tokens or tokens[0] not in _NOT_A_NAME_START)
        and not has_negation(tokens)
    )
    if plausible:
        return text.title()
    return Issue(
        "invalid_name",
        "Ask for their first and last name again; it must contain only letters.",
    )


# --- email ------------------------------------------------------------------------------

_EMAIL_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\s+(?:punto|dot)\s+"), "."),
    (re.compile(r"\s+(?:guion bajo|underscore)\s+"), "_"),
    (re.compile(r"\s+(?:guion|dash|hyphen)\s+"), "-"),
)
_EMAIL_LEAD = re.compile(
    r"^\s*(?:"
    r"(?:pues|bueno|claro|vale|okay|ok|si|mira|yes|yeah|sure)(?!\s+(?:arroba|at)\s)(?=[\s,.!;:]|$)"
    r"|(?:mi|my|el|the)\s+(?:correo(?:\s+electronico)?|e-?mail|mail)(?:\s+(?:es|is))?(?=[\s:,]|$)"
    r"|it'?s|it\u2019s|es(?=[\s:,]))"
    r"[\s,.!;:]*"
)
_AT_WORD = re.compile(r"\s+(?:arroba|at)\s+")
_EMAIL_DIGIT_WORDS: dict[str, str] = {
    **dict.fromkeys(("cero", "zero"), "0"),
    **dict.fromkeys(("uno", "one"), "1"),
    **dict.fromkeys(("dos", "two"), "2"),
    **dict.fromkeys(("tres", "three"), "3"),
    **dict.fromkeys(("cuatro", "four"), "4"),
    **dict.fromkeys(("cinco", "five"), "5"),
    **dict.fromkeys(("seis", "six"), "6"),
    **dict.fromkeys(("siete", "seven"), "7"),
    **dict.fromkeys(("ocho", "eight"), "8"),
    **dict.fromkeys(("nueve", "nine"), "9"),
}
_DIGIT_WORD = re.compile(r"(?<![a-z])(?:" + "|".join(_EMAIL_DIGIT_WORDS) + r")(?![a-z])")
_EMAIL_SHAPE = re.compile(
    r"^[a-z0-9]+(?:[._%+\-][a-z0-9]+)*@[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)*"
    r"\.[a-z]{2,}$"
)
_EMAIL_ISSUE = Issue(
    "invalid_email",
    "Ask them to spell the email slowly: name, 'arroba' or 'at', then the domain.",
)


def _strip_email_leads(text: str) -> str:
    """Drop leading acknowledgements and "my email is"-style fillers, however many there are."""
    while (stripped := _EMAIL_LEAD.sub("", text, count=1)) != text:
        text = stripped
    return text


def _join_local(local: str) -> str | None:
    """Join the spoken local part; spoken digits and spelled letters only, never filler words."""
    local = _DIGIT_WORD.sub(lambda m: _EMAIL_DIGIT_WORDS[m.group()], local)
    pieces = local.split()
    if not pieces or any(len(p) > 1 and not p.isdigit() for p in pieces[1:]):
        return None
    return "".join(pieces)


def parse_email(raw: str, ctx: ParseContext) -> ParseResult[str]:
    """Strip fillers, convert spoken "arroba"/"punto"/digits, then check a basic address shape."""
    text = _strip_email_leads(normalise(raw)).strip().rstrip(".,!?;:")
    text = f" {text} "
    if "@" not in text:
        text = _AT_WORD.sub("@", text)
    for pattern, replacement in _EMAIL_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    local, sep, domain = text.strip().partition("@")
    joined = _join_local(local.strip())
    if not sep or joined is None or not domain.strip() or len(domain.split()) != 1:
        return _EMAIL_ISSUE
    email = f"{joined}@{domain.strip()}"
    if len(email) <= 254 and _EMAIL_SHAPE.match(email):
        return email
    return _EMAIL_ISSUE


# --- phone ------------------------------------------------------------------------------

_NATIONAL_LENGTH = {"ES": 9, "MX": 10}
_PHONE_HINTS = {
    "too_short": "The number is too short; ask them to repeat it slowly, digit by digit.",
    "too_long": "The number has too many digits; ask them to repeat it slowly, digit by digit.",
    "invalid_number": "That is not a valid number; ask them to repeat it slowly, digit by digit.",
}
_COUNTRY_NOTE = {
    "ES": " Spanish mobile numbers have 9 digits.",
    "MX": " Mexican numbers have 10 digits.",
}


def _phone_issue(code: str, country: str) -> Issue:
    return Issue(code, _PHONE_HINTS[code] + _COUNTRY_NOTE[country])


def _parse_phone_in(raw: str, country: Literal["ES", "MX"]) -> ParseResult[str]:
    """Spoken or typed digits -> E.164, using `country` as the default region."""
    digits = extract_digits(raw)
    if not digits:
        return _phone_issue("too_short", country)
    plus = "+" if raw.strip().startswith("+") else ""
    try:
        number = phonenumbers.parse(plus + digits, country)
    except NumberParseException:
        return _phone_issue("invalid_number", country)
    reason = phonenumbers.is_possible_number_with_reason(number)
    expected = _NATIONAL_LENGTH[country]
    if reason == ValidationResult.TOO_SHORT:
        return _phone_issue("too_short", country)
    if reason == ValidationResult.TOO_LONG:
        return _phone_issue("too_long", country)
    if reason == ValidationResult.INVALID_LENGTH and not plus:
        code = "too_short" if len(digits) < expected else "too_long"
        return _phone_issue(code, country)
    if reason != ValidationResult.IS_POSSIBLE or not phonenumbers.is_valid_number(number):
        return _phone_issue("invalid_number", country)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def parse_phone(raw: str, ctx: ParseContext) -> ParseResult[str]:
    """Spoken or typed digits -> E.164, trying `ctx.country` first, then the other country.

    A candidate may live in one country and prefer a store in the other, so a number that is
    invalid for the session country but valid for the other supported one is accepted. When
    neither is valid the issue is the one for the session country.
    """
    first = _parse_phone_in(raw, ctx.country)
    if not isinstance(first, Issue):
        return first
    other: Literal["ES", "MX"] = "MX" if ctx.country == "ES" else "ES"
    second = _parse_phone_in(raw, other)
    return first if isinstance(second, Issue) else second
