"""Verification of Hunar's ``X-Hunar-Signature`` callback header.

Hunar signs callbacks with HMAC-SHA256 and sends the digest base64-encoded
(comma-separated when the org has more than one active signing key), alongside
``X-Hunar-Timestamp``.

The exact string that gets signed is not pinned down in the public docs, so we
accept any of the constructions vendors commonly use and report which one
matched. That keeps verification strict (a forged signature still fails) while
not silently rejecting genuine callbacks over a formatting detail.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from dataclasses import dataclass

from app.core.logging import get_logger

log = get_logger(__name__)

#: Reject callbacks whose timestamp is further away than this (replay defence).
MAX_SKEW_SECONDS = 15 * 60


@dataclass
class VerificationResult:
    valid: bool
    reason: str = ""
    scheme: str = ""

    @property
    def as_note(self) -> str:
        return f"{self.reason} ({self.scheme})" if self.scheme else self.reason


def _digests(secret: str, body: bytes, timestamp: str | None) -> dict[str, set[str]]:
    """Candidate signature encodings, keyed by the string that was signed."""
    payloads: dict[str, bytes] = {"body": body}
    if timestamp:
        payloads["timestamp.body"] = f"{timestamp}.".encode() + body
        payloads["timestamp+body"] = timestamp.encode() + body

    out: dict[str, set[str]] = {}
    key = secret.encode()
    for name, payload in payloads.items():
        mac = hmac.new(key, payload, hashlib.sha256).digest()
        out[name] = {base64.b64encode(mac).decode(), mac.hex()}
    return out


#: Tolerate "sha256=<digest>" / "v1=<digest>" prefixes without eating the
#: trailing "=" padding that base64 digests end with.
_SCHEME_PREFIX = re.compile(r"^(?:sha256|sha-256|hmac|v1|t)=(?=.)", re.I)


def _strip_scheme_prefix(candidate: str) -> str:
    return _SCHEME_PREFIX.sub("", candidate.strip(), count=1)


def verify_signature(
    *,
    secret: str,
    body: bytes,
    signature_header: str | None,
    timestamp_header: str | None = None,
    max_skew_seconds: int = MAX_SKEW_SECONDS,
) -> VerificationResult:
    if not secret:
        return VerificationResult(
            False, "No HUNAR_WEBHOOK_SECRET configured - signature not verified"
        )
    if not signature_header:
        return VerificationResult(False, "Missing X-Hunar-Signature header")

    if timestamp_header:
        try:
            skew = abs(time.time() - float(timestamp_header))
        except (TypeError, ValueError):
            return VerificationResult(False, "Malformed X-Hunar-Timestamp header")
        if skew > max_skew_seconds:
            return VerificationResult(False, f"Timestamp skew too large ({skew:.0f}s)")

    expected = _digests(secret, body, timestamp_header)
    # ASGI decodes header bytes as latin-1, so a mangled header can carry
    # non-ASCII text - which hmac.compare_digest raises TypeError on. Drop those
    # candidates so a malformed delivery is rejected, not 500'd (and retried).
    provided = [
        part.strip()
        for part in signature_header.split(",")
        if part.strip() and part.isascii()
    ]

    for scheme, digests in expected.items():
        for candidate in provided:
            value = _strip_scheme_prefix(candidate)
            for digest in digests:
                if hmac.compare_digest(value, digest):
                    return VerificationResult(True, "Signature verified", scheme)

    return VerificationResult(False, "Signature mismatch")
