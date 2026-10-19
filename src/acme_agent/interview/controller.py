"""Deterministic interview controller (ADR-016, ADR-015).

Synchronous and free of I/O: the clock, id generator and `emit` callback are injected.
Only the methods of `InterviewController` change slot state (ADR-016.2).
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from acme_agent.domain import rules
from acme_agent.domain.models import (
    Availability,
    CandidateProfile,
    ConversationRecord,
    EndReason,
    Event,
    LanguageInfo,
    ModelInfo,
    ReconciliationConflict,
    Role,
    SlotMeta,
    SlotName,
    TranscriptTurn,
)
from acme_agent.domain.sentiment import aggregate
from acme_agent.domain.validators import CANONICAL, CROSS_CHECKS, VERBATIM, Issue, ParseContext
from acme_agent.interview.events import Emit, EscalationReason, EventType, Status, ToolResult
from acme_agent.interview.evidence import RECENT_TURNS, said_in_transcript
from acme_agent.interview.readback import READBACK, normalise_text, role_mentioned
from acme_agent.interview.slots import RIDER_ONLY, SLOT_BY_NAME, SLOTS, SlotSpec

MAX_ATTEMPTS = 3

_COUNTRIES: dict[str, Literal["ES", "MX"]] = {"ES": "ES", "MX": "MX"}
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

CLOSE_DECLINED = (
    "The candidate did not consent. Thank them politely, say goodbye, then call "
    "end_interview with reason declined_consent."
)
CONFIRM_DECLINE_GOAL = (
    "The candidate said no to consent. Explain kindly that without their consent the "
    "interview cannot continue, and ask whether they want to end the call. "
    "Finish with this direct question: "
    '"¿Das tu consentimiento para grabar y procesar esta entrevista? Sí o no." (in the '
    "candidate's language)."
)
CONFIRM_GOAL = "Call confirm_profile."
CLOSE_GOAL = (
    "Thank the candidate, tell them you now have all the information you need and that the "
    "Acme Burgers hiring team will review it and be in touch soon, then call end_interview."
)
ENDED_GOAL = "The interview has ended. Do not ask anything else."
ENDED_HINT = "The interview has ended."
NO_CONSENT_HINT = "Consent has not been given yet; do not collect data."
DECLINED_HINT = "Consent was declined; do not collect data."
_PER_FIELD_EVENTS = (
    "slot_filled",
    "field_corrected",
    "validation_failed",
    "slot_unresolved",
)
_KEPT_AFTER_DECLINE = ("phase_changed", "interview_ended", "escalated")
ESCALATED_GOAL = (
    "The candidate has been handed to a recruiter. Say goodbye politely and, in this same "
    "turn, call end_interview with reason escalated: the interview is not finished until you do."
)
ESCALATED_ASK_PHONE_GOAL = (
    "Before ending, ask for a phone number so the recruiter can phone them back; record it "
    "with record_field(phone, ...). If they don't want to give it, tell them they can "
    "contact the hiring team (see the contact-recruiter FAQ) and say goodbye."
)
ESCALATED_NO_CONSENT_GOAL = (
    "The candidate asked for a person before giving consent, so do not collect any data "
    "and do not promise a callback. Call search_faq('contact a recruiter') and tell them "
    "how they can contact the hiring team, say goodbye, then call end_interview with "
    "reason escalated."
)
FRUSTRATION_NOTE = (
    "[SYSTEM NOTE] The candidate seems frustrated. Offer a recruiter callback or to continue later."
)
HUMAN_REQUEST_NOTE = (
    "[SYSTEM NOTE] The candidate asked to speak with a person. Offer a recruiter callback; "
    "call escalate_to_human only if they accept."
)
FRUSTRATION_WINDOW = 4
FRUSTRATION_THRESHOLD = 2

# Human-request detection on normalised text (lowercase, no accents, no punctuation, ES/EN):
# a request phrase followed within a few words by a person noun, or a fixed phrase.
_REQUEST_PHRASE = (
    r"(?:talk to|talk with|speak to|speak with|hablar con|pasame con|pasarme con|ponme con"
    r"|put me through to|connect me (?:to|with)|transfer me to)"
)
_PERSON_NOUN = (
    r"(?:person|human|someone|somebody|recruiter|persona|alguien|humano|reclutador|reclutadora)"
)
_HUMAN_REQUEST_RE = re.compile(
    rf"\b{_REQUEST_PHRASE}(?: \w+){{0,3}} {_PERSON_NOUN}\b"
    r"|\buna persona real\b|\ba real person\b|\ba human please\b"
)


@dataclass(frozen=True)
class Fill:
    """A validated post-call value for a slot that the live interview left empty."""

    slot: SlotName
    value: object  # already normalised by the CANONICAL / VERBATIM validator
    said: str | None = None


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of post-call reconciliation, applied only via `apply_reconciliation`."""

    fills: Sequence[Fill] = ()
    conflicts: Sequence[ReconciliationConflict] = ()


