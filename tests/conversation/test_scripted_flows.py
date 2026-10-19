"""Scripted conversations: replay tool calls against a controller and compare the record.

Each fixture in `fixtures/` holds `calls` (the tool-call script), `language` and the
`expected` final `ConversationRecord` as JSON. Set `UPDATE_FIXTURES=1` to rewrite the
`expected` part after an intentional change, then review the diff by eye.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from acme_agent.domain.models import EndReason, ModelInfo
from acme_agent.domain.validators import ParseContext
from acme_agent.interview.controller import InterviewController

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = [
    "happy_path_rider_es",
    "happy_path_crew_en",
    "multi_field_first_sentence",
    "invalid_phone_twice_then_valid",
    "store_ambiguity_resolved",
    "declined_consent",
]

START = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
MODEL = ModelInfo(live="live-model", text="text-model", prompt_version="test")
MakeCtx = Callable[..., ParseContext]


def replay(ctx: ParseContext, calls: list[list[str]]) -> InterviewController:
    """Run the script. Call shapes: ["record", field, value, said], ["confirm_profile"],
    ["escalate", reason], ["end", reason]."""
    ids = iter(f"ticket-{i}" for i in range(100))
    controller = InterviewController(ctx, lambda: START, lambda: next(ids), lambda _event: None)
    for call in calls:
        tool, args = call[0], call[1:]
        if tool == "record":
            controller.record(*args)
        elif tool == "confirm_profile":
            controller.confirm_profile()
        elif tool == "escalate":
            controller.escalate(*args)
        elif tool == "end":
            controller.end(EndReason(args[0]))
        else:  # pragma: no cover - guards against typos in fixtures
            raise AssertionError(f"unknown tool {tool}")
    return controller


@pytest.mark.parametrize("name", NAMES)
def test_scripted_flow(name: str, make_ctx: MakeCtx) -> None:
    path = FIXTURES / f"{name}.json"
    fixture: dict[str, Any] = json.loads(path.read_text())
    ctx = make_ctx(language=fixture["language"])
    controller = replay(ctx, fixture["calls"])
    record = controller.build_record(f"conv-{name}", START, MODEL, channel="voice").model_dump(
        mode="json"
    )
    if os.environ.get("UPDATE_FIXTURES"):
        fixture["expected"] = record
        path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
    assert record == fixture["expected"]
