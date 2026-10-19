"""Slot specifications as data (ADR-016.5).

A `SlotSpec` says where a slot sits in the interview, when it applies and what the model
should ask. It carries no parser: the slot's class and validator come from the ADR-015
registries (`CANONICAL` / `VERBATIM`), and required / rider-only membership comes from
`domain/models.py`, so there is one source of truth for each.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from acme_agent.domain import models as _models
from acme_agent.domain.models import (
    CandidateProfile,
    Role,
    SlotName,
)

ALWAYS_REQUIRED: frozenset[SlotName] = frozenset(_models.ALWAYS_REQUIRED)
RIDER_ONLY: frozenset[SlotName] = frozenset(_models.RIDER_REQUIRED)


class SlotPhase(IntEnum):
    """Interview stages in asking order."""

    CONSENT = 1
    ROLE = 2
    IDENTITY = 3
    LOCATION = 4
    AVAILABILITY = 5
    ELIGIBILITY = 6
    EXPERIENCE = 7


type Condition = Callable[[CandidateProfile], bool]


def is_rider(profile: CandidateProfile) -> bool:
    """Condition for the rider-only slots."""
    return profile.role is Role.DELIVERY_RIDER


@dataclass(frozen=True)
class SlotSpec:
    """One slot: position, applicability, the instruction for the model and risk marker."""

    name: SlotName
    phase: SlotPhase
    order: int
    ask: str
    when: Condition | None = None
    risky: bool = False  # read back to the candidate before closing

    @property
    def required(self) -> bool:
        """Required for the interview to complete (when active)."""
        return self.name in ALWAYS_REQUIRED or self.name in RIDER_ONLY

    def active(self, profile: CandidateProfile) -> bool:
        """True when the slot applies to this candidate."""
        return self.when is None or self.when(profile)


_VERBATIM_NOTE = "call record_field with value as their exact words"


def _spec(
    name: SlotName,
    phase: SlotPhase,
    order: int,
    ask: str,
    *,
    when: Condition | None = None,
    risky: bool = False,
) -> SlotSpec:
    return SlotSpec(name, phase, order, ask, when, risky)


SLOTS: tuple[SlotSpec, ...] = (
    _spec(
        SlotName.CONSENT_RECORDING,
        SlotPhase.CONSENT,
        1,
        "Ask permission to record and process the conversation for this application, then "
        "call record_field with value as yes or no and said as their words.",
    ),
    _spec(
        SlotName.ROLE,
        SlotPhase.ROLE,
        1,
        "Ask which role they applied for: counter and drive-thru crew, kitchen or delivery "
        "rider. Then call record_field with value as crew_member, kitchen or delivery_rider "
        "and said as their words.",
    ),
    _spec(
        SlotName.FULL_NAME,
        SlotPhase.IDENTITY,
        1,
        f"Ask for their first and last name, then {_VERBATIM_NOTE}.",
        risky=True,
    ),
    _spec(
        SlotName.PHONE,
        SlotPhase.IDENTITY,
        2,
        f"Ask for a contact phone number, then {_VERBATIM_NOTE} (digits as they said them).",
        risky=True,
    ),
    _spec(
        SlotName.EMAIL,
        SlotPhase.IDENTITY,
        3,
        f"Optionally ask for an email address, then {_VERBATIM_NOTE}.",
    ),
    _spec(
        SlotName.PREFERRED_STORE_ID,
        SlotPhase.LOCATION,
        1,
        f"Ask which store, city or area they would like to work in, then {_VERBATIM_NOTE}.",
        risky=True,
    ),
    _spec(
        SlotName.AVAILABILITY,
        SlotPhase.AVAILABILITY,
        1,
        "Ask which days and shifts (morning, afternoon, night) they can work, then call "
        "record_field with value as comma-separated day:shift pairs such as "
        "mon:morning,sat:night and said as their words.",
    ),
    _spec(
        SlotName.WEEKLY_HOURS,
        SlotPhase.AVAILABILITY,
        2,
        "Ask how many hours per week they want to work, then call record_field with value "
        "as an integer from 10 to 40 and said as their words.",
    ),
    _spec(
        SlotName.START_DATE,
        SlotPhase.AVAILABILITY,
        3,
        "Ask when they can start, then call record_field with value as YYYY-MM-DD and "
        "said as their words.",
        risky=True,
    ),
    _spec(
        SlotName.RIGHT_TO_WORK,
        SlotPhase.ELIGIBILITY,
        1,
        "Ask if they have the legal right to work in the country (never ask nationality), "
        "then call record_field with value as yes or no and said as their words.",
    ),
    _spec(
        SlotName.IS_18_OR_OVER,
        SlotPhase.ELIGIBILITY,
        2,
        "Ask if they are 18 or over (never ask their exact age), then call record_field "
        "with value as yes or no and said as their words.",
    ),
    _spec(
        SlotName.DRIVING_LICENCE,
        SlotPhase.ELIGIBILITY,
        3,
        "Ask if they have a driving licence valid for a moped or car, then call "
        "record_field with value as yes or no and said as their words.",
        when=is_rider,
    ),
    _spec(
        SlotName.OWN_VEHICLE,
        SlotPhase.ELIGIBILITY,
        4,
        "Ask if they have their own moped, bike or car for deliveries, then call "
        "record_field with value as yes or no and said as their words.",
        when=is_rider,
    ),
    _spec(
        SlotName.EXPERIENCE_MONTHS,
        SlotPhase.EXPERIENCE,
        1,
        "Ask how many months of relevant work experience they have, then call record_field "
        "with value as an integer number of months (0 if none) and said as their words.",
    ),
    _spec(
        SlotName.EXPERIENCE_SUMMARY,
        SlotPhase.EXPERIENCE,
        2,
        "Optionally ask for a short summary of their experience, then call record_field "
        "with value as a sentence of at most 300 characters written by you.",
    ),
    _spec(
        SlotName.LANGUAGES,
        SlotPhase.EXPERIENCE,
        3,
        "Optionally ask which languages they speak, then call record_field with value as "
        "comma-separated ISO 639-1 codes such as es,en and said as their words.",
    ),
)

SLOT_BY_NAME: dict[SlotName, SlotSpec] = {spec.name: spec for spec in SLOTS}