class Phase(StrEnum):
    GREETING = "greeting"
    CONSENT = "consent"
    COLLECTING = "collecting"
    CONFIRMATION = "confirmation"
    CLOSING = "closing"
    ENDED = "ended"


def _same(a: object, b: object) -> bool:
    """Equality where lists (languages, availability) are compared as sets."""
    if isinstance(a, list) and isinstance(b, list):
        return set(a) == set(b)  # elements are hashable: strings, frozen Availability
    return a == b


def _as_canonical(value: object) -> str:
    """Typed slot value -> the canonical string the ADR-015 validators accept."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Role):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return ",".join(
            f"{v.day.value}:{v.shift.value}" if isinstance(v, Availability) else str(v)
            for v in value
        )
    return str(value)


def _empty_value(name: SlotName) -> object:
    return [] if name in (SlotName.AVAILABILITY, SlotName.LANGUAGES) else None


class InterviewController:
    """Owns the candidate profile, slot metadata, phase and event log of one interview.

    Only mutating methods change state or phase: `start()` (greeting -> consent, returns the
    first goal), `record`, `prefill`, `confirm_profile`, `escalate` and `end`. `next_goal()`
    is a pure read: calling it any number of times changes neither `phase` nor `events`.
    Consent comes first (ADR-009.4): until it is given, or once it is refused, `record`
    stores nothing for any other field.
    """

    def __init__(
        self,
        ctx: ParseContext,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
        emit: Emit,
        timezone: str = "Europe/Madrid",
        on_said_unverified: Callable[[str], None] | None = None,
    ) -> None:
        self.ctx = ctx
        self._clock = clock
        self._id_factory = id_factory
        self._emit = emit
        self._on_said_unverified = on_said_unverified or (lambda field: None)
        self.timezone = timezone
        self.phase = Phase.GREETING
        self.profile = CandidateProfile()
        self.slot_meta: dict[SlotName, SlotMeta] = {}
        self.events: list[Event] = []
        self._failures: dict[SlotName, int] = {}
        self._hints: dict[SlotName, str] = {}
        self.language: str = ctx.language  # interview language marker for read-backs
        self.escalated = False
        self.end_reason: EndReason | None = None
        self.ended_at: datetime | None = None
        self._confirmed = False
        self._decline_pending = False  # a first "no" to consent awaits confirmation
        self._readback_pending = False
        self._frustration: deque[bool] = deque(maxlen=FRUSTRATION_WINDOW)
        self._frustration_events = 0  # flagged turns, for the record's sentiment aggregate
        self._frustration_noted = False
        self._recruiter_offered = False  # a frustration / human-request note was sent
        self._ticket_id: str | None = None
        self._recent_candidate: deque[str] = deque(maxlen=RECENT_TURNS)
        self.said_unverified: list[str] = []  # advisory: verbatim slots whose `said` is unheard
        self.reconciliation_conflicts: list[ReconciliationConflict] = []
        self.post_call_failed = False

    # -- public API ----------------------------------------------------------------------

    @property
    def readback_pending(self) -> bool:
        """True from confirm_profile until the details are read back, corrected or dropped."""
        return self._readback_pending

    def drop_readback(self) -> None:
        """Stop waiting for a read-back (the caller gave up after its one re-prompt)."""
        self._readback_pending = False

    def date_context(self) -> str:
        """Session-start note with today's date, weekday and timezone (ADR-015.6)."""
        now = self._clock().astimezone(ZoneInfo(self.timezone))
        return (
            f"[SYSTEM NOTE] Today is {now.date().isoformat()} ({_WEEKDAYS[now.weekday()]}), "
            f"timezone {self.timezone}. Use it to resolve relative dates such as "
            "'next Monday' into YYYY-MM-DD."
        )

    def start(self) -> str:
        """Begin the interview: greeting -> consent; returns the first goal."""
        if self.phase is Phase.GREETING:
            self._set_phase(Phase.CONSENT)
        return self.next_goal()

    def record(self, field: str, value: str, said: str = "") -> ToolResult:
        """Validate and store one slot value (TECHNICAL_DESIGN 5.4, ADR-015)."""
        try:
            name = SlotName(field)
        except ValueError:
            allowed = ", ".join(s.name.value for s in SLOTS)
            return self._result("unknown_field", field, hint=f"Unknown field. Allowed: {allowed}.")
        if self.phase is Phase.ENDED:
            return self._result("not_applicable", field, hint=ENDED_HINT)
        if name is not SlotName.CONSENT_RECORDING:
            if self._consent_refused():
                return self._result("not_applicable", field, hint=DECLINED_HINT)
            if self.profile.consent_recording is not True:
                return self._result("not_applicable", field, hint=NO_CONSENT_HINT)
        spec = SLOT_BY_NAME[name]
        if not spec.active(self.profile):
            return self._result("not_applicable", field, hint="This field does not apply.")

        meta = self.slot_meta.setdefault(name, SlotMeta())
        meta.attempts += 1
        canonical = name in CANONICAL
        if not canonical and not said_in_transcript(said, self._recent_candidate):
            self._on_said_unverified(name.value)
            if name.value not in self.said_unverified:
                self.said_unverified.append(name.value)
        parser = CANONICAL[name] if canonical else VERBATIM[name]
        parsed = parser(value if canonical else (value.strip() or said), self.ctx)
        if isinstance(parsed, Issue):
            return self._on_issue(spec, meta, parsed, said)

        if self._needs_decline_confirmation(name, parsed):
            # Consent hook: a first "no" is not stored; the candidate is asked if they are sure.
            self._decline_pending = True
            return self._result("confirm_decline", field)

        previous = getattr(self.profile, name.value)
        was_filled = meta.status == "filled"
        setattr(self.profile, name.value, parsed)
        meta.status = "filled"
        meta.source = "live_tool"
        meta.raw = said or None
        self._failures.pop(name, None)
        self._hints.pop(name, None)
        if canonical:
            self._cross_check(name, meta, said, parsed)
        changed = was_filled and not _same(previous, parsed)
        if changed:
            meta.corrected = True
            self._event(
                "field_corrected",
                field=name.value,
                old=to_jsonable_python(previous),
                new=to_jsonable_python(parsed),
            )
        self._event("slot_filled", field=name.value, source=meta.source)
        if name is SlotName.CONSENT_RECORDING and parsed is False:
            self._purge_after_withdrawal()  # a confirmed refusal or a withdrawal
        self._after_fill(name)
        if changed and self._confirmed and not self.escalated and self.phase is Phase.CLOSING:
            # Correction after the read-back: collect/confirm again before closing.
            self._confirmed = False
            self._set_phase(Phase.COLLECTING)
        return self._result("ok", field, normalized=to_jsonable_python(parsed))

    def next_goal(self) -> str:
        """The next instruction for the model (TECHNICAL_DESIGN 5.3). Pure: no state change."""
        if self.phase is Phase.ENDED:
            return ENDED_GOAL
        if self.escalated:
            if not self.consented:
                return ESCALATED_NO_CONSENT_GOAL
            return ESCALATED_ASK_PHONE_GOAL if self._phone_open() else ESCALATED_GOAL
        if self._consent_refused():
            return CLOSE_DECLINED
        if self._decline_pending:
            return CONFIRM_DECLINE_GOAL
        pending = self._pending()
        if pending:
            spec = pending[0]
            hint = self._hints.get(spec.name)
            return f"{spec.ask} Previous answer was not valid: {hint}" if hint else spec.ask
        if self.phase in (Phase.COLLECTING, Phase.CONFIRMATION):
            return CONFIRM_GOAL
        return CLOSE_GOAL

    def missing(self) -> list[str]:
        """Required active slots that do not hold a value yet."""
        return [s.name.value for s in self._required_active() if not self._is_filled(s.name)]

    def progress(self) -> float:
        """Share of required active slots that are filled or unresolved."""
        required = self._required_active()
        done = sum(1 for s in required if self._is_done(s.name))
        return round(done / len(required), 2) if required else 1.0

    def confirm_profile(self) -> dict[str, JsonValue]:
        """Read-back instruction for role and risky slots; moves the interview to closing.

        Calling it again while closing after a confirmation returns the same read-back.
        """
        if self.phase is Phase.ENDED:
            return {"error": ENDED_HINT, "next_goal": ENDED_GOAL}
        again = self.phase is Phase.CLOSING and self._confirmed and not self.escalated
        if self.phase is not Phase.CONFIRMATION and not again:
            return {
                "error": "Not ready to confirm: some required answers are still missing.",
                "next_goal": self.next_goal(),
            }
        items: list[str] = []
        if self.profile.role is not None:
            items.append(f"role: {self.profile.role.value}")
        for spec in SLOTS:
            if not spec.risky:
                continue
            items.append(f"{spec.name.value}: {self._readback_text(spec.name, spoken=False)}")
        if not again:
            self._confirmed = True
            self._set_phase(Phase.CLOSING)
        self._readback_pending = True
        summary = (
            f"[language: {self.language}] Read these details back to the candidate in that "
            f"language and ask them to confirm: {'; '.join(items)}. If they correct "
            "something, call record_field with the new value. If they confirm, thank them, tell "
            "them you now have all the information you need and that the Acme Burgers hiring "
            "team will review it and be in touch soon, then call end_interview with reason "
            "completed."
        )
        return {"summary_for_readback": summary, "say": self.readback_say()}

    def readback_complete(self, text: str) -> bool:
        """True when `text` mentions the role and every filled risky detail (ES/EN).

        Unresolved slots are skipped. Only clears the `readback_pending` flag when it
        returns True: no phase, slot or event changes.
        """
        checks: list[bool] = []
        if self.profile.role is not None:
            checks.append(role_mentioned(self.profile.role, text))
        for spec in SLOTS:
            if spec.risky and self._is_filled(spec.name):
                value = getattr(self.profile, spec.name.value)
                checks.append(READBACK[spec.name][2](value, text, self.ctx.stores))
        complete = all(checks)
        if complete:
            self._readback_pending = False
        return complete

    def readback_say(self) -> str:
        """English line with the role and risky details for the model to translate and read."""
        parts: list[str] = []
        if self.profile.role is not None:
            parts.append(f"role {self.profile.role.value}")
        for spec in SLOTS:
            if spec.risky:
                label = READBACK[spec.name][0]
                parts.append(f"{label} {self._readback_text(spec.name, spoken=True)}")
        return f"Please confirm: {'; '.join(parts)}."

    def note_faq(self, question: str, found: bool, source: str | None = None) -> None:
        """Log a FAQ lookup as `faq_answered` (with source) or `faq_missed`; no other state."""
        if found:
            self._event("faq_answered", question=question, source=source)
        else:
            self._event("faq_missed", question=question)

    def escalate(self, reason: str) -> dict[str, JsonValue]:
        """Hand the candidate to a human recruiter. Idempotent; a no-op once ended.

        `reason` is a closed set (`EscalationReason`); anything else is stored as `other`,
        never as free text.
        """
        try:
            safe_reason = EscalationReason(reason)
        except ValueError:
            safe_reason = EscalationReason.OTHER
        if self.phase is Phase.ENDED and not self.escalated:
            return {"ticket_id": None, "message_for_candidate": ENDED_HINT}
        if self._ticket_id is None:
            self._ticket_id = self._id_factory()
            self.escalated = True
            self._frustration.clear()
            self._frustration_noted = False
            self._readback_pending = False
            self._event("escalated", reason=safe_reason.value, ticket_id=self._ticket_id)
            if self.phase is not Phase.ENDED:
                self._set_phase(Phase.CLOSING)
        goal = self.next_goal()
        message = f"[language: {self.language}] {goal}"
        return {"ticket_id": self._ticket_id, "message_for_candidate": message, "next_goal": goal}

    def end(self, reason: EndReason) -> None:
        """Finish the interview. Calling it again is a no-op.

        An escalated interview never ends as `abandoned`: a recruiter was promised, so a
        session that stops without an explicit reason ends `escalated`. Conversely `escalated`
        is only valid when an escalation happened; otherwise the candidate ended early
        (`abandoned`) and the requested reason is kept in the event payload.
        """
        if self.phase is Phase.ENDED:
            return
        requested = reason
        if self.escalated and reason is EndReason.ABANDONED:
            reason = EndReason.ESCALATED
        elif reason is EndReason.ESCALATED and not self.escalated:
            reason = EndReason.ABANDONED
        self._readback_pending = False
        self.end_reason = reason
        self.ended_at = self._clock()
        self._set_phase(Phase.ENDED)
        if requested is reason:
            self._event("interview_ended", reason=reason.value)
        else:
            self._event("interview_ended", reason=reason.value, requested_reason=requested.value)

    @property
    def has_phone(self) -> bool:
        """A phone number is held for a candidate who consented (basis for callback promises)."""
        return self.consented and self._is_filled(SlotName.PHONE)

    def _phone_open(self) -> bool:
        """After an escalation with consent: the phone is still to be asked for."""
        return self.escalated and self.consented and not self._is_done(SlotName.PHONE)

    @property
    def consented(self) -> bool:
        """Recording consent is a clear yes (gate for every optional model call, ADR-009.4)."""
        return self.profile.consent_recording is True and not self._consent_refused()

    def on_sentiment(self, score: float, frustration: bool) -> str | None:
        """Track the last 4 frustration flags; steer once per frustrated streak (ADR-011.2).

        The note repeats only after a non-frustrated turn has reset the streak. While a
        read-back is pending or the interview is closing, no note is returned and the streak is
        not consumed, so the next flagged turn can still offer the recruiter.
        """
        self._frustration.append(frustration)
        self._frustration_events += int(frustration)
        if not frustration:
            self._frustration_noted = False
            return None
        if self.escalated or self._frustration_noted:
            return None
        if self.readback_pending or self.phase in (Phase.CLOSING, Phase.ENDED):
            return None
        if sum(self._frustration) >= FRUSTRATION_THRESHOLD:
            self._frustration_noted = True
            self._recruiter_offered = True
            return FRUSTRATION_NOTE
        return None

    def on_candidate_text(self, text: str) -> str | None:
        """Steering note when the candidate explicitly asks for a person (ES/EN)."""
        if self._consent_refused():
            self._recent_candidate.clear()
        else:
            self._recent_candidate.append(text)
        if self.escalated or self.phase is Phase.ENDED:
            return None
        normalised = normalise_text(text)
        if _HUMAN_REQUEST_RE.search(normalised):
            self._recruiter_offered = True
            return HUMAN_REQUEST_NOTE
        return None

    def prefill(self, values: Mapping[SlotName, object], source: str = "prefill") -> list[SlotName]:
        """Fill empty, active slots from known data; returns the slots that were set.

        Values are canonical-value strings (as `record_field` takes them) or typed values
        (bool, Role, date, int, str, lists of Availability or strings), converted to their
        canonical string; both pass through the same CANONICAL/VERBATIM validators. Nothing is
        applied unless consent was given (`consent_recording is True`). Consent itself is never
        prefilled; invalid values are skipped.
        """
        applied: list[SlotName] = []
        if self.phase is Phase.ENDED or self.profile.consent_recording is not True:
            return applied
        for spec in SLOTS:  # slot order: role before the rider-only slots it activates
            name = spec.name
            if name not in values or name is SlotName.CONSENT_RECORDING:
                continue
            if not spec.active(self.profile) or self._status(name) == "filled":
                continue
            raw = values[name]
            if raw is None:
                continue
            text = raw if isinstance(raw, str) else _as_canonical(raw)
            parser = CANONICAL[name] if name in CANONICAL else VERBATIM[name]
            parsed = parser(text, self.ctx)
            if isinstance(parsed, Issue):
                continue
            setattr(self.profile, name.value, parsed)
            self.slot_meta[name] = SlotMeta(status="filled", source="prefill")
            self._event("slot_filled", field=name.value, source=source)
            self._after_fill(name)
            applied.append(name)
        self._advance()
        return applied

    def apply_reconciliation(self, result: ReconciliationResult) -> list[SlotName]:
        """Apply reconciliation fills and conflicts (ADR-008.2, ADR-016.2); returns filled slots.

        Only empty, active slots are filled (never a valid live value), marked
        `source: post_call`; conflicts are kept for the screening rules. Nothing is applied
        unless consent was given.
        """
        if self.profile.consent_recording is not True or self._consent_refused():
            return []
        applied: list[SlotName] = []
        fills = {f.slot: f for f in result.fills}
        for spec in SLOTS:  # slot order: role before the rider-only slots it activates
            fill = fills.get(spec.name)
            name = spec.name
            if fill is None or name is SlotName.CONSENT_RECORDING:
                continue
            if not spec.active(self.profile) or self._status(name) == "filled":
                continue
            setattr(self.profile, name.value, fill.value)
            meta = self.slot_meta.setdefault(name, SlotMeta())
            meta.status = "filled"
            meta.source = "post_call"
            meta.raw = fill.said
            self._event("slot_filled", field=name.value, source="post_call")
            self._after_fill(name)
            applied.append(name)
        confirmed = self.confirmed_slots()
        for conflict in result.conflicts:
            if all(c.slot is not conflict.slot for c in self.reconciliation_conflicts):
                kept = conflict.model_copy(deep=True)
                kept.confirmed_by_candidate = conflict.slot in confirmed
                self.reconciliation_conflicts.append(kept)
        return applied

    def confirmed_slots(self) -> frozenset[SlotName]:
        """Slots the candidate confirmed in the read-back (role and risky details, name included).

        Empty until the read-back happened, and again after a later correction.
        """
        if not self._confirmed:
            return frozenset()
        names = {SlotName.ROLE}
        names.update(spec.name for spec in SLOTS if spec.risky)
        return frozenset(names)

    def note_post_call_failed(self, step: str) -> None:
        """Record that the after-interview analysis failed; the rules then route to human review."""
        self.post_call_failed = True
        self._event("post_call_failed", step=step)

    def snapshot(self) -> dict[str, JsonValue]:
        """JSON-serialisable state for the UI. Nothing is masked here; the gateway decides."""
        slots: dict[str, JsonValue] = {}
        for spec in SLOTS:
            name = spec.name
            if not spec.active(self.profile):
                slots[name.value] = {"status": "not_applicable"}
            elif self._is_filled(name):
                slots[name.value] = {
                    "status": "filled",
                    "value": to_jsonable_python(getattr(self.profile, name.value)),
                }
            else:
                slots[name.value] = {"status": self._status(name)}
        return {"phase": self.phase.value, "progress": self.progress(), "slots": slots}

    def build_record(
        self,
        conversation_id: str,
        started_at: datetime,
        model_info: ModelInfo,
        channel: str,
        *,
        transcript: Sequence[TranscriptTurn] = (),
        metrics: Mapping[str, Any] | None = None,
    ) -> ConversationRecord:
        """Current `ConversationRecord`; screening comes only from `domain.rules` (ADR-009.1).

        The single redaction point (ADR-009.4): the transcript and `said_unverified` are kept
        only when consent is a clear yes; otherwise `transcript=[]` and counters/timings only.
        """
        today = self._clock().astimezone(ZoneInfo(self.timezone)).date()
        facts = rules.Facts(
            today=today,
            end_reason=self.end_reason,
            escalated=self.escalated,
            frustration_events=self._frustration_events,
            recruiter_offered=self._recruiter_offered,
            unresolved_slots=[s.name for s in SLOTS if self._status(s.name) == "unresolved"],
            reconciliation_conflicts=list(self.reconciliation_conflicts),
            post_call_failed=self.post_call_failed,
        )
        profile = self.profile.model_copy(deep=True)
        slot_meta = {n: m.model_copy(deep=True) for n, m in self.slot_meta.items()}
        events = [e.model_copy(deep=True) for e in self.events]
        if self.end_reason is EndReason.DECLINED_CONSENT or self._consent_refused():
            # ADR-009.4: keep nothing but the refusal itself once consent is declined.
            consent = SlotName.CONSENT_RECORDING
            profile = CandidateProfile(consent_recording=profile.consent_recording)
            slot_meta = {n: m for n, m in slot_meta.items() if n is consent}
            for meta in slot_meta.values():
                meta.raw = None
                meta.cross_check = None
                meta.cross_check_agrees = None
            events = [
                e
                for e in events
                if e.type in _KEPT_AFTER_DECLINE or e.payload.get("field") == consent.value
            ]
        kept_metrics = dict(metrics) if metrics else {}
        consented = self.profile.consent_recording is True and not (
            self.end_reason is EndReason.DECLINED_CONSENT or self._consent_refused()
        )
        if not consented:
            kept_metrics.pop("said_unverified", None)
        return ConversationRecord(
            conversation_id=conversation_id,
            started_at=started_at,
            ended_at=self.ended_at,
            end_reason=self.end_reason,
            channel=channel,
            language=LanguageInfo(detected=self.language),
            model=model_info,
            candidate=profile,
            slot_meta=slot_meta,
            screening=rules.evaluate(profile, facts),
            events=events,
            sentiment=aggregate(transcript, self._frustration_events) if consented else None,
            transcript=[t.model_copy(deep=True) for t in transcript] if consented else [],
            metrics=kept_metrics,
        )

    # -- internals -----------------------------------------------------------------------

    def _required_active(self) -> list[SlotSpec]:
        return [s for s in SLOTS if s.required and s.active(self.profile)]

    def _readback_text(self, name: SlotName, *, spoken: bool) -> str:
        if not self._is_filled(name):
            return "not provided"
        value = getattr(self.profile, name.value)
        return READBACK[name][1](value, self.ctx.stores, spoken)

    def _status(self, name: SlotName) -> str:
        meta = self.slot_meta.get(name)
        return meta.status or "empty" if meta else "empty"

    def _is_filled(self, name: SlotName) -> bool:
        return self._status(name) == "filled"

    def _is_done(self, name: SlotName) -> bool:
        return self._status(name) in ("filled", "unresolved")

    def _pending(self) -> list[SlotSpec]:
        pending = [s for s in self._required_active() if not self._is_done(s.name)]
        return sorted(pending, key=lambda s: (s.phase, s.order))

    def _needs_decline_confirmation(self, name: SlotName, parsed: object) -> bool:
        """Consent hook: True for a first "no" before consent was ever given."""
        return (
            name is SlotName.CONSENT_RECORDING
            and parsed is False
            and self.profile.consent_recording is None
            and not self._decline_pending
        )

    def _consent_refused(self) -> bool:
        """Consent declined, or unresolved after repeated failures (treated as no consent)."""
        name = SlotName.CONSENT_RECORDING
        return self.profile.consent_recording is False or self._status(name) == "unresolved"

    def _result(
        self,
        status: Status,
        field: str,
        *,
        normalized: JsonValue = None,
        hint: str | None = None,
    ) -> ToolResult:
        self._advance()  # mutating paths only; next_goal() itself never moves the phase
        return ToolResult(
            status=status,
            field=field,
            normalized=normalized,
            hint=hint,
            next_goal=self.next_goal(),
            missing=self.missing(),
            progress=self.progress(),
        )

    def _event(self, type_: EventType, **payload: JsonValue) -> None:
        event = Event(ts=self._clock(), type=type_, payload=dict(payload))
        self.events.append(event)
        self._emit(event)

    def _advance(self) -> None:
        """Move collecting <-> confirmation as pending slots appear or run out."""
        if self.escalated or self._consent_refused():
            return
        if self.phase is Phase.COLLECTING and not self._pending():
            self._set_phase(Phase.CONFIRMATION)
        elif self.phase is Phase.CONFIRMATION and self._pending():
            self._set_phase(Phase.COLLECTING)  # a role change added slots after read-back

    def _purge_after_withdrawal(self) -> None:
        """Consent refused or unresolved: drop other slot values, metadata, events."""
        consent = SlotName.CONSENT_RECORDING
        self.profile = CandidateProfile(consent_recording=self.profile.consent_recording)
        self.slot_meta = {n: m for n, m in self.slot_meta.items() if n is consent}
        self._failures.clear()
        self._hints.clear()
        self._confirmed = False
        self._readback_pending = False
        self._recent_candidate.clear()
        self.events[:] = [
            e
            for e in self.events
            if e.type not in _PER_FIELD_EVENTS or e.payload.get("field") == consent.value
        ]

    def _set_phase(self, phase: Phase) -> None:
        if phase is Phase.COLLECTING:
            self._readback_pending = False  # a correction reopened collecting
        if phase is not self.phase:
            self._event("phase_changed", **{"from": self.phase.value, "to": phase.value})
            self.phase = phase

    def _on_issue(self, spec: SlotSpec, meta: SlotMeta, issue: Issue, said: str) -> ToolResult:
        name = spec.name
        self._event("validation_failed", field=name.value, code=issue.code)
        if meta.status == "filled":
            # A failed correction never downgrades a stored value.
            return self._result("invalid", name.value, hint=issue.hint)
        meta.raw = said or None
        failures = self._failures.get(name, 0) + 1
        self._failures[name] = failures
        if failures >= MAX_ATTEMPTS:
            meta.status = "unresolved"
            self._hints.pop(name, None)
            if name is SlotName.CONSENT_RECORDING and not self.escalated:
                self._set_phase(Phase.CLOSING)  # unresolved consent is treated as declined
            self._event("slot_unresolved", field=name.value, attempts=failures)
            if name is SlotName.CONSENT_RECORDING:
                self._purge_after_withdrawal()
            return self._result("unresolved", name.value, hint=issue.hint)
        meta.status = "invalid"
        self._hints[name] = issue.hint
        return self._result("invalid", name.value, hint=issue.hint)

    def _cross_check(self, name: SlotName, meta: SlotMeta, said: str, canonical: object) -> None:
        """Advisory reading of `said`; recorded only, never changes value or flow (ADR-015.5)."""
        meta.cross_check = None
        meta.cross_check_agrees = None
        check = CROSS_CHECKS.get(name)
        if check is None or not said.strip():
            return
        reading = check(said, self.ctx)
        if isinstance(reading, Issue):
            meta.cross_check = {"issue": reading.code}
            return
        meta.cross_check = to_jsonable_python(reading)
        meta.cross_check_agrees = _same(reading, canonical)

    def _after_fill(self, name: SlotName) -> None:
        """The documented per-field hooks (ADR-016.5); everything else is data-driven."""
        if name is SlotName.CONSENT_RECORDING:
            # Consent hook: a refusal closes the call, an acceptance starts collecting.
            self._decline_pending = False
            if self.profile.consent_recording is False:
                self._set_phase(Phase.CLOSING)
            elif self.phase in (Phase.GREETING, Phase.CONSENT):
                self._set_phase(Phase.COLLECTING)
            elif self.phase is Phase.CLOSING and not self.escalated and not self._confirmed:
                self._set_phase(Phase.COLLECTING)  # consent corrected from no to yes
        elif name is SlotName.ROLE:
            # Role hook: leaving delivery_rider deactivates licence and vehicle, so their
            # values and metadata are cleared. Becoming a rider activates them (empty).
            if self.profile.role is not Role.DELIVERY_RIDER:
                for slot in RIDER_ONLY:
                    setattr(self.profile, slot.value, _empty_value(slot))
                    self.slot_meta.pop(slot, None)
                    self._failures.pop(slot, None)
                    self._hints.pop(slot, None)
        elif name is SlotName.PREFERRED_STORE_ID:
            # Store hook: the store's country becomes the session country, which drives the
            # default region of phone parsing.
            store = next(
                (s for s in self.ctx.stores if s.id == self.profile.preferred_store_id), None
            )
            country = _COUNTRIES.get(store.country) if store else None
            if country:
                self.ctx = replace(self.ctx, country=country)
