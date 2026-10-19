from __future__ import annotations

import json

import pytest
import structlog

from acme_agent.logging import bind_conversation, configure_logging, mask_pii


def _mask(**kw: object) -> dict[str, object]:
    return dict(mask_pii(None, "info", dict(kw)))


def test_phone_masked() -> None:
    assert _mask(event="call from +34600123456")["event"] == "call from +34******456"


def test_email_masked() -> None:
    assert _mask(email="laura@example.com")["email"] == "l***@example.com"


def test_name_keys_masked_including_nested() -> None:
    out = _mask(full_name="Laura Gil", name="Laura", data={"name": "Bob", "city": "Madrid"})
    assert out["full_name"] == "***"
    assert out["name"] == "***"
    assert out["data"] == {"name": "***", "city": "Madrid"}


def test_plain_values_untouched() -> None:
    out = _mask(event="slot filled", count=3, year="2024")
    assert out == {"event": "slot filled", "count": 3, "year": "2024"}


def test_json_output_with_conversation_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.contextvars.clear_contextvars()
    bind_conversation("conv-1")
    structlog.get_logger().info("hello", phone="+34600123456", full_name="Laura Gil")
    structlog.contextvars.clear_contextvars()
    record = json.loads(capsys.readouterr().out)
    assert record["conversation_id"] == "conv-1"
    assert record["phone"] == "+34******456"
    assert record["full_name"] == "***"
    assert record["level"] == "info"


def test_exception_text_and_stack_info_masked(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.contextvars.clear_contextvars()
    log = structlog.get_logger()
    try:
        raise ValueError("bad phone +34600123456 for laura@example.com")
    except ValueError:
        log.exception("failed", stack_info=True)
    out = capsys.readouterr().out
    record = json.loads(out)
    assert "+34******456" in record["exception"]
    assert "l***@example.com" in record["exception"]
    assert "+34600123456" not in out
    assert "laura@example.com" not in out


def test_stdlib_logger_line_is_masked(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    configure_logging("INFO")
    logging.getLogger("google_genai").info("sent to +34600123456 (laura@example.com)")
    out = capsys.readouterr().out
    record = json.loads(out)
    assert "+34******456" in record["event"]
    assert "l***@example.com" in record["event"]
    assert "+34600123456" not in out


def test_uvicorn_access_log_has_no_query_string(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    configure_logging("INFO")
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/x?phone=600123456", "1.1", 200
    )
    out = capsys.readouterr().out
    assert "/x" in out
    assert "phone=" not in out
    assert "600123456" not in out


def test_route_stdlib_can_be_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    configure_logging("INFO", route_stdlib=False)
    assert structlog.get_logger() is not None
    capsys.readouterr()
    assert logging.getLogger().level >= 0


def test_third_party_loggers_never_below_info_at_debug() -> None:
    import logging as std

    configure_logging("DEBUG")
    try:
        for name in ("google_adk", "google_genai", "httpx"):
            assert std.getLogger(name).getEffectiveLevel() >= std.INFO
    finally:
        configure_logging("INFO")
