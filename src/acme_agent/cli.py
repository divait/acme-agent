"""Command-line entry point."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import statistics
from collections import Counter
from typing import Annotated, Any, Literal

import structlog
import typer
from pydantic import ValidationError

from acme_agent import __version__
from acme_agent.agent.text import TextInterview
from acme_agent.bootstrap import build_container
from acme_agent.config import get_settings
from acme_agent.domain.models import (
    ALWAYS_REQUIRED,
    RIDER_REQUIRED,
    ConversationRecord,
    EndReason,
)
from acme_agent.logging import configure_logging
from acme_agent.storage.json_repo import (
    make_repository,
    validate_conversation_id,
)
from acme_agent.storage.repository import (
    ConversationRepository,
    CorruptRecordError,
    InvalidConversationIdError,
)

app = typer.Typer(help="Voice recruiting-interview agent.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Voice recruiting-interview agent."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def _repo() -> ConversationRepository:
    try:
        return make_repository(get_settings())
    except NotImplementedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("list")
def list_conversations(
    limit: int | None = typer.Option(None, "--limit", "-n", min=1, help="Max rows."),
) -> None:
    """List stored conversations, newest first."""
    rows = asyncio.run(_repo().list(limit))
    if not rows:
        typer.echo("No conversations found.")
        return
    typer.echo(f"{'ID':<30} {'STARTED':<12} {'ROLE':<16} {'STATUS':<22} END REASON")
    for r in rows:
        typer.echo(
            f"{r.conversation_id:<30} {r.started_at.date().isoformat():<12} "
            f"{(r.role.value if r.role else '-'):<16} {r.status.value:<22} "
            f"{r.end_reason.value if r.end_reason else '-'}"
        )


@app.command()
def show(
    conversation_id: str = typer.Argument(..., help="Conversation id."),
    summary: bool = typer.Option(False, "--summary", help="Short human-readable view."),
) -> None:
    """Show one conversation record."""
    try:
        validate_conversation_id(conversation_id)
    except InvalidConversationIdError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    try:
        record = asyncio.run(_repo().get(conversation_id))
    except CorruptRecordError as exc:
        typer.echo(f"Conversation {conversation_id} is unreadable (corrupted file)", err=True)
        raise typer.Exit(3) from exc
    if record is None:
        typer.echo(f"Conversation not found: {conversation_id}", err=True)
        raise typer.Exit(1)
    if not summary:
        typer.echo(record.model_dump_json(indent=2))
        return
    c = record.candidate
    typer.echo(f"Conversation: {record.conversation_id}")
    typer.echo(f"Started:      {record.started_at.isoformat()}")
    typer.echo(f"End reason:   {record.end_reason.value if record.end_reason else '-'}")
    typer.echo(f"Role:         {c.role.value if c.role else '-'}")
    typer.echo(f"Status:       {record.screening.status.value}")
    if record.summary:
        typer.echo(f"Headline:     {record.summary.headline}")
        for point in record.summary.key_points:
            typer.echo(f"  - {point}")


def compute_stats(records: list[ConversationRecord], unreadable: int = 0) -> dict[str, Any]:
    """Aggregate stored records (pure; the command feeds it through the repository)."""
    total = len(records)
    completed = sum(1 for r in records if r.end_reason is EndReason.COMPLETED)
    durations: list[float] = []
    for r in records:
        value = r.metrics.get("duration_s")
        if isinstance(value, int | float) and not isinstance(value, bool):
            durations.append(float(value))
        elif r.ended_at is not None:
            durations.append((r.ended_at - r.started_at).total_seconds())
    failed: Counter[str] = Counter()
    for r in records:
        attempts = r.metrics.get("invalid_attempts")
        if isinstance(attempts, dict):
            for slot, count in attempts.items():
                if isinstance(count, int) and count > 0:
                    failed[str(slot)] += count
    with_post_call = [r for r in records if "post_call_fills" in r.metrics]
    filled_by_post_call = sum(1 for r in with_post_call if (r.metrics["post_call_fills"] or 0) > 0)
    return {
        "count": total,
        "unreadable": unreadable,
        "completion_rate": completed / total if total else None,
        "status_distribution": dict(Counter(r.screening.status.value for r in records)),
        "median_duration_s": statistics.median(durations) if durations else None,
        "most_failed_slots": [
            {"slot": slot, "invalid_attempts": n} for slot, n in failed.most_common(5)
        ],
        "post_call_fill_rate": (
            filled_by_post_call / len(with_post_call) if with_post_call else None
        ),
    }


async def _load_all(repo: ConversationRepository) -> tuple[list[ConversationRecord], int]:
    records: list[ConversationRecord] = []
    unreadable = 0
    for row in await repo.list():
        try:
            record = await repo.get(row.conversation_id)
        except CorruptRecordError:
            unreadable += 1
            continue
        if record is not None:
            records.append(record)
    return records, unreadable


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


@app.command()
def stats(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Aggregate stored conversations.

    Reports count, completion rate (end reason completed), status distribution, median
    duration, most-failed slots (summed invalid_attempts) and the post-call fill rate: the
    share of records that went through post-call and had at least one field filled by it
    (metrics.post_call_fills > 0).
    """
    records, unreadable = asyncio.run(_load_all(_repo()))
    result = compute_stats(records, unreadable)
    if as_json:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Conversations:     {result['count']}")
    typer.echo(f"Completion rate:   {_pct(result['completion_rate'])}")
    median = result["median_duration_s"]
    typer.echo(f"Median duration:   {'-' if median is None else f'{median:.0f}s'}")
    typer.echo(f"Post-call fill:    {_pct(result['post_call_fill_rate'])}")
    typer.echo("Status:")
    for status, n in sorted(result["status_distribution"].items()):
        typer.echo(f"  {status:<22} {n}")
    typer.echo("Most failed slots:")
    for item in result["most_failed_slots"] or []:
        typer.echo(f"  {item['slot']:<22} {item['invalid_attempts']}")
    if unreadable:
        typer.echo(f"Unreadable records skipped: {unreadable}", err=True)


