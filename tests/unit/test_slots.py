"""Slot specs agree with the domain models and the validator registries."""

from __future__ import annotations

from acme_agent.domain.models import CandidateProfile, Role, SlotName
from acme_agent.domain.validators import CANONICAL, VERBATIM
from acme_agent.interview.slots import SLOT_BY_NAME, SLOTS, SlotPhase


def test_slots_cover_every_slot_name_once() -> None:
    names = [spec.name for spec in SLOTS]
    assert sorted(names) == sorted(SlotName)
    assert len(set(names)) == len(names)


def test_every_slot_has_a_validator() -> None:
    for spec in SLOTS:
        assert (spec.name in CANONICAL) != (spec.name in VERBATIM)


def test_slots_are_in_phase_order() -> None:
    keys = [(spec.phase, spec.order) for spec in SLOTS]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def _required(profile: CandidateProfile) -> set[SlotName]:
    return {s.name for s in SLOTS if s.required and s.active(profile)}


def test_required_matches_models() -> None:
    no_role = CandidateProfile()
    assert _required(no_role) == set(no_role.missing_required())
    crew = CandidateProfile(role=Role.CREW_MEMBER)
    assert _required(crew) == set(crew.missing_required()) | {SlotName.ROLE}
    rider = CandidateProfile(role=Role.DELIVERY_RIDER)
    assert _required(rider) == set(rider.missing_required()) | {SlotName.ROLE}
    assert {SlotName.DRIVING_LICENCE, SlotName.OWN_VEHICLE} <= _required(rider)
    assert not {SlotName.EMAIL, SlotName.LANGUAGES, SlotName.EXPERIENCE_SUMMARY} & _required(rider)


def test_rider_slots_are_conditional() -> None:
    rider = CandidateProfile(role=Role.DELIVERY_RIDER)
    kitchen = CandidateProfile(role=Role.KITCHEN)
    for name in (SlotName.DRIVING_LICENCE, SlotName.OWN_VEHICLE):
        assert SLOT_BY_NAME[name].active(rider)
        assert not SLOT_BY_NAME[name].active(kitchen)
        assert not SLOT_BY_NAME[name].active(CandidateProfile())
    assert SLOT_BY_NAME[SlotName.FULL_NAME].active(kitchen)


def test_risky_slots() -> None:
    risky = {spec.name for spec in SLOTS if spec.risky}
    assert risky == {
        SlotName.FULL_NAME,
        SlotName.PHONE,
        SlotName.START_DATE,
        SlotName.PREFERRED_STORE_ID,
    }


def test_phase_order_follows_the_design() -> None:
    assert SLOT_BY_NAME[SlotName.CONSENT_RECORDING].phase is SlotPhase.CONSENT
    assert SLOT_BY_NAME[SlotName.LANGUAGES].phase is SlotPhase.EXPERIENCE


def test_canonical_asks_name_the_format() -> None:
    assert "YYYY-MM-DD" in SLOT_BY_NAME[SlotName.START_DATE].ask
    assert "day:shift" in SLOT_BY_NAME[SlotName.AVAILABILITY].ask
    assert "yes or no" in SLOT_BY_NAME[SlotName.RIGHT_TO_WORK].ask
