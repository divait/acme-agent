"""Read-back matching and formatting for role and risky slots (ADR-016.5).

Pure: no clock, no I/O. `READBACK` maps each risky slot to its label, a formatter (the value
as shown to the candidate) and a matcher (does the agent's reply mention that value?). The
controller only iterates over risky slots and dispatches through the table.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from datetime import date

import phonenumbers

from acme_agent.domain.models import Role, SlotName, Store
from acme_agent.domain.validators import ROLE_WORDS

# (value, stores, spoken) -> text. `spoken` adds spacing the candidate can follow aloud.
type FormatFn = Callable[[object, Sequence[Store], bool], str]
# (value, reply text, stores) -> whether the reply mentions the value.
type MentionedFn = Callable[[object, str, Sequence[Store]], bool]

_MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip
_MONTHS_EN = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)  # fmt: skip


def normalise_text(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    folded = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def _spaced_phone(value: str) -> str:
    """E.164 -> international format with spaces; unparseable values stay as they are."""
    try:
        return phonenumbers.format_number(
            phonenumbers.parse(value, None), phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
    except phonenumbers.NumberParseException:
        return value


def _date_mentioned(value: date, text: str) -> bool:
    """ISO date, or day-of-month plus (month number or Spanish/English month name)."""
    if value.isoformat() in text:
        return True
    numbers = {int(n) for n in re.findall(r"(?<!\d)\d{1,4}(?!\d)", text)}
    if value.day not in numbers:
        return False
    if value.month in numbers:
        return True
    norm = normalise_text(text)
    names = (_MONTHS_ES[value.month - 1], _MONTHS_EN[value.month - 1])
    return any(re.search(rf"\b{name}\b", norm) for name in names)


def _store_of(value: object, stores: Sequence[Store]) -> Store | None:
    return next((s for s in stores if s.id == value), None)


def _format_phone(value: object, stores: Sequence[Store], spoken: bool) -> str:
    return _spaced_phone(str(value)) if spoken else str(value)


def _phone_mentioned(value: object, text: str, stores: Sequence[Store]) -> bool:
    return re.sub(r"\D", "", str(value))[-4:] in re.sub(r"\D", "", text)


def _format_store(value: object, stores: Sequence[Store], spoken: bool) -> str:
    store = _store_of(value, stores)
    return f"{store.name} ({store.city})" if store else str(value)


def _store_mentioned(value: object, text: str, stores: Sequence[Store]) -> bool:
    store = _store_of(value, stores)
    names = [normalise_text(n) for n in (store.area, store.name)] if store else []
    norm = normalise_text(text)
    return any(n and n in norm for n in names)


def _format_date(value: object, stores: Sequence[Store], spoken: bool) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _date_slot_mentioned(value: object, text: str, stores: Sequence[Store]) -> bool:
    return isinstance(value, date) and _date_mentioned(value, text)


def _format_name(value: object, stores: Sequence[Store], spoken: bool) -> str:
    return str(value)


def _name_mentioned(value: object, text: str, stores: Sequence[Store]) -> bool:
    """Every token of the name appears in the text (case/accent-insensitive)."""
    tokens = normalise_text(str(value)).split()
    present = set(normalise_text(text).split())
    return bool(tokens) and all(t in present for t in tokens)


READBACK: dict[SlotName, tuple[str, FormatFn, MentionedFn]] = {
    SlotName.FULL_NAME: ("name", _format_name, _name_mentioned),
    SlotName.PHONE: ("phone", _format_phone, _phone_mentioned),
    SlotName.PREFERRED_STORE_ID: ("store", _format_store, _store_mentioned),
    SlotName.START_DATE: ("start date", _format_date, _date_slot_mentioned),
}


def role_mentioned(role: Role, text: str) -> bool:
    """True when the text contains one of the role's words as a whole word (ES/EN)."""
    tokens = set(normalise_text(text).split())
    return bool(tokens.intersection(ROLE_WORDS[role]))
