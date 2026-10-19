"""Yes/no and role parsers."""

from __future__ import annotations

from collections.abc import Mapping

from acme_agent.domain.models import Role
from acme_agent.domain.validators.base import (
    Issue,
    ParseContext,
    ParseResult,
    has_negation,
    words,
)

# --- yes / no ---------------------------------------------------------------------------

_YES = (
    "si", "claro", "vale", "por supuesto", "correcto", "afirmativo", "exacto", "desde luego",
    "efectivamente", "de acuerdo", "ok", "okay", "yes", "yeah", "yep", "yup", "sure",
    "of course", "correct", "absolutely", "right", "affirmative", "definitely",
)  # fmt: skip
_NO = (
    "no", "nope", "nel", "para nada", "negativo", "nunca", "jamas", "not really", "never",
    "negative", "nah", "claro que no", "por supuesto que no", "of course not", "not at all",
)  # fmt: skip
_UNSURE = (
    "no se", "no lo se", "no estoy seguro", "no estoy segura", "not sure", "no idea",
    "i dont know", "i do not know", "dont know",
)  # fmt: skip
_MORE_YES = ("no problem", "no hay problema", "sin problema")
_MAX_TRAILING_WORDS = 6

_PHRASES: list[tuple[list[str], str]] = sorted(
    [(p.split(), "yes") for p in (*_YES, *_MORE_YES)]
    + [(p.split(), "no") for p in _NO]
    + [(p.split(), "unsure") for p in _UNSURE],
    key=lambda pair: -len(pair[0]),
)  # longest first: "claro que no" beats "claro", "no se" beats "no"


def _phrase_hits(tokens: list[str]) -> list[tuple[int, int, str]]:
    """Every yes/no/unsure phrase as (start, end, polarity), longest match first."""
    hits: list[tuple[int, int, str]] = []
    i = 0
    while i < len(tokens):
        for words_, polarity in _PHRASES:
            if tokens[i : i + len(words_)] == words_:
                hits.append((i, i + len(words_), polarity))
                i += len(words_)
                break
        else:
            i += 1
    return hits


def parse_bool(raw: str, ctx: ParseContext) -> ParseResult[bool]:
    """Colloquial yes/no in Spanish or English; a yes and a no together is never guessed."""
    tokens = words(raw)
    hits = _phrase_hits(tokens)
    polarities = {polarity for _, _, polarity in hits}
    if "yes" in polarities and "no" in polarities:
        return Issue(
            "contradictory",
            "The answer contained both yes and no. Ask again for a plain yes or no.",
        )
    if hits and "unsure" not in polarities:
        start, end, polarity = hits[0]
        if start == 0 and len(tokens) - end <= _MAX_TRAILING_WORDS:
            return polarity == "yes"
    return Issue("unrecognized", "Ask again for a plain yes or no.")


# --- role -------------------------------------------------------------------------------

ROLE_WORDS: Mapping[Role, tuple[str, ...]] = {
    Role.CREW_MEMBER: (
        "cajero", "cajera", "caja", "mostrador", "drive", "counter", "cashier", "crew", "sala",
        "atencion",
    ),
    Role.KITCHEN: ("cocina", "cocinero", "cocinera", "cook", "kitchen", "chef", "plancha", "grill"),
    Role.DELIVERY_RIDER: (
        "repartidor", "repartidora", "rider", "delivery", "moto", "reparto", "repartos",
        "repartir", "courier", "motorista",
    ),
}  # fmt: skip


def parse_role(raw: str, ctx: ParseContext) -> ParseResult[Role]:
    """Map synonyms ("cajero", "cook", "moto"...) to the closed role enum."""
    all_tokens = words(raw)
    if has_negation(all_tokens):
        return Issue(
            "unrecognized",
            "The answer was negated or unclear, so do not guess a role. Ask which role they "
            "want: crew member (counter, cashier, drive), kitchen, or delivery rider.",
        )
    tokens = set(all_tokens)
    found = [role for role, words in ROLE_WORDS.items() if tokens.intersection(words)]
    if len(found) == 1:
        return found[0]
    return Issue(
        "unrecognized",
        "Ask which role they want: crew member (counter, cashier, drive), "
        "kitchen, or delivery rider.",
    )
