"""Slot validators: canonical-format validators and verbatim parsers (ADR-015).

Parsers never raise on candidate input and never read the clock or files; everything they
need comes from `ParseContext`. Hints are short English instructions for the model.
"""

from acme_agent.domain.models import SlotName
from acme_agent.domain.validators.availability import parse_availability
from acme_agent.domain.validators.base import Issue, ParseContext, Parser, ParseResult
from acme_agent.domain.validators.canonical import (
    canonical_availability,
    canonical_bool,
    canonical_languages,
    canonical_months,
    canonical_role,
    canonical_start_date,
    canonical_summary,
    canonical_weekly_hours,
)
from acme_agent.domain.validators.choice import ROLE_WORDS, parse_bool, parse_role
from acme_agent.domain.validators.dates import parse_start_date
from acme_agent.domain.validators.experience import (
    parse_languages,
    parse_months,
    parse_text,
    parse_weekly_hours,
)
from acme_agent.domain.validators.identity import parse_email, parse_name, parse_phone
from acme_agent.domain.validators.location import parse_store

CANONICAL: dict[SlotName, Parser] = {
    SlotName.CONSENT_RECORDING: canonical_bool,
    SlotName.RIGHT_TO_WORK: canonical_bool,
    SlotName.IS_18_OR_OVER: canonical_bool,
    SlotName.DRIVING_LICENCE: canonical_bool,
    SlotName.OWN_VEHICLE: canonical_bool,
    SlotName.ROLE: canonical_role,
    SlotName.AVAILABILITY: canonical_availability,
    SlotName.START_DATE: canonical_start_date,
    SlotName.WEEKLY_HOURS: canonical_weekly_hours,
    SlotName.EXPERIENCE_MONTHS: canonical_months,
    SlotName.LANGUAGES: canonical_languages,
    SlotName.EXPERIENCE_SUMMARY: canonical_summary,
}

VERBATIM: dict[SlotName, Parser] = {
    SlotName.FULL_NAME: parse_name,
    SlotName.PHONE: parse_phone,
    SlotName.EMAIL: parse_email,
    SlotName.PREFERRED_STORE_ID: parse_store,
}

# Advisory natural-language readings of `said` for canonical slots (ADR-015.5).
CROSS_CHECKS: dict[SlotName, Parser] = {
    SlotName.CONSENT_RECORDING: parse_bool,
    SlotName.RIGHT_TO_WORK: parse_bool,
    SlotName.IS_18_OR_OVER: parse_bool,
    SlotName.DRIVING_LICENCE: parse_bool,
    SlotName.OWN_VEHICLE: parse_bool,
    SlotName.ROLE: parse_role,
    SlotName.AVAILABILITY: parse_availability,
    SlotName.START_DATE: parse_start_date,
    SlotName.WEEKLY_HOURS: parse_weekly_hours,
    SlotName.EXPERIENCE_MONTHS: parse_months,
    SlotName.LANGUAGES: parse_languages,
    SlotName.EXPERIENCE_SUMMARY: parse_text,
}

# Deprecated alias kept so existing tests work. SPEC-005 must use CANONICAL / VERBATIM.
PARSERS: dict[SlotName, Parser] = {**CROSS_CHECKS, **VERBATIM}

__all__ = [
    "CANONICAL",
    "CROSS_CHECKS",
    "PARSERS",
    "ROLE_WORDS",
    "VERBATIM",
    "Issue",
    "ParseContext",
    "ParseResult",
    "Parser",
    "parse_availability",
    "parse_bool",
    "parse_email",
    "parse_languages",
    "parse_months",
    "parse_name",
    "parse_phone",
    "parse_role",
    "parse_start_date",
    "parse_store",
    "parse_text",
    "parse_weekly_hours",
]
