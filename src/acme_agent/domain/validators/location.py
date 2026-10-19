"""Store matching."""

from __future__ import annotations

from collections.abc import Sequence

from rapidfuzz import fuzz

from acme_agent.domain.models import Store
from acme_agent.domain.spoken import (
    normalise,
    tokenize,
)
from acme_agent.domain.validators.base import Issue, ParseContext, ParseResult

# --- store ------------------------------------------------------------------------------

_MATCH_MIN = 85.0
_MATCH_LEAD = 10.0
_MAX_OPTIONS = 3
_MIN_COMBINED_WORDS = 2
_COMBINED_MIN = 95.0
_COMBINED_LEAD = 15.0


def _describe(store: Store) -> str:
    return f"{store.name} ({store.area}, {store.city})"


def _prefer_city_and_area(query: str, close: list[Store]) -> list[Store]:
    """ "valencia centro": when exactly one close store matches city + area, keep only it."""
    if len(query.split()) < _MIN_COMBINED_WORDS:
        return close
    scores = [(fuzz.token_set_ratio(query, normalise(f"{s.city} {s.area}")), s) for s in close]
    scores.sort(key=lambda pair: -pair[0])
    top = scores[0][0]
    if top >= _COMBINED_MIN and top - scores[1][0] >= _COMBINED_LEAD:
        return [scores[0][1]]
    return close


def _contains_phrase(tokens: list[str], phrase: str) -> bool:
    """True when the words of `phrase` appear contiguously in `tokens` (accent-insensitive)."""
    words = tokenize(phrase)
    n = len(words)
    if n == 0:
        return False
    return any(tokens[i : i + n] == words for i in range(len(tokens) - n + 1))


def _ambiguous(stores: list[Store]) -> Issue:
    options = "; ".join(_describe(s) for s in stores[:_MAX_OPTIONS])
    return Issue("ambiguous", f"Several stores match: {options}. Ask which one they prefer.")


def _match_by_area_or_city(raw: str, stores: Sequence[Store]) -> ParseResult[str] | None:
    """Deterministic precedence: a named area wins, a city only confirms or narrows.

    Returns None when neither an area nor a city is named, so the fuzzy scoring decides.
    """
    tokens = tokenize(raw)
    cities = {s.city for s in stores}
    named_cities = {c for c in cities if _contains_phrase(tokens, c)}
    by_area = [s for s in stores if _contains_phrase(tokens, s.area)]
    if by_area and len({s.area for s in by_area}) == 1:
        if named_cities:
            in_named = [s for s in by_area if s.city in named_cities]
            if not in_named:
                return _ambiguous(by_area)  # the city contradicts the area: never guess
            by_area = in_named
        if len(by_area) == 1:
            return by_area[0].id
        return _ambiguous(by_area)
    if not by_area and len(named_cities) == 1:
        in_city = [s for s in stores if s.city in named_cities]
        if len(in_city) > 1:
            return _ambiguous(in_city)
    return None


def parse_store(raw: str, ctx: ParseContext) -> ParseResult[str]:
    """Match a store of `ctx.stores` by area (city narrows), then fuzzy; returns the store id."""
    precedence = _match_by_area_or_city(raw, ctx.stores)
    if precedence is not None:
        return precedence
    query = normalise(raw)
    scored: list[tuple[float, Store]] = []
    if query:
        for store in ctx.stores:
            fields = (store.name, store.city, store.area)
            score = max(fuzz.WRatio(query, normalise(field)) for field in fields)
            scored.append((score, store))
        scored.sort(key=lambda pair: -pair[0])
    if scored and scored[0][0] >= _MATCH_MIN:
        best = scored[0][0]
        close = [s for score, s in scored if best - score < _MATCH_LEAD]
        if len(close) > 1:
            close = _prefer_city_and_area(query, close)
        if len(close) == 1:
            return close[0].id
        options = "; ".join(_describe(s) for s in close[:_MAX_OPTIONS])
        return Issue(
            "ambiguous",
            f"Several stores match: {options}. Ask which one they prefer.",
        )
    cities = sorted({s.city for s in ctx.stores})
    served = ", ".join(cities) if cities else "none"
    return Issue(
        "not_found",
        f"No store matched. We have stores in: {served}. Ask which city or area they prefer.",
    )