@app.command()
def purge(
    older_than: int | None = typer.Option(
        None, "--older-than", min=0, help="Days; defaults to ACME_RETENTION_DAYS."
    ),
    yes: bool = typer.Option(False, "--yes", help="Actually delete (otherwise dry run)."),
) -> None:
    """Delete conversations older than the retention period."""
    settings = get_settings()
    days = settings.retention_days if older_than is None else older_than
    if not yes:
        repo = _repo()
        old = asyncio.run(repo.purge_candidates(days))
        typer.echo(f"Would delete {len(old)} conversation(s) older than {days} days:")
        for r in old:
            typer.echo(f"  {r.conversation_id}  {r.timestamp.date().isoformat()}")
        typer.echo("Re-run with --yes to delete.")
        return
    deleted = asyncio.run(_repo().purge_older_than(days))
    typer.echo(f"Deleted {deleted} conversation(s) older than {days} days.")


_MARKS = {"filled": "✓", "invalid": "?", "unresolved": "?"}
_PROMPTS = {"es": "Tú: ", "en": "You: "}
_MODEL_ERROR = (
    "Could not talk to the model ({error}). Check your credentials: run "
    "`gcloud auth application-default login` and set GOOGLE_CLOUD_PROJECT."
)
_NO_PROJECT = (
    "GOOGLE_CLOUD_PROJECT is not set. Copy .env.example to .env and set it, then run "
    "`gcloud auth application-default login`."
)
_NOISY_LOGGERS = ("google_adk", "google.adk", "google_genai", "httpx")


_SHORT_LABELS = {
    "consent_recording": "consent",
    "full_name": "name",
    "preferred_store_id": "store",
    "availability": "avail",
    "weekly_hours": "hours",
    "start_date": "start",
    "right_to_work": "rtw",
    "is_18_or_over": "18+",
    "driving_licence": "licence",
    "own_vehicle": "vehicle",
    "experience_months": "exp",
    "experience_summary": "summary",
}  # display only


def progress_line(snapshot: dict[str, Any]) -> str:
    """Compact progress, e.g. `[6/14 slots] phone ✓ store ? hours ·` (required active only)."""
    required = {s.value for s in (*ALWAYS_REQUIRED, *RIDER_REQUIRED)}
    slots = {
        name: info
        for name, info in snapshot["slots"].items()
        if name in required and info["status"] != "not_applicable"
    }
    filled = sum(1 for info in slots.values() if info["status"] == "filled")
    parts = " ".join(
        f"{_SHORT_LABELS.get(name, name)} {_MARKS.get(info['status'], '·')}"
        for name, info in slots.items()
    )
    return f"[{filled}/{len(slots)} slots] {parts}"


