from __future__ import annotations

import json

import pytest

from acme_agent.web.protocol import (
    TEXT_MAX_BYTES,
    CompletedMessage,
    EndMessage,
    ErrorMessage,
    PingMessage,
    ProtocolError,
    SlotMessage,
    StartMessage,
    TextMessage,
    TranscriptMessage,
    dump_server_message,
    parse_client_message,
)


def test_parses_each_client_message() -> None:
    assert parse_client_message('{"type":"start","locale":"en-GB"}') == StartMessage(locale="en-GB")
    assert parse_client_message('{"type":"start"}') == StartMessage()
    assert parse_client_message('{"type":"text","text":"hola"}') == TextMessage(text="hola")
    assert isinstance(parse_client_message('{"type":"end"}'), EndMessage)
    assert isinstance(parse_client_message('{"type":"ping"}'), PingMessage)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("not json", "malformed"),
        ("[1, 2]", "malformed"),
        ('"ping"', "malformed"),
        ('{"type":"nope"}', "unknown_type"),
        ('{"no_type":1}', "unknown_type"),
        ('{"type":"pong"}', "unknown_type"),
        ('{"type":"text"}', "invalid"),
        ('{"type":"text","text":""}', "invalid"),
        ('{"type":"text","text":5}', "invalid"),
        ('{"type":"ping","extra":1}', "invalid"),
    ],
)
def test_rejects_bad_frames(raw: str, code: str) -> None:
    result = parse_client_message(raw)
    assert isinstance(result, ProtocolError)
    assert result.code == code


def test_rejects_oversized_text_frame() -> None:
    raw = json.dumps({"type": "text", "text": "x" * TEXT_MAX_BYTES})
    result = parse_client_message(raw)
    assert isinstance(result, ProtocolError)
    assert result.code == "too_large"


def test_size_limit_counts_bytes_not_characters() -> None:
    raw = json.dumps({"type": "text", "text": "ñ" * (TEXT_MAX_BYTES // 2)}, ensure_ascii=False)
    assert isinstance(parse_client_message(raw), ProtocolError)


def test_server_messages_serialise_with_type() -> None:
    out = json.loads(
        dump_server_message(TranscriptMessage(speaker="agent", text="Hola", final=False, turn=2))
    )
    assert out == {
        "type": "transcript",
        "speaker": "agent",
        "text": "Hola",
        "final": False,
        "turn": 2,
    }
    slot = json.loads(
        dump_server_message(SlotMessage(name="phone", status="filled", value="+34", progress=0.5))
    )
    assert slot["type"] == "slot"
    assert json.loads(dump_server_message(ErrorMessage(code="x", message="y")))["code"] == "x"
    done = json.loads(dump_server_message(CompletedMessage(status="meets_requirements")))
    assert done == {
        "type": "completed",
        "summary": None,
        "status": "meets_requirements",
        "reasons": [],
        "end_reason": None,
        "sentiment": None,
        "profile": None,
        "complete": False,
    }


def test_slot_display_optional() -> None:
    plain = json.loads(
        dump_server_message(SlotMessage(name="phone", status="filled", progress=0.1))
    )
    assert plain["display"] is None
    shown = json.loads(
        dump_server_message(
            SlotMessage(
                name="preferred_store_id",
                status="filled",
                value="mad-sol",
                display="Acme Burgers Sol",
                progress=0.5,
            )
        )
    )
    assert shown["display"] == "Acme Burgers Sol"


def test_slot_progress_bounded() -> None:
    with pytest.raises(ValueError):
        SlotMessage(name="phone", status="filled", progress=1.5)
