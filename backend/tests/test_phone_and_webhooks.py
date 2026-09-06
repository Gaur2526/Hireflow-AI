"""Phone normalisation and Hunar webhook signature verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

import pytest

from app.services.phone import describe, is_fictional, normalise_phone
from app.services.webhook_security import (
    MAX_SKEW_SECONDS,
    verify_signature,
)

SECRET = "hunar_va_test_sk_not_a_real_key_0000"


# ===========================================================================
# Phone normalisation
# ===========================================================================
@pytest.mark.parametrize(
    ("raw", "region", "expected"),
    [
        ("+91 98765-43210", None, "+919876543210"),
        ("9876543210", "IN", "+919876543210"),
        ("098765 43210", "IN", "+919876543210"),
        ("+91 (98765) 43210", None, "+919876543210"),
        ("  +919876543210  ", None, "+919876543210"),
        ("(415) 555-0100", "US", "+14155550100"),
        ("415-555-0100", "US", "+14155550100"),
        ("+1 202 555 0187", None, "+12025550187"),
        ("+44 20 7946 0958", None, "+442079460958"),
    ],
)
def test_normalises_to_e164(raw: str, region: str | None, expected: str) -> None:
    number, valid = normalise_phone(raw, default_region=region)
    assert number == expected
    assert valid is True


@pytest.mark.parametrize(
    "junk",
    [
        None,
        "",
        "   ",
        "not-a-number",
        "n/a",
        "email@example.com",
        "+",
        "++++",
        "12",
    ],
)
def test_junk_input_yields_no_number(junk: str | None) -> None:
    assert normalise_phone(junk, default_region="IN") == (None, False)


def test_a_plus_prefixed_number_is_parsed_in_its_own_country() -> None:
    """A leading "+" must win over the configured default region."""
    number, _ = normalise_phone("+14155550100", default_region="IN")
    assert number == "+14155550100"


def test_possible_but_invalid_numbers_are_returned_and_flagged() -> None:
    number, valid = normalise_phone("+91 11111 11111", default_region="IN")
    assert number == "+911111111111", "still returned - the operator may know better"
    assert valid is False, "but the UI must be able to warn that it is not dialable"


def test_describe_renders_something_human_readable() -> None:
    assert describe("+919876543210") == "+91 98765 43210"
    assert describe(None) == "no number"
    assert describe("garbage") == "garbage"


# --- the fictional-number detector -----------------------------------------
@pytest.mark.parametrize(
    "number",
    [
        "+12025550100",
        "+12125550101",
        "+13125550102",
        "+14155550187",
        "+16175550199",
        "+17185550100",
    ],
)
def test_detects_the_plus_1_npa_555_01xx_fiction_block(number: str) -> None:
    assert is_fictional(number) is True


@pytest.mark.parametrize(
    "number",
    [
        None,
        "",
        "+919876543210",  # not +1 at all
        "+12025551234",  # 555 but not the 01XX block
        "+12025554100",  # 555 in the wrong position
        "+120255501",  # too short
        "+120255501000",  # too long
        "+442079460958",
    ],
)
def test_real_numbers_are_not_flagged_as_fictional(number: str | None) -> None:
    assert is_fictional(number) is False


def test_the_demo_dataset_only_produces_fictional_numbers() -> None:
    """Nothing the built-in provider generates can ever reach a real person."""
    from app.services.people_search.mock import FICTION_AREA_CODES

    for index, area in enumerate(FICTION_AREA_CODES):
        number = f"+1{area}555{100 + index:04d}"
        assert is_fictional(number) is True


# ===========================================================================
# Webhook signature verification
# ===========================================================================
def hunar_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Sign exactly the way Hunar does: b64(HMAC-SHA256(f"{ts}." + body))."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


BODY = b'{"event_type":"call_result_done","call_id":"call_abc","result":{"ok":true}}'


def test_a_genuine_hunar_signature_verifies() -> None:
    ts = str(int(time.time()))
    verdict = verify_signature(
        secret=SECRET,
        body=BODY,
        signature_header=hunar_signature(SECRET, ts, BODY),
        timestamp_header=ts,
    )
    assert verdict.valid is True
    assert verdict.scheme == "timestamp.body"
    assert "verified" in verdict.reason.lower()


def test_a_forged_signature_fails() -> None:
    ts = str(int(time.time()))
    forged = base64.b64encode(b"x" * 32).decode()
    verdict = verify_signature(
        secret=SECRET, body=BODY, signature_header=forged, timestamp_header=ts
    )
    assert verdict.valid is False
    assert verdict.reason == "Signature mismatch"


def test_a_signature_made_with_the_wrong_key_fails() -> None:
    ts = str(int(time.time()))
    verdict = verify_signature(
        secret=SECRET,
        body=BODY,
        signature_header=hunar_signature("some-other-key", ts, BODY),
        timestamp_header=ts,
    )
    assert verdict.valid is False


def test_a_tampered_body_fails() -> None:
    ts = str(int(time.time()))
    signature = hunar_signature(SECRET, ts, BODY)
    verdict = verify_signature(
        secret=SECRET,
        body=BODY.replace(b'"ok":true', b'"ok":false'),
        signature_header=signature,
        timestamp_header=ts,
    )
    assert verdict.valid is False


def test_a_stale_timestamp_fails_even_with_a_correct_digest() -> None:
    stale = str(int(time.time()) - MAX_SKEW_SECONDS - 60)
    verdict = verify_signature(
        secret=SECRET,
        body=BODY,
        signature_header=hunar_signature(SECRET, stale, BODY),
        timestamp_header=stale,
    )
    assert verdict.valid is False
    assert "skew" in verdict.reason.lower()


def test_a_far_future_timestamp_also_fails() -> None:
    future = str(int(time.time()) + MAX_SKEW_SECONDS + 60)
    verdict = verify_signature(
        secret=SECRET,
        body=BODY,
        signature_header=hunar_signature(SECRET, future, BODY),
        timestamp_header=future,
    )
    assert verdict.valid is False


def test_a_timestamp_inside_the_window_still_verifies() -> None:
    recent = str(int(time.time()) - (MAX_SKEW_SECONDS - 30))
    verdict = verify_signature(
        secret=SECRET,
        body=BODY,
        signature_header=hunar_signature(SECRET, recent, BODY),
        timestamp_header=recent,
    )
    assert verdict.valid is True


def test_a_malformed_timestamp_is_rejected() -> None:
    verdict = verify_signature(
        secret=SECRET,
        body=BODY,
        signature_header=hunar_signature(SECRET, "not-a-time", BODY),
        timestamp_header="not-a-time",
    )
    assert verdict.valid is False
    assert "Malformed" in verdict.reason


def test_missing_signature_header_is_rejected() -> None:
    verdict = verify_signature(secret=SECRET, body=BODY, signature_header=None)
    assert verdict.valid is False
    assert "Missing" in verdict.reason


def test_no_secret_means_no_verification() -> None:
    verdict = verify_signature(secret="", body=BODY, signature_header="anything")
    assert verdict.valid is False
    assert "not verified" in verdict.reason


def test_a_non_ascii_signature_is_rejected_not_raised() -> None:
    """ASGI decodes headers as latin-1, and compare_digest TypeErrors on those.

    Left unhandled it is a one-byte unauthenticated 500 generator - and Hunar
    retries 5XX, so a genuinely corrupted header would be retried forever.
    """
    verdict = verify_signature(
        secret=SECRET, body=BODY, signature_header=b"\xe9bad".decode("latin-1")
    )

    assert verdict.valid is False
    assert verdict.reason == "Signature mismatch"


def test_a_valid_signature_still_verifies_beside_a_non_ascii_one() -> None:
    ts = str(int(time.time()))
    good = hunar_signature(SECRET, ts, BODY)
    verdict = verify_signature(
        secret=SECRET,
        body=BODY,
        signature_header=f"{b'\xe9bad'.decode('latin-1')},{good}",
        timestamp_header=ts,
    )

    assert verdict.valid is True


# --- header formatting quirks ----------------------------------------------
def test_scheme_prefix_stripper_does_not_eat_base64_padding() -> None:
    """A SHA-256 digest base64-encodes to 44 chars ending in "=".

    A naive ``strip("=")`` style prefix stripper would swallow that padding and
    every genuine callback would be rejected.
    """
    ts = str(int(time.time()))
    signature = hunar_signature(SECRET, ts, BODY)
    assert signature.endswith("="), "precondition: this digest is padded"

    for prefix in ("sha256=", "SHA256=", "sha-256=", "hmac=", "v1=", "t="):
        verdict = verify_signature(
            secret=SECRET,
            body=BODY,
            signature_header=f"{prefix}{signature}",
            timestamp_header=ts,
        )
        assert verdict.valid is True, f"{prefix!r} broke verification"


def test_an_unprefixed_padded_signature_verifies() -> None:
    ts = str(int(time.time()))
    signature = hunar_signature(SECRET, ts, BODY)
    assert signature.endswith("=")
    verdict = verify_signature(
        secret=SECRET, body=BODY, signature_header=signature, timestamp_header=ts
    )
    assert verdict.valid is True


def test_comma_separated_multi_key_headers_work() -> None:
    """Orgs mid key-rotation send one digest per active key."""
    ts = str(int(time.time()))
    good = hunar_signature(SECRET, ts, BODY)
    other = hunar_signature("rotated-out-key", ts, BODY)

    for header in (
        f"{other},{good}",
        f"{good},{other}",
        f" {other} , {good} ",
        f"v1={other},v1={good}",
    ):
        verdict = verify_signature(
            secret=SECRET, body=BODY, signature_header=header, timestamp_header=ts
        )
        assert verdict.valid is True, header

    only_wrong = f"{other},{hunar_signature('third-key', ts, BODY)}"
    assert (
        verify_signature(
            secret=SECRET, body=BODY, signature_header=only_wrong, timestamp_header=ts
        ).valid
        is False
    )


def test_hex_encoded_digests_are_also_accepted() -> None:
    ts = str(int(time.time()))
    hex_digest = hmac.new(
        SECRET.encode(), f"{ts}.".encode() + BODY, hashlib.sha256
    ).hexdigest()
    verdict = verify_signature(
        secret=SECRET, body=BODY, signature_header=hex_digest, timestamp_header=ts
    )
    assert verdict.valid is True


def test_body_only_signature_is_accepted_and_reported() -> None:
    """Some tenants sign the bare body; the verdict says which scheme matched."""
    mac = hmac.new(SECRET.encode(), BODY, hashlib.sha256).digest()
    verdict = verify_signature(
        secret=SECRET,
        body=BODY,
        signature_header=base64.b64encode(mac).decode(),
        timestamp_header=None,
    )
    assert verdict.valid is True
    assert verdict.scheme == "body"
    assert verdict.as_note == "Signature verified (body)"