def _make_interview(language: Literal["es", "en"]) -> TextInterview:
    return TextInterview(build_container(get_settings()), language=language)


async def _chat(interview: TextInterview, language: Literal["es", "en"]) -> ConversationRecord:
    prompt = _PROMPTS[language]
    warmup = interview.start_faq_warmup()  # first FAQ question must not pay the cold build
    try:
        typer.echo(f"Ana: {await interview.start()}")
        typer.echo(progress_line(interview.controller.snapshot()))
        while not interview.is_over:
            try:
                line = await asyncio.to_thread(input, prompt)
            except (EOFError, KeyboardInterrupt):
                break
            if not line.strip():
                continue
            if line.strip() == "/quit":
                break
            typer.echo(f"Ana: {await interview.send(line)}")
            typer.echo(progress_line(interview.controller.snapshot()))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        raise _ChatFailed(await _save_abandoned(interview)) from exc
    finally:
        if warmup is not None:
            warmup.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await warmup
    return await interview.close(EndReason.ABANDONED)


class _ChatFailed(Exception):
    """A model error mid-interview; carries the abandoned record when the save worked."""

    def __init__(self, record: ConversationRecord | None) -> None:
        super().__init__("chat failed")
        self.record = record


async def _save_abandoned(interview: TextInterview) -> ConversationRecord | None:
    try:
        return await interview.close(EndReason.ABANDONED)
    except Exception as exc:
        structlog.get_logger().warning("abandoned_save_failed", error_type=type(exc).__name__)
        return None


def _quiet_third_party_loggers() -> None:
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.CRITICAL)


def _fail_model(exc: BaseException) -> typer.Exit:
    cause = exc.__cause__ if isinstance(exc, _ChatFailed) and exc.__cause__ else exc
    typer.echo(
        _MODEL_ERROR.format(
            error=str(cause).splitlines()[0][:200] if str(cause) else type(cause).__name__
        ),
        err=True,
    )
    return typer.Exit(1)


@app.command()
def chat(
    lang: Annotated[str, typer.Option("--lang", help="Interview language: es or en.")] = "es",
) -> None:
    """Run an interview by typing, with a real text model."""
    if lang not in ("es", "en"):
        typer.echo("--lang must be 'es' or 'en'.", err=True)
        raise typer.Exit(2)
    language: Literal["es", "en"] = "es" if lang == "es" else "en"
    _quiet_third_party_loggers()
    try:
        settings = get_settings()
    except ValidationError as exc:
        first = str(exc).splitlines()[0]
        typer.echo(f"Invalid configuration: {first}", err=True)
        raise typer.Exit(1) from exc
    configure_logging(settings.log_level)
    if not settings.google_cloud_project:
        typer.echo(_NO_PROJECT, err=True)
        raise typer.Exit(1)
    try:
        interview = _make_interview(language)
        record = asyncio.run(_chat(interview, language))
    except typer.Exit:
        raise
    except _ChatFailed as failed:
        if failed.record is not None:
            typer.echo(f"Saved:     {failed.record.conversation_id}", err=True)
        raise _fail_model(failed) from failed
    except Exception as exc:
        raise _fail_model(exc) from exc
    typer.echo(f"Record:    {record.conversation_id}")
    typer.echo(f"End:       {record.end_reason.value if record.end_reason else '-'}")
    typer.echo(f"Screening: {record.screening.status.value}")


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port.")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload (development).")] = False,
) -> None:
    """Start the web gateway (voice interviews over WebSocket)."""
    import uvicorn

    try:
        settings = get_settings()
    except ValidationError as exc:
        typer.echo(f"Invalid configuration: {str(exc).splitlines()[0]}", err=True)
        raise typer.Exit(1) from exc
    configure_logging(settings.log_level)
    uvicorn.run(
        "acme_agent.web.main:create_default_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_config=None,  # logging is configured by configure_logging (masked JSON)
    )
