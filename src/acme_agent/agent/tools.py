"""The five model-facing tools, as thin adapters over the controller (ADR-003, ADR-016).

Docstrings are the tool descriptions the model sees, so they are written as instructions.
Parameters stay plain `str` so ADK can build declarations from type hints.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from acme_agent.domain.models import EndReason
from acme_agent.interview.closing import closing_line
from acme_agent.interview.controller import InterviewController
from acme_agent.knowledge.retriever import Retriever

_END_REASONS = [r.value for r in EndReason]


def build_tools(controller: InterviewController, retriever: Retriever) -> list[Callable[..., Any]]:
    """Tools bound to one controller; no module-level state."""

    def record_field(field: str, value: str, said: str) -> dict[str, Any]:
        """Save one piece of information the candidate just gave.
        Call it every time the candidate states a value, even if they gave several at once
        (call once per field). `said` is always the candidate's own words.
        `value` depends on the field:
          - full_name, phone, email, preferred_store_id: the candidate's words, unchanged.
          - consent_recording, right_to_work, is_18_or_over, driving_licence, own_vehicle:
            "yes" or "no". For consent_recording record "yes" only for a clear, unconditional
            yes. For a mixed or conditional answer ("no... but fine", "I suppose") do not
            record anything: ask "¿Das tu consentimiento para grabar y procesar esta
            entrevista? Sí o no." (in their language) and record the answer.
          - role: crew_member | kitchen | delivery_rider.
          - availability: comma list of day:shift, days mon..sun, shifts
            morning|afternoon|night (e.g. "mon:morning,tue:morning,sat:night").
          - start_date: YYYY-MM-DD (resolve "next Monday" etc. using today's date).
          - weekly_hours, experience_months: an integer.
          - languages: ISO codes, e.g. "es,en".
          - experience_summary: one short sentence you write.
        The valid field names are the ones listed above (`missing` only lists what is still
        required). Follow `next_goal` in the response.
        If status is "invalid", re-ask using `hint`."""
        return controller.record(field, value, said).to_json()

    async def search_faq(question: str, language: str) -> dict[str, Any]:
        """Look up Acme Burgers job information (pay, shifts, stores, uniforms, process)
        when the candidate asks a question. `language` is "es" or "en". Only answer from
        the returned text. If found is false, say a recruiter will follow up."""
        result = await retriever.search(question, language)
        source = result.answers[0].source if result.found and result.answers else None
        controller.note_faq(question, result.found, source)
        dumped: dict[str, Any] = result.model_dump(mode="json")
        goal = controller.next_goal()
        dumped["next_goal"] = goal
        dumped["then"] = (
            f"Answer in one or two short sentences, then ask the pending question again: {goal}"
        )
        return dumped

    def confirm_profile() -> dict[str, Any]:
        """Call when next_goal says all information is collected. Returns a summary to read
        back to the candidate for confirmation, plus `say`: an English line with the details
        to translate into the candidate's language and read back in the same reply."""
        return dict(controller.confirm_profile())

    def escalate_to_human(reason: str) -> dict[str, Any]:
        """Call only after the candidate explicitly accepts the recruiter offer or explicitly
        asks for a person; never merely because they are upset. After it, say goodbye and call
        end_interview with reason escalated. reason: candidate_request | frustration |
        technical_issue | other."""
        # ticket_id is None when the interview had already ended: passed through as null.
        return dict(controller.escalate(reason))

    def end_interview(reason: str) -> dict[str, Any]:
        """Call to end the interview. reason: completed | declined_consent | escalated |
        abandoned. Say the goodbye from `say` in the candidate's language in this same reply."""
        try:
            end_reason = EndReason(reason)
        except ValueError:
            return {"error": f"Unknown reason '{reason}'.", "allowed": _END_REASONS}
        controller.end(end_reason)
        return {
            "status": "ended",
            "reason": end_reason.value,
            "say": closing_line(end_reason, controller.has_phone, controller.consented),
        }

    return [record_field, search_faq, confirm_profile, escalate_to_human, end_interview]
