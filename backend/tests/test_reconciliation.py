"""Merging Hunar callbacks and poll results into a Call row.

Hunar retries callbacks on 4XX *and* 5XX, so a delivery can arrive twice and
out of order. These pin down that a replay never walks a finished call
backwards, and that the poller keeps chasing calls Hunar holds for hours.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from app.models import Call, CallStatus, CandidateStatus
from app.services.campaigns import (
    _now,
    answer_columns,
    apply_call_payload,
    compute_stats,
    compute_stats_across,
    sync_stale_calls,
)

COMPLETED_PAYLOAD = {
    "id": "hunar_call_regress",
    "status": "COMPLETED",
    "answered_by": "HUMAN",
    "duration_seconds": 96.4,
    "result": {"consent_to_continue": True, "notice_period": "60 days"},
}


@pytest.fixture
def completed_call(db, factory) -> Call:
    job = factory.job()
    candidate = factory.candidate(job)
    campaign = factory.campaign(job)
    call = factory.call(
        campaign,
        candidate,
        status=CallStatus.RINGING,
        hunar_call_id="hunar_call_regress",
    )
    apply_call_payload(call, COMPLETED_PAYLOAD, source="webhook")
    db.commit()
    return call


# ---------------------------------------------------------------------------
# Out-of-order / duplicated callbacks
# ---------------------------------------------------------------------------
def test_a_replayed_callback_reports_that_nothing_changed(completed_call) -> None:
    changed = apply_call_payload(
        completed_call,
        {"id": "hunar_call_regress", "status": "RINGING"},
        source="webhook",
    )

    assert changed is False


def test_a_replayed_ringing_callback_keeps_the_terminal_state(completed_call) -> None:
    apply_call_payload(
        completed_call,
        {
            "id": "hunar_call_regress",
            "status": "RINGING",
            "lifecycle_status": "IN_PROGRESS",
        },
        source="webhook",
    )

    assert completed_call.status == CallStatus.COMPLETED
    assert completed_call.candidate.status == CandidateStatus.COMPLETED
    assert compute_stats([completed_call]).completed == 1


def test_a_duplicated_not_connected_callback_does_not_wipe_the_duration(
    completed_call,
) -> None:
    """The status webhook for the *first*, failed attempt arriving late."""
    apply_call_payload(
        completed_call,
        {
            "id": "hunar_call_regress",
            "status": "NOT_CONNECTED",
            "answered_by": "UNKNOWN",
            "duration_seconds": 0.0,
        },
        source="webhook",
    )

    assert completed_call.status == CallStatus.COMPLETED
    assert completed_call.duration_seconds == 96.4
    assert completed_call.answered_by == "HUMAN"
    assert completed_call.result["notice_period"] == "60 days"


def test_an_out_of_order_status_inside_the_call_is_ignored(db, factory) -> None:
    job = factory.job()
    call = factory.call(
        factory.campaign(job),
        factory.candidate(job),
        status=CallStatus.IN_PROGRESS,
    )

    apply_call_payload(call, {"status": "RINGING"}, source="webhook")

    assert call.status == CallStatus.IN_PROGRESS


def test_a_hunar_retry_may_reopen_a_finished_call(completed_call) -> None:
    """REDIALING is a genuine new attempt, not a duplicate delivery."""
    apply_call_payload(
        completed_call,
        {
            "id": "hunar_call_regress",
            "status": "SCHEDULED",
            "redial_status": "REDIALING",
        },
        source="webhook",
    )

    assert completed_call.status == CallStatus.SCHEDULED


def test_a_higher_retry_count_also_reopens_a_finished_call(completed_call) -> None:
    apply_call_payload(
        completed_call,
        {"id": "hunar_call_regress", "status": "SCHEDULED", "retry_count": 1},
        source="webhook",
    )

    assert completed_call.status == CallStatus.SCHEDULED
    assert completed_call.retry_count == 1


def test_a_result_still_merges_into_a_completed_call(completed_call) -> None:
    """call_result_done carries no status and must always be applied."""
    apply_call_payload(
        completed_call,
        {"id": "hunar_call_regress", "result": {"notice_period": "immediate"}},
        source="webhook",
    )

    assert completed_call.result["notice_period"] == "immediate"


# ---------------------------------------------------------------------------
# Poller selection window
# ---------------------------------------------------------------------------
async def test_the_poller_still_reconciles_a_call_hunar_parked_overnight(
    db, factory, hunar_key, respx_mock, settings
) -> None:
    """Guardrails defer calls past the created_at window; polling must not stop."""
    job = factory.job()
    call = factory.call(
        factory.campaign(job),
        factory.candidate(job),
        status=CallStatus.SCHEDULED,
        hunar_call_id="hunar_call_parked",
    )
    stale = _now() - timedelta(minutes=settings.call_poll_max_age_minutes + 60)
    call.created_at = stale
    call.last_synced_at = _now() - timedelta(minutes=1)
    db.commit()

    respx_mock.get(
        "https://api.voice.hunar.ai/external/v1/calls/hunar_call_parked/"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "hunar_call_parked", "status": "COMPLETED"}
        )
    )

    assert await sync_stale_calls(db) == 1
    assert db.get(Call, call.id).status == CallStatus.COMPLETED


async def test_a_call_nobody_has_heard_from_in_hours_is_dropped(
    db, factory, hunar_key, settings
) -> None:
    job = factory.job()
    call = factory.call(
        factory.campaign(job),
        factory.candidate(job),
        status=CallStatus.SCHEDULED,
        hunar_call_id="hunar_call_abandoned",
    )
    stale = _now() - timedelta(minutes=settings.call_poll_max_age_minutes + 60)
    call.created_at = stale
    call.last_synced_at = stale
    db.commit()

    assert await sync_stale_calls(db) == 0


# ---------------------------------------------------------------------------
# Dashboard aggregates
# ---------------------------------------------------------------------------
def test_the_whole_database_aggregate_matches_the_in_memory_one(db, factory) -> None:
    job = factory.job()
    campaign = factory.campaign(job)
    factory.call(campaign, factory.candidate(job), status=CallStatus.PENDING)
    factory.call(campaign, factory.candidate(job), status=CallStatus.RINGING)
    factory.call(
        campaign,
        factory.candidate(job),
        status=CallStatus.COMPLETED,
        answered_by="HUMAN",
        duration_seconds=90.0,
        result={"consent_to_continue": True, "interest_level": "high"},
    )
    factory.call(
        campaign,
        factory.candidate(job),
        status=CallStatus.NOT_CONNECTED,
        result={"do_not_contact_requested": "yes"},
    )
    db.commit()

    assert compute_stats_across(db) == compute_stats(list(campaign.calls))


# ---------------------------------------------------------------------------
# Dashboard columns
# ---------------------------------------------------------------------------
def test_a_hyphen_inside_the_question_survives_the_type_prefix_strip() -> None:
    columns = answer_columns(
        {
            "years_experience": (
                "number — How many years of hands-on professional experience do you "
                "have as a Senior Backend Engineer? Use null if not stated."
            )
        }
    )

    assert columns[0]["type"] == "number"
    assert columns[0]["description"].startswith("How many years of hands-on")


def test_a_schema_with_no_type_prefix_keeps_its_whole_description() -> None:
    columns = answer_columns(
        {"on_site": "This role is on-site in Bengaluru. Does that work for you?"}
    )

    assert columns[0]["description"].startswith("This role is on-site")
