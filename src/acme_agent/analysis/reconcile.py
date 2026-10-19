"""Pure reconciliation of live slots with the post-call extraction (ADR-008.1, ADR-008.2).

Cases per slot: agree -> keep; live empty and post valid -> fill; disagree -> keep live and
report a conflict; both empty -> nothing. Post values are validated by the same
CANONICAL / VERBATIM registries as live input (ADR-015.8) and must be grounded in what the
candidate said; invalid or ungrounded values are dropped and never create a conflict.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace

from pydantic_core import to_jsonable_python

from acme_agent.analysis.schemas import ExtractionResult
from acme_agent.domain.models import CandidateProfile, ReconciliationConflict, SlotName
from acme_agent.domain.validators import CANONICAL, VERBATIM, Issue, ParseContext
from acme_agent.interview.controller import Fill, ReconciliationResult
from acme_agent.interview.evidence import said_in_transcript
from acme_agent.interview.readback import normalise_text
from acme_agent.interview.slots import SLOT_BY_NAME, SLOTS


def _is_empty(value: object) -> bool:
    return value is None or value == []


# Free-text slots are written by the model, so two phrasings never count as a conflict.
FREE_TEXT: frozenset[SlotName] = frozenset({SlotName.EXPERIENCE_SUMMARY})


def _same(a: object, b: object) -> bool:
    """Equal after normalisation: lists as sets, text casefolded, unaccented, punctuation-free."""
    if isinstance(a, list) and isinstance(b, list):
        return set(a) == set(b)
    if isinstance(a, str) and isinstance(b, str):
        if a == b:
            return True
        if "@" in a and "@" in b:
            return a.strip().casefold() == b.strip().casefold()
        return normalise_text(a) == normalise_text(b)
    return a == b


def _with_store_country(ctx: ParseContext, store_id: object) -> ParseContext:
    store = next((s for s in ctx.stores if s.id == store_id), None)
    if store is not None and store.country in ("ES", "MX"):
        return replace(ctx, country=store.country)  # type: ignore[arg-type]
    return ctx


def _grounded(said: str | None, turn: int | None, candidate_turns: Mapping[int, str]) -> bool:
    """The quoted words must share a meaningful token with a candidate turn (cheap check).

    The referenced turn is tried first, then any candidate turn (turn numbers may be off).
    """
    if not said or not said.strip():
        return False
    texts = list(candidate_turns.values())
    if turn is not None and turn in candidate_turns:
        texts.insert(0, candidate_turns[turn])
    return any(said_in_transcript(said, [text]) for text in texts)


def _value_grounded(name: SlotName, value: str, candidate_turns: Mapping[int, str]) -> bool:
    """Verbatim values (phone, email, name, store) must also appear in what the candidate said."""
    heard = " ".join(candidate_turns.values())
    if name is SlotName.PHONE:
        digits = re.sub(r"\D", "", value)
        return bool(digits) and (
            digits in re.sub(r"\D", "", heard) or said_in_transcript(value, [heard])
        )
    if name is SlotName.EMAIL:
        local, _, domain = value.strip().lower().partition("@")
        low = normalise_text(heard)
        parts = [normalise_text(x) for x in (local, domain.split(".")[0]) if x]
        return any(x and x in low for x in parts)
    return said_in_transcript(value, [heard])


def reconcile(
    live: CandidateProfile,
    extracted: ExtractionResult,
    ctx: ParseContext,
    candidate_turns: Mapping[int, str],
) -> ReconciliationResult:
    """Compare `live` with `extracted`; `candidate_turns` maps turn number -> candidate text."""
    by_slot = {item.slot: item for item in extracted.slots if item.value and item.value.strip()}
    working = live.model_copy(deep=True)
    fills: list[Fill] = []
    conflicts: list[ReconciliationConflict] = []
    ordered = sorted(SLOTS, key=lambda s: s.name is not SlotName.PREFERRED_STORE_ID)
    ordered.sort(key=lambda s: s.name is not SlotName.ROLE)  # stable: role, store, then the rest
    for spec in ordered:  # role activates rider slots; store sets the country phone needs
        name = spec.name
        item = by_slot.get(name)
        if item is None or item.value is None or name is SlotName.CONSENT_RECORDING:
            continue
        if not SLOT_BY_NAME[name].active(working):
            continue
        canonical = name in CANONICAL
        parser = CANONICAL[name] if canonical else VERBATIM[name]
        text = item.value if canonical else (item.value.strip())
        parsed = parser(text, ctx)
        if isinstance(parsed, Issue) or not _grounded(item.said, item.turn, candidate_turns):
            continue
        if not canonical and not _value_grounded(name, text, candidate_turns):
            continue
        current = getattr(working, name.value)
        if _is_empty(current):
            setattr(working, name.value, parsed)
            fills.append(Fill(slot=name, value=parsed, said=item.said))
            if name is SlotName.PREFERRED_STORE_ID:
                ctx = _with_store_country(ctx, parsed)
        elif name not in FREE_TEXT and not _same(current, parsed):
            conflicts.append(
                ReconciliationConflict(
                    slot=name,
                    live=to_jsonable_python(current),
                    post_call=to_jsonable_python(parsed),
                )
            )
    return ReconciliationResult(fills=fills, conflicts=conflicts)
