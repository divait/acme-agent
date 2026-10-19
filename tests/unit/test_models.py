import json
from pathlib import Path

import pytest

from acme_agent.domain.models import (
    CandidateProfile,
    ConversationRecord,
    Role,
    SlotMeta,
    SlotName,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "record_example.json"

ALWAYS = {
    SlotName.CONSENT_RECORDING,
    SlotName.ROLE,
    SlotName.FULL_NAME,
    SlotName.PHONE,
    SlotName.PREFERRED_STORE_ID,
    SlotName.AVAILABILITY,
    SlotName.WEEKLY_HOURS,
    SlotName.START_DATE,
    SlotName.RIGHT_TO_WORK,
    SlotName.IS_18_OR_OVER,
    SlotName.EXPERIENCE_MONTHS,
}
RIDER = {SlotName.DRIVING_LICENCE, SlotName.OWN_VEHICLE}


def test_fixture_validates_and_round_trips() -> None:
    record = ConversationRecord.model_validate_json(FIXTURE.read_text())
    assert record.schema_version == "1.2"
    assert ConversationRecord.model_validate_json(record.model_dump_json()) == record


def test_schema_1_0_record_still_loads() -> None:
    raw = json.loads(FIXTURE.read_text())
    raw["schema_version"] = "1.0"
    assert ConversationRecord.model_validate(raw).schema_version == "1.0"


def test_dump_matches_fixture_shape() -> None:
    raw = json.loads(FIXTURE.read_text())
    dumped = ConversationRecord.model_validate(raw).model_dump(mode="json")
    assert dumped["candidate"]["start_date"] == "2026-10-26"
    assert dumped["candidate"]["role"] == "delivery_rider"
    assert dumped["end_reason"] == "completed"
    assert dumped["summary"]["headline"] == raw["summary"]["headline"]
    assert dumped["transcript"][1]["speaker"] == "candidate"


def test_minimal_record_defaults() -> None:
    record = ConversationRecord.model_validate(
        {
            "conversation_id": "c_1",
            "started_at": "2026-10-18T10:00:00Z",
            "channel": "text",
            "model": {"live": "l", "text": "t", "prompt_version": "v"},
            "screening": {"status": "needs_human_review"},
        }
    )
    assert record.summary is None
    assert record.metrics == {}
    assert record.previous_conversation_id is None


def test_empty_profile_missing_non_rider_slots() -> None:
    assert set(CandidateProfile().missing_required()) == ALWAYS


@pytest.mark.parametrize("role", [Role.CREW_MEMBER, Role.KITCHEN])
def test_rider_fields_not_required_for_other_roles(role: Role) -> None:
    missing = set(CandidateProfile(role=role).missing_required())
    assert not missing & RIDER
    assert SlotName.ROLE not in missing


def test_rider_fields_required_for_rider() -> None:
    missing = set(CandidateProfile(role=Role.DELIVERY_RIDER).missing_required())
    assert missing >= RIDER


def test_complete_rider_has_nothing_missing() -> None:
    record = ConversationRecord.model_validate_json(FIXTURE.read_text())
    assert record.candidate.missing_required() == []


def test_slot_meta_cross_check_round_trip() -> None:
    meta = SlotMeta(raw="lunes", cross_check=["mon:morning"], cross_check_agrees=False)
    assert SlotMeta.model_validate_json(meta.model_dump_json()) == meta
    assert SlotMeta().cross_check is None
    assert SlotMeta().cross_check_agrees is None
