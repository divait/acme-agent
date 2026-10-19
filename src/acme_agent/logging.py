"""Structured JSON logging with PII masking."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

# Deliberately over-masks long digit runs (safe direction).
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_NAME_KEYS = frozenset({"full_name", "name"})
_MASK = "***"


def _mask_phone(match: re.Match[str]) -> str:
    raw = match.group(0)
    compact = re.sub(r"[\s().-]", "", raw)
    if len(compact) < 9:
        return raw
    plus = "+" if compact.startswith("+") else ""
    digits = compact.lstrip("+")
    head = 2 if plus else 0
    return f"{plus}{digits[:head]}{'*' * (len(digits) - head - 3)}{digits[-3:]}"


def _mask_text(value: str) -> str:
    value = _EMAIL_RE.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", value)
    return _PHONE_RE.sub(_mask_phone, value)


def _mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return _mask_text(value)
    if isinstance(value, dict):
        return {k: _mask_pair(k, v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_mask_value(v) for v in value)
    return value


def _mask_pair(key: Any, value: Any) -> Any:
    if isinstance(key, str) and key in _NAME_KEYS and value is not None:
        return _MASK
    return _mask_value(value)


def mask_pii(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor masking phones, emails and name fields."""
    for key in list(event_dict):
        event_dict[key] = _mask_pair(key, event_dict[key])
    return event_dict


_THIRD_PARTY_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "google_adk",
    "google.adk",
    "google_genai",
    "httpx",
)
_QUIET_LOGGERS = ("google_adk", "google.adk", "google_genai", "httpx")
_HANDLER_MARK = "_acme_structlog_handler"


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to whatever `sys.stdout` is at emit time (survives stream swaps)."""

    def __init__(self) -> None:
        super().__init__()
        setattr(self, _HANDLER_MARK, True)

    @property
    def stream(self) -> Any:
        return sys.stdout

    @stream.setter
    def stream(self, value: Any) -> None:
        pass


class _StripQueryFilter(logging.Filter):
    """uvicorn.access: drop query strings from the logged path (they may carry PII)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (args[0], args[1], args[2].split("?", 1)[0], *args[3:])
        return True


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def _route_stdlib(numeric: int) -> None:
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            mask_pii,  # after exception rendering (ADR-014.4)
            structlog.processors.JSONRenderer(),
        ],
    )
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, _HANDLER_MARK, False)]
    handler = _StdoutHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(numeric)
    for name in _THIRD_PARTY_LOGGERS:
        third = logging.getLogger(name)
        third.handlers = []  # uvicorn installs its own; ours (on root) must be the only sink
        third.propagate = True
    if numeric < logging.INFO:
        for name in _QUIET_LOGGERS:  # their DEBUG lines carry request bodies (PII)
            logging.getLogger(name).setLevel(logging.INFO)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _StripQueryFilter) for f in access.filters):
        access.addFilter(_StripQueryFilter())


def configure_logging(level: str = "INFO", *, route_stdlib: bool = True) -> None:
    """Configure structlog to emit JSON lines with PII masked.

    With `route_stdlib`, stdlib loggers (uvicorn, google_adk, google_genai, httpx) are
    formatted by the same pipeline so third-party lines are masked too.
    """
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            *_shared_processors(),
            mask_pii,  # must run after exception/stack rendering (ADR-014.4)
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    if route_stdlib:
        _route_stdlib(numeric)


def bind_conversation(conversation_id: str) -> None:
    """Bind `conversation_id` to every subsequent log line in this context."""
    structlog.contextvars.bind_contextvars(conversation_id=conversation_id)
