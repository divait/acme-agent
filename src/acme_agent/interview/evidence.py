"""Advisory check that a recorded `said` quote comes from what the candidate actually said.

Pure: no clock, no I/O. Voice transcripts are approximate, so the result is only a signal
(logged and counted by the caller); it never blocks or changes a value.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from acme_agent.interview.readback import normalise_text

RECENT_TURNS = 3

_STOP_TEXT = """
a an the of to in on at is am are and or but for with my me i you it its this that
de la el los las un una unos unas y o en con por para mi yo tu es soy son que
se al del lo le su sus no si yes ok vale hola hello hi
"""
_STOP_WORDS = frozenset(_STOP_TEXT.split())


def _tokens(text: str) -> set[str]:
    return {
        t
        for t in normalise_text(text).split()
        if len(t) > 1 and t not in _STOP_WORDS and not t.isdigit()
    }


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def said_in_transcript(said: str, recent_candidate_texts: Sequence[str]) -> bool:
    """True when `said` shares a meaningful token or digit run with the recent candidate turns.

    An empty `said` is treated as verified (nothing was claimed).
    """
    if not said.strip():
        return True
    recent = list(recent_candidate_texts)[-RECENT_TURNS:]
    heard = " ".join(recent)
    if _tokens(said) & _tokens(heard):
        return True
    claimed, spoken = _digits(said), _digits(heard)
    return len(claimed) >= 3 and len(spoken) >= 3 and (claimed in spoken or spoken in claimed)
