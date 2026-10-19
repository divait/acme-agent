"""Closing lines per end reason (SPEC-018): English steering text for the model to translate.

Pure data shared by the `end_interview` tool and the goodbye guards of the live session and
text mode. Not candidate-facing copy.
"""

from __future__ import annotations

from acme_agent.domain.models import EndReason

CLOSING_LINES: dict[EndReason, str] = {
    EndReason.COMPLETED: (
        "Thank the candidate warmly and tell them you now have all the information you need. "
        "Say the Acme Burgers hiring team will review it and be in touch with them soon. "
        "Say goodbye."
    ),
    EndReason.DECLINED_CONSENT: (
        "Thank the candidate kindly. Tell them nothing from this conversation was stored "
        "and they can contact the Acme Burgers hiring team at any time. Say goodbye."
    ),
    EndReason.ESCALATED: (
        "Thank the candidate. Tell them a recruiter will call them at the number they gave. "
        "Say goodbye."
    ),
    EndReason.ABANDONED: (
        "The candidate is not answering. Say kindly that you will end the call now, "
        "that they can start again any time, and say goodbye (in Spanish: 'hasta luego')."
    ),
}

GOODBYE_NOTE = (
    "[SYSTEM NOTE] The interview has ended. Say goodbye now in the candidate's language: {say}"
)


ESCALATED_NO_PHONE_LINE = (
    "Thank the candidate. Do not promise any call or contact: tell them they can contact "
    "the Acme Burgers hiring team at any time. Say goodbye."
)
ESCALATED_NO_CONSENT_LINE = (
    "Thank the candidate. Tell them nothing from this conversation was stored and they can "
    "contact the Acme Burgers hiring team at any time. Do not promise any call. Say goodbye."
)


def closing_line(reason: EndReason | None, has_phone: bool = False, consented: bool = False) -> str:
    """The closing line for `reason` (abandoned when unknown).

    Promises must match the data held: a callback only when an escalated candidate gave a
    phone number; abandoned or early endings never promise contact.
    """
    reason = reason or EndReason.ABANDONED
    if reason is EndReason.ESCALATED:
        if not consented:
            return ESCALATED_NO_CONSENT_LINE
        return CLOSING_LINES[reason] if has_phone else ESCALATED_NO_PHONE_LINE
    return CLOSING_LINES[reason]
