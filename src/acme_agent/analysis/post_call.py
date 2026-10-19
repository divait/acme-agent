"""Post-call pipeline: extraction -> reconciliation -> rules -> summary -> metrics -> save.

Implements `SessionFinalizer` (TECHNICAL_DESIGN section 8, ADR-008, ADR-009). Live slots stay
primary: post-call values only fill gaps or raise conflicts, and the screening status always
comes from `domain/rules.py` (ADR-009.1). Logs never carry candidate data.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel

from acme_agent.analysis.reconcile import reconcile
from acme_agent.analysis.schemas import ExtractionResult, Summary
from acme_agent.config import Settings
from acme_agent.domain.models import (
    ConversationRecord,
    EndReason,
    ModelInfo,
    Speaker,
    TranscriptTurn,
)
from acme_agent.interview.controller import InterviewController
from acme_agent.storage.repository import ConversationRepository

log = structlog.get_logger(__name__)

CALL_TIMEOUT_S = 30.0
MAX_RETRIES = 2
RETRY_BASE_DELAY_S = 1.0
EXTRACTION_TEMPERATURE = 0.0
SUMMARY_TEMPERATURE = 0.3

ClientProvider = Callable[[], genai.Client]

EXTRACTION_INSTRUCTION = """\
You extract structured data from a recruiting phone interview transcript for Acme Burgers.
Each line is "[turn N] Speaker: text". Only the Candidate's own statements count; never use
what the agent said as the candidate's answer. Return one item per slot, in the form
{slot, value, said, turn}. Use value=null (and said=null, turn=null) when the candidate did
not clearly state it. Never guess. If the candidate corrected an answer, use the final one.
`said` must be the candidate's exact words from the transcript, `turn` the turn it is in.

Value formats:
- full_name, phone, email, preferred_store_id: the candidate's words, unchanged.
- right_to_work, is_18_or_over, driving_licence, own_vehicle: "yes" or "no".
- role: crew_member | kitchen | delivery_rider.
- availability: comma list of day:shift, days mon..sun, shifts morning|afternoon|night,
  e.g. "mon:morning,sat:night".
