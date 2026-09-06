"""Phone-number normalisation.

Voice providers need E.164. People-search vendors return everything from
``9876543210`` to ``+91 98765-43210`` to ``(415) 555-0100``.
"""

from __future__ import annotations

import phonenumbers

from app.core.config import settings

# Numbers reserved for fiction: +1 (NPA) 555-01XX and the UK/IN drama ranges.
_FICTIONAL_PREFIXES = ("+1",)


def normalise_phone(
    raw: str | None, *, default_region: str | None = None
) -> tuple[str | None, bool]:
    """Return ``(e164_or_none, is_valid)``.

    A number that parses but is not *valid* (e.g. a reserved 555 demo number)
    is still returned - the operator may knowingly want to dial it - but the
    flag lets the UI say so.
    """
    if not raw:
        return None, False
    candidate = str(raw).strip()
    if not candidate:
        return None, False

    region = (default_region or settings.default_country_code or "IN").upper()
    for attempt_region in (
        [None, region] if candidate.startswith("+") else [region, None]
    ):
        try:
            parsed = phonenumbers.parse(candidate, attempt_region)
        except phonenumbers.NumberParseException:
            continue
        formatted = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.E164
        )
        if phonenumbers.is_valid_number(parsed):
            return formatted, True
        if phonenumbers.is_possible_number(parsed):
            return formatted, False
    return None, False


def is_fictional(e164: str | None) -> bool:
    """True for the +1-NPA-555-01XX block used by the built-in demo dataset."""
    if not e164 or not e164.startswith(_FICTIONAL_PREFIXES):
        return False
    digits = e164[2:]
    return len(digits) == 10 and digits[3:6] == "555" and digits[6:8] == "01"


def describe(e164: str | None) -> str:
    if not e164:
        return "no number"
    try:
        parsed = phonenumbers.parse(e164, None)
        return phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
    except phonenumbers.NumberParseException:
        return e164
