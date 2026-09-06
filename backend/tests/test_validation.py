"""Input validation that exists to pre-empt an upstream 4xx.

``CallDefaults`` mirrors what Hunar enforces server-side, and campaign creation
refuses to launch an agent whose declared custom variables we cannot fill. Both
turn a raw upstream rejection into a sentence an operator can act on.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from app.core.errors import ValidationFailure
from app.schemas.campaign import RETRY_INTERVALS, CallDefaults, CampaignCreate
from app.services.campaigns import create_campaign

from tests.conftest import AGENTS_URL


def _messages(exc: ValidationError) -> str:
    return " | ".join(e["msg"] for e in exc.errors())


# ===========================================================================
# CallDefaults
# ===========================================================================
def test_the_defaults_are_themselves_valid() -> None:
    defaults = CallDefaults()
    assert defaults.retry_interval_hours in RETRY_INTERVALS
    assert len(defaults.allowed_days) >= 3
    assert defaults.earliest_call_time == "10:00"
    assert defaults.last_call_time == "19:00"
    assert defaults.from_phone_number is None, "let Hunar assign a pooled number"


@pytest.mark.parametrize("hours", RETRY_INTERVALS)
def test_accepted_retry_intervals(hours: int) -> None:
    assert CallDefaults(retry_interval_hours=hours).retry_interval_hours == hours


@pytest.mark.parametrize("hours", [1, 2, 4, 5, 7, 8, 11, 13, 23, 25, -3])
def test_rejects_retry_intervals_hunar_does_not_support(hours: int) -> None:
    with pytest.raises(ValidationError) as exc:
        CallDefaults(retry_interval_hours=hours)
    assert "retry_interval_hours must be one of 0, 3, 6, 9, 12, 24" in _messages(
        exc.value
    )


@pytest.mark.parametrize(
    "days",
    [
        [],
        ["MON"],
        ["MON", "TUE"],
        ["MON", "mon", "Mon"],  # de-duplicated down to one day
        ["MON", " tue "],
    ],
)
def test_rejects_fewer_than_three_calling_days(days: list[str]) -> None:
    with pytest.raises(ValidationError) as exc:
        CallDefaults(allowed_days=days)
    assert "Pick at least three calling days." in _messages(exc.value)


def test_days_are_upper_cased_trimmed_and_de_duplicated() -> None:
    defaults = CallDefaults(allowed_days=[" mon ", "MON", "tue", "Wed", "wed"])
    assert defaults.allowed_days == ["MON", "TUE", "WED"]


def test_rejects_unknown_day_names() -> None:
    with pytest.raises(ValidationError) as exc:
        CallDefaults(allowed_days=["MON", "TUE", "FUNDAY"])
    assert "Unknown day(s): FUNDAY" in _messages(exc.value)


@pytest.mark.parametrize(
    "value",
    ["10:00:00", "19:00:00", "9:00", "10.00", "24:00", "10:60", "1000", "ten", ""],
)
def test_rejects_times_that_are_not_hh_mm(value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        CallDefaults(earliest_call_time=value)
    assert "must be HH:MM in 24-hour time (not HH:MM:SS)" in _messages(exc.value)


def test_hh_mm_ss_is_specifically_called_out() -> None:
    """The most common operator mistake gets the most specific message."""
    with pytest.raises(ValidationError) as exc:
        CallDefaults(last_call_time="19:00:00")
    assert "'19:00:00' must be HH:MM in 24-hour time (not HH:MM:SS)." in _messages(
        exc.value
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("10:00", "12:00"),  # 2 hours
        ("10:00", "12:59"),  # 2h59
        ("14:00", "14:00"),  # zero-length
        ("19:00", "10:00"),  # inverted
    ],
)
def test_rejects_a_calling_window_under_three_hours(start: str, end: str) -> None:
    with pytest.raises(ValidationError) as exc:
        CallDefaults(earliest_call_time=start, last_call_time=end)
    assert "The calling window must be at least 3 hours long." in _messages(exc.value)


@pytest.mark.parametrize(("start", "end"), [("10:00", "13:00"), ("09:00", "21:00")])
def test_accepts_a_window_of_exactly_three_hours_or_more(start: str, end: str) -> None:
    defaults = CallDefaults(earliest_call_time=start, last_call_time=end)
    assert (defaults.earliest_call_time, defaults.last_call_time) == (start, end)


@pytest.mark.parametrize("count", [-1, 11, 50])
def test_rejects_out_of_range_retry_counts(count: int) -> None:
    with pytest.raises(ValidationError):
        CallDefaults(max_retry_count=count)


# --- through the HTTP API --------------------------------------------------
def test_the_api_returns_a_readable_422_for_a_bad_calling_window(
    client, factory
) -> None:
    job = factory.job()
    response = client.post(
        f"/api/jobs/{job.id}/campaigns",
        json={
            "call_defaults": {
                "earliest_call_time": "10:00:00",
                "allowed_days": ["MON", "TUE"],
                "retry_interval_hours": 5,
            }
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    fields = {d["field"] for d in error["details"]}
    messages = " ".join(d["message"] for d in error["details"])

    assert "call_defaults.earliest_call_time" in fields
    assert "call_defaults.allowed_days" in fields
    assert "call_defaults.retry_interval_hours" in fields
    assert "HH:MM" in messages
    assert "at least three calling days" in messages
    assert "0, 3, 6, 9, 12, 24" in messages


def test_job_creation_rejects_a_too_short_description(client) -> None:
    response = client.post("/api/jobs", json={"description": "too short"})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "description"


# ===========================================================================
# Custom-variable mismatch between our script and Hunar's agent
# ===========================================================================
AGENT_WITH_EXTRA_VARIABLE = {
    "id": "agent_1",
    "status": "ACTIVE",
    "custom_variables": [
        "job_title",
        "company",
        "jd_summary",
        "key_requirements",
        "recruiter_name",  # declared by Hunar, never supplied by us
        "interview_stage",
    ],
}


async def test_campaign_creation_fails_readably_on_an_undeclarable_variable(
    db, factory, respx_mock, hunar_key
) -> None:
    respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(201, json=AGENT_WITH_EXTRA_VARIABLE)
    )
    job = factory.job()
    factory.candidate(job, phone="+919876500001")

    with pytest.raises(ValidationFailure) as exc:
        await create_campaign(db, job, CampaignCreate())

    assert exc.value.status_code == 422
    message = exc.value.message
    assert "Hunar requires custom variables this campaign cannot supply" in message
    assert "interview_stage" in message and "recruiter_name" in message
    assert exc.value.details == {
        "missing_custom_data": ["interview_stage", "recruiter_name"]
    }


async def test_that_failure_is_recorded_on_the_campaign_row(
    db, factory, respx_mock, hunar_key
) -> None:
    respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(201, json=AGENT_WITH_EXTRA_VARIABLE)
    )
    job = factory.job()
    factory.candidate(job)

    with pytest.raises(ValidationFailure):
        await create_campaign(db, job, CampaignCreate())

    from app.models import Campaign, CampaignStatus

    campaign = db.query(Campaign).filter(Campaign.job_id == job.id).one()
    assert campaign.status == CampaignStatus.FAILED
    assert "recruiter_name" in (campaign.error or "")


def test_the_api_surfaces_that_error_as_a_422(
    client, factory, respx_mock, hunar_key
) -> None:
    respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(201, json=AGENT_WITH_EXTRA_VARIABLE)
    )
    job = factory.job()
    factory.candidate(job)

    response = client.post(f"/api/jobs/{job.id}/campaigns", json={})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert "cannot supply" in error["message"]
    assert error["details"]["missing_custom_data"] == [
        "interview_stage",
        "recruiter_name",
    ]


def test_the_failed_campaign_row_survives_the_request_rollback(
    client, factory, respx_mock, hunar_key, db
) -> None:
    """The agent exists upstream by now; losing its id orphans it forever."""
    from app.models import Campaign, CampaignStatus

    respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(201, json=AGENT_WITH_EXTRA_VARIABLE)
    )
    job = factory.job()
    factory.candidate(job)

    assert client.post(f"/api/jobs/{job.id}/campaigns", json={}).status_code == 422

    db.expire_all()
    campaign = db.query(Campaign).filter(Campaign.job_id == job.id).one()
    assert campaign.status == CampaignStatus.FAILED
    assert campaign.hunar_agent_id == AGENT_WITH_EXTRA_VARIABLE["id"]
    assert "recruiter_name" in (campaign.error or "")


# ===========================================================================
# Our own script referencing a variable no call will supply
# ===========================================================================
async def test_an_operator_edited_prompt_with_a_stray_brace_is_rejected(
    db, factory, respx_mock, hunar_key
) -> None:
    job = factory.job()
    factory.candidate(job)

    payload = CampaignCreate.model_validate(
        {
            "agent_config": {
                "agent_prompt": (
                    "You are screening for {job_title} at {company}. "
                    "Mention the {signing_bonus} and ask for {referral_code}."
                )
            }
        }
    )

    with pytest.raises(ValidationFailure) as exc:
        await create_campaign(db, job, payload)

    assert "references variables that no call will supply" in exc.value.message
    assert "{referral_code}" in exc.value.message
    assert "{signing_bonus}" in exc.value.message
    assert exc.value.details == {
        "unknown_variables": ["referral_code", "signing_bonus"]
    }
    assert not respx_mock.calls, "we must fail before creating a Hunar agent"


async def test_a_prompt_using_only_known_variables_is_accepted(
    db, factory, respx_mock, hunar_key
) -> None:
    respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "agent_ok",
                "status": "ACTIVE",
                "custom_variables": ["job_title", "company"],
            },
        )
    )
    job = factory.job()
    factory.candidate(job)

    campaign, _, _ = await create_campaign(
        db,
        job,
        CampaignCreate.model_validate(
            {
                "agent_config": {
                    "agent_prompt": "Screen for {job_title} at {company}. {jd_summary}",
                    "introduction": "Hi {callee_name}, calling about {job_title}.",
                }
            }
        ),
    )

    assert campaign.hunar_agent_id == "agent_ok"


# ===========================================================================
# Campaign preconditions
# ===========================================================================
async def test_a_job_with_no_screening_questions_cannot_launch(
    db, factory, respx_mock, hunar_key
) -> None:
    job = factory.job(screening_questions=[], result_schema={})
    factory.candidate(job)

    with pytest.raises(ValidationFailure) as exc:
        await create_campaign(db, job, CampaignCreate())
    assert "Parse the job description first" in exc.value.message
    assert not respx_mock.calls


async def test_a_campaign_with_no_candidates_cannot_launch(
    db, factory, respx_mock, hunar_key
) -> None:
    job = factory.job()  # nobody shortlisted
    with pytest.raises(ValidationFailure) as exc:
        await create_campaign(db, job, CampaignCreate())
    assert "Select at least one candidate" in exc.value.message
    assert not respx_mock.calls