- start_date: YYYY-MM-DD (resolve relative dates with today's date).
- weekly_hours, experience_months: an integer.
- languages: comma list of ISO 639-1 codes, e.g. "es,en".
- experience_summary: one short sentence you write, in English.
Do not include consent_recording.
"""

SUMMARY_INSTRUCTION = """\
You write a short, factual summary of a recruiting phone interview for an Acme Burgers
recruiter. Write in English whatever language the interview used. Be neutral: you do not
decide anything about hiring. headline: one line, at most 140 characters. key_points: 3 to 6
short bullets about the candidate. candidate_questions: only the questions listed under
"Unanswered candidate questions" (rephrased briefly), otherwise an empty list.
recruiter_next_steps: concrete follow-ups for the recruiter, based on the status reasons and
those questions.
"""


class PostCallError(Exception):
    """A model call failed after all retries."""

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


def transcript_text(transcript: list[TranscriptTurn]) -> str:
    """Numbered, speaker-labelled transcript for the prompts."""
    return "\n".join(
        f"[turn {t.turn}] {'Candidate' if t.speaker is Speaker.CANDIDATE else 'Agent'}: {t.text}"
        for t in transcript
    )


def _parse[T: BaseModel](response: Any, schema: type[T]) -> T:
    """Structured output only (ADR-008.3): the SDK-parsed object or schema validation."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, schema):
        return parsed
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("empty model response")
    return schema.model_validate_json(text)


class PostCallFinalizer:
    """Finalizes a session: with consent, runs the post-call pipeline; always saves a record."""

    def __init__(
        self,
        genai_client: genai.Client | ClientProvider,
        settings: Settings,
        repository: ConversationRepository,
        *,
        call_timeout: float = CALL_TIMEOUT_S,
        max_retries: int = MAX_RETRIES,
        retry_base_delay: float = RETRY_BASE_DELAY_S,
    ) -> None:
        self._client = genai_client
        self._settings = settings
        self._repository = repository
        self._timeout = call_timeout
        self._max_retries = max_retries
        self._base_delay = retry_base_delay

    async def finalize(
        self,
        controller: InterviewController,
        transcript: list[TranscriptTurn],
        *,
        conversation_id: str,
        started_at: datetime,
        model_info: ModelInfo,
        channel: str,
        metrics: dict[str, Any] | None = None,
    ) -> ConversationRecord:
        def build(extra: dict[str, Any]) -> ConversationRecord:
            return controller.build_record(
                conversation_id,
                started_at,
                model_info,
                channel=channel,
                transcript=transcript,
                metrics={
                    **_derived(controller, transcript, started_at),
                    **(metrics or {}),
                    **extra,
                },
            )

        bound = log.bind(conversation_id=conversation_id)
        consented = (
            controller.profile.consent_recording is True
            and controller.end_reason is not EndReason.DECLINED_CONSENT
        )
        if not consented or not transcript:
            # ADR-009.4: no consent, no analysis (and nothing to analyse without a transcript).
            record = build({"post_call": "skipped"})
            await self._repository.save(record)
            bound.info("post_call_skipped", consented=consented)
            return record

        fills = 0
        conflicts = 0
        failed_step: str | None = None
        summary: Summary | None = None
        try:
            extraction = await self._extract(controller, transcript)
            candidate_turns = {t.turn: t.text for t in transcript if t.speaker is Speaker.CANDIDATE}
            result = reconcile(controller.profile, extraction, controller.ctx, candidate_turns)
            controller.apply_reconciliation(result)
            fills, conflicts = len(result.fills), len(result.conflicts)
            draft = build({})
            summary = await self._summarise(controller, transcript, draft)
        except PostCallError as exc:
            failed_step = exc.step
            controller.note_post_call_failed(exc.step)
            bound.error("post_call_failed", step=exc.step)

        record = build(
            {
                **_aggregate(controller),
                "post_call": "failed" if failed_step else "ok",
                "post_call_fills": fills,
                "post_call_conflicts": conflicts,
            }
        )
        record.summary = summary.to_record() if summary else None
        await self._repository.save(record)
        bound.info(
            "post_call_done",
            status=record.screening.status.value,
            fills=fills,
            conflicts=conflicts,
            summary=record.summary is not None,
        )
        return record

    # -- model calls ----------------------------------------------------------------------

    async def _extract(
        self, controller: InterviewController, transcript: list[TranscriptTurn]
    ) -> ExtractionResult:
        prompt = f"{controller.date_context()}\n\nTranscript:\n{transcript_text(transcript)}"
        return await self._generate(
            "extraction",
            prompt,
            ExtractionResult,
            instruction=EXTRACTION_INSTRUCTION,
            temperature=EXTRACTION_TEMPERATURE,
        )

    async def _summarise(
        self,
        controller: InterviewController,
        transcript: list[TranscriptTurn],
        draft: ConversationRecord,
    ) -> Summary:
        missed = _missed_questions(controller)
        profile = draft.candidate.model_dump_json(exclude_none=True)
        screening = draft.screening
        reasons = ", ".join(screening.rule_ids) or "none"
        conflicts = json.dumps(
            [c.model_dump(mode="json") for c in screening.reconciliation_conflicts]
        )
        questions = "\n".join(f"- {q}" for q in missed) or "(none)"
        prompt = (
            f"Candidate profile (JSON): {profile}\n"
            f"Screening status: {screening.status.value}\n"
            f"Status reasons: {reasons}\n"
            f"Reconciliation conflicts: {conflicts}\n"
            f"Unanswered candidate questions:\n{questions}\n\n"
            f"Transcript:\n{transcript_text(transcript)}"
        )
        summary = await self._generate(
            "summary",
            prompt,
            Summary,
            instruction=SUMMARY_INSTRUCTION,
            temperature=SUMMARY_TEMPERATURE,
        )
        if not missed:
            summary.candidate_questions = []  # never invent questions the candidate did not ask
        return summary

    async def _generate[T: BaseModel](
        self,
        step: str,
        prompt: str,
        schema: type[T],
        *,
        instruction: str,
        temperature: float,
    ) -> T:
        client = self._client() if callable(self._client) else self._client
        config = types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
        )

        async def call() -> T:
            async with asyncio.timeout(self._timeout):
                response = await client.aio.models.generate_content(
                    model=self._settings.text_model, contents=prompt, config=config
                )
            return _parse(response, schema)

        return await self._with_retries(step, call)

    async def _with_retries[T](self, step: str, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(self._max_retries + 1):
            try:
                return await call()
            except Exception as exc:  # network, timeout, quota or invalid structured output
                log.warning(
                    "post_call_attempt_failed",
                    step=step,
                    attempt=attempt + 1,
                    error=type(exc).__name__,
                )
                if attempt == self._max_retries:
                    raise PostCallError(step) from exc
                await asyncio.sleep(self._base_delay * 2**attempt)
        raise PostCallError(step)  # unreachable: the loop returns or raises


def _missed_questions(controller: InterviewController) -> list[str]:
    seen: dict[str, None] = {}
    for event in controller.events:
        question = event.payload.get("question")
        if event.type == "faq_missed" and isinstance(question, str) and question.strip():
            seen.setdefault(question.strip())
    return list(seen)


def _derived(
    controller: InterviewController, transcript: list[TranscriptTurn], started_at: datetime
) -> dict[str, Any]:
    """Defaults for metrics a channel did not supply: duration and turn counts."""
    ended = controller.ended_at
    out: dict[str, Any] = {
        "candidate_turns": sum(1 for t in transcript if t.speaker is Speaker.CANDIDATE),
        "agent_turns": sum(1 for t in transcript if t.speaker is Speaker.AGENT),
        "validation_errors": sum(1 for e in controller.events if e.type == "validation_failed"),
    }
    if ended is not None:
        out["duration_s"] = round(max((ended - started_at).total_seconds(), 0.0), 3)
    return out


def _aggregate(controller: InterviewController) -> dict[str, Any]:
    """Counters derived from the controller's events (invalid attempts per slot, FAQ)."""
    invalid: Counter[str] = Counter()
    hits = misses = 0
    for event in controller.events:
        if event.type == "validation_failed":
            invalid[str(event.payload.get("field"))] += 1
        elif event.type == "faq_answered":
            hits += 1
        elif event.type == "faq_missed":
            misses += 1
    return {"invalid_attempts": dict(invalid), "faq_hits": hits, "faq_misses": misses}
