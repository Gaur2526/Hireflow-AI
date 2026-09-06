"""The whole product, driven through HTTP.

JD -> people search -> shortlist -> voice agent -> outbound calls -> signed
webhook -> dashboard -> CSV. Every ``api.voice.hunar.ai`` request is mocked with
respx; the socket guard in ``conftest`` fails the test if anything escapes.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import time
from typing import Any

import httpx
import pytest

from app.models import (
    Call,
    CallStatus,
    Campaign,
    CampaignStatus,
    Candidate,
    CandidateStatus,
)

from tests.conftest import AGENTS_URL, CALLS_URL, FAKE_HUNAR_KEY, FAKE_REDIRECT_NUMBER

JD = """\
Role: Senior Backend Engineer

About the role
We move money for a living and rebuilt the ledger 2 years ago.

Responsibilities
- Own the Observability stack and the on-call rotation

Requirements
- 5-9 years building production backend services
- Deep Python and PostgreSQL experience
- Kubernetes in production

Nice to have
- Kafka

Hybrid, full-time, based in Bengaluru.
"""

AGENT_RESPONSE = {
    "id": "agent_7f3a",
    "status": "ACTIVE",
    "agent_code": "AG-7F3A",
    "custom_variables": ["job_title", "company", "jd_summary", "key_requirements"],
    "required_variables": [],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class HunarStub:
    """Records what the app sent to Hunar and hands back plausible responses."""

    def __init__(self, respx_mock) -> None:
        self.agents_created: list[dict[str, Any]] = []
        self.calls_created: list[dict[str, Any]] = []

        respx_mock.post(AGENTS_URL).mock(side_effect=self._agent)
        respx_mock.post(CALLS_URL).mock(side_effect=self._call)

    def _agent(self, request: httpx.Request) -> httpx.Response:
        self.agents_created.append(json.loads(request.content))
        return httpx.Response(201, json=AGENT_RESPONSE)

    def _call(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls_created.append(body)
        index = len(self.calls_created)
        return httpx.Response(
            201,
            json={
                "id": f"hunar_call_{index}",
                "status": "NOT_STARTED",
                "request_id": body.get("request_id"),
                "agent_id": body["agent_id"],
                "mobile_number": body["mobile_number"],
            },
        )

    @property
    def dialed_numbers(self) -> list[str]:
        return [c["mobile_number"] for c in self.calls_created]


def signed_post(
    client, url: str, payload: dict[str, Any], *, secret: str = FAKE_HUNAR_KEY
):
    """POST a webhook signed exactly the way Hunar signs it."""
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).digest()
    return client.post(
        url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hunar-Signature": base64.b64encode(digest).decode(),
            "X-Hunar-Timestamp": timestamp,
        },
    )


RESULT_PAYLOAD_TEMPLATE = {
    "event_type": "call_result_done",
    "status": "COMPLETED",
    "answered_by": "HUMAN",
    "duration_seconds": 96.4,
    "user_speech_duration": 41.2,
    "recording_url": "https://recordings.example.com/hunar_call_1.mp3",
    "result": {
        "consent_to_continue": True,
        "open_to_opportunity": True,
        "current_role": "Senior Backend Engineer at Razorpay",
        "years_of_experience": 7,
        "python_depth": "Rebuilt a settlement service in Python and FastAPI.",
        "secondary_skills_confirmed": "PostgreSQL yes, Kubernetes yes",
        "location_fit": True,
        "notice_period": "60 days",
        "best_time_to_talk": "Weekday evenings after 6pm",
        "do_not_contact_requested": False,
        "screening_summary": "Says he 'owns the settlement pipeline end to end'.",
        "recommended_next_step": "schedule_interview",
    },
}


# ---------------------------------------------------------------------------
# the happy path
# ---------------------------------------------------------------------------
@pytest.fixture
def hunar(respx_mock) -> HunarStub:
    return HunarStub(respx_mock)


def test_end_to_end_happy_path(
    client, hunar: HunarStub, hunar_key, demo_redirect, db, reread
) -> None:
    # --- 1. intake + parse ------------------------------------------------
    response = client.post(
        "/api/jobs",
        json={
            "title": "Senior Backend Engineer",
            "company": "Acme Payments",
            "location": "Bengaluru",
            "description": JD,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    job_id = job["id"]

    assert job["parsed_by"] == "heuristic"
    assert job["status"] == "PARSED"
    assert job["criteria"]["must_have_skills"][0] == "Python"
    assert job["criteria"]["min_years"] == 5.0
    assert job["criteria"]["countries"] == ["IN"]
    assert "consent_to_continue" in job["result_schema"]
    assert "screening_summary" in job["result_schema"]

    # --- 2. source ---------------------------------------------------------
    response = client.post(f"/api/jobs/{job_id}/search", json={"limit": 6})
    assert response.status_code == 200, response.text
    search = response.json()

    assert search["provider_label"] == "Built-in demo dataset"
    assert search["run"]["returned"] == 6
    assert search["run"]["new_candidates"] == 6
    candidates = search["candidates"]
    assert len(candidates) == 6
    # Ranked by fit, explainably.
    scores = [c["fit_score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert all(c["fit_reasons"] for c in candidates)
    assert all(c["status"] == "SOURCED" for c in candidates)
    assert any("reserved for fiction" in w for w in search["warnings"]), (
        "the demo dataset must say its numbers are fake"
    )

    # --- 3. shortlist ------------------------------------------------------
    chosen = [c["id"] for c in candidates[:3]]
    response = client.post(
        f"/api/jobs/{job_id}/shortlist", json={"candidate_ids": chosen}
    )
    assert response.status_code == 200
    assert {c["status"] for c in response.json()} == {"SHORTLISTED"}

    # --- 4. launch the campaign -------------------------------------------
    response = client.post(f"/api/jobs/{job_id}/campaigns", json={})
    assert response.status_code == 201, response.text
    launch = response.json()
    campaign_id = launch["campaign"]["id"]

    # One agent, three calls, all through the documented endpoints.
    assert len(hunar.agents_created) == 1
    assert len(hunar.calls_created) == 3
    assert launch["dispatched"] == 3
    assert launch["skipped"] == []

    agent_body = hunar.agents_created[0]
    assert agent_body["voice_persona"] == "NEHA"
    assert agent_body["language"] == "ENGLISH"
    assert "{job_title}" in agent_body["agent_prompt"]
    assert "{callee_name}" in agent_body["introduction"]
    assert set(agent_body["result_schema"]) == set(launch["campaign"]["result_schema"])

    for body in hunar.calls_created:
        assert body["agent_id"] == "agent_7f3a"
        assert set(body["custom_data"]) >= {
            "job_title",
            "company",
            "jd_summary",
            "key_requirements",
        }
        assert body["custom_data"]["company"] == "Acme Payments"
        assert body["mobile_number"] == FAKE_REDIRECT_NUMBER

    # --- 5. statuses advanced ---------------------------------------------
    session = reread()
    campaign = session.get(Campaign, campaign_id)
    assert campaign.status == CampaignStatus.RUNNING
    assert campaign.hunar_agent_id == "agent_7f3a"

    calls = session.query(Call).filter(Call.campaign_id == campaign_id).all()
    assert len(calls) == 3
    assert {c.status for c in calls} == {"NOT_STARTED"}
    assert {c.hunar_call_id for c in calls} == {
        "hunar_call_1",
        "hunar_call_2",
        "hunar_call_3",
    }
    assert all(c.dialed_redirected for c in calls)
    assert all(c.dialed_number == FAKE_REDIRECT_NUMBER for c in calls)
    assert all(c.sync_source == "dispatch" for c in calls)

    for candidate_id in chosen:
        assert session.get(Candidate, candidate_id).status == CandidateStatus.CALLING

    # --- 6. Hunar calls back with the answers ------------------------------
    target = next(c for c in calls if c.hunar_call_id == "hunar_call_1")
    payload = {**RESULT_PAYLOAD_TEMPLATE, "call_id": "hunar_call_1"}
    response = signed_post(client, "/api/webhooks/hunar/result", payload)

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "matched": True, "changed": True}

    session = reread()
    stored = session.get(Call, target.id)
    assert stored.status == CallStatus.COMPLETED
    assert stored.sync_source == "webhook"
    assert stored.answered_by == "HUMAN"
    assert stored.duration_seconds == pytest.approx(96.4)
    assert stored.recording_url == RESULT_PAYLOAD_TEMPLATE["recording_url"]
    assert stored.result == RESULT_PAYLOAD_TEMPLATE["result"]
    assert stored.result["recommended_next_step"] == "schedule_interview"
    assert (
        session.get(Candidate, stored.candidate_id).status == CandidateStatus.COMPLETED
    )

    # The callback itself is logged with its signature verdict.
    events = client.get("/api/webhooks/hunar/events").json()
    assert events[0]["event_type"] == "call_result_done"
    assert events[0]["signature_valid"] is True
    assert events[0]["handled"] is True

    # --- 7. the dashboard --------------------------------------------------
    detail = client.get(f"/api/campaigns/{campaign_id}").json()
    assert detail["job_title"] == "Senior Backend Engineer"
    assert detail["stats"]["total"] == 3
    assert detail["stats"]["completed"] == 1
    assert detail["stats"]["in_flight"] == 2
    assert detail["stats"]["consented"] == 1
    assert detail["stats"]["interested"] == 1
    assert detail["stats"]["answered_human"] == 1
    assert detail["stats"]["do_not_contact"] == 0
    assert any("Demo redirect is active" in w for w in detail["warnings"])

    answered = next(c for c in detail["calls"] if c["id"] == target.id)
    assert answered["result"]["notice_period"] == "60 days"
    assert answered["result"]["screening_summary"].startswith("Says he")
    assert answered["candidate_name"]
    assert answered["candidate_fit_score"] > 0

    # One dashboard column per result_schema key, in schema order.
    columns = [c["key"] for c in detail["answer_columns"]]
    assert columns == list(detail["campaign"]["result_schema"])
    types = {c["key"]: c["type"] for c in detail["answer_columns"]}
    assert types["consent_to_continue"] == "boolean"
    assert types["years_of_experience"] == "number"
    assert types["recommended_next_step"] == "enum"
    assert types["current_role"] == "string"

    # --- 8. CSV export -----------------------------------------------------
    response = client.get(f"/api/campaigns/{campaign_id}/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(response.text)))
    header, *body_rows = rows

    fixed = [
        "candidate_name",
        "title",
        "company",
        "linkedin_url",
        "fit_score",
        "phone_dialed",
        "status",
        "answered_by",
        "duration_seconds",
        "recording_url",
    ]
    assert header[: len(fixed)] == fixed
    assert header[len(fixed) :] == columns, "one column per result_schema key"
    assert len(header) == len(fixed) + len(detail["campaign"]["result_schema"])
    assert len(body_rows) == 3, "one row per call"
    assert all(len(row) == len(header) for row in body_rows)

    answered_row = dict(
        zip(
            header,
            next(r for r in body_rows if r[header.index("status")] == "COMPLETED"),
        )
    )
    assert answered_row["consent_to_continue"] == "yes"
    assert answered_row["do_not_contact_requested"] == "no"
    assert answered_row["notice_period"] == "60 days"
    assert answered_row["recommended_next_step"] == "schedule_interview"
    assert answered_row["phone_dialed"] == FAKE_REDIRECT_NUMBER
    assert answered_row["answered_by"] == "HUMAN"

    # Calls with no answers yet leave the answer columns blank, not "None".
    pending_row = dict(
        zip(
            header,
            next(r for r in body_rows if r[header.index("status")] != "COMPLETED"),
        )
    )
    assert pending_row["screening_summary"] == ""
    assert pending_row["recording_url"] == ""


# ---------------------------------------------------------------------------
# webhook security through the API
# ---------------------------------------------------------------------------
def test_a_forged_webhook_signature_is_rejected_and_changes_nothing(
    client, factory, hunar_key, db, reread
) -> None:
    job = factory.job()
    candidate = factory.candidate(job)
    campaign = factory.campaign(job)
    call = factory.call(
        campaign, candidate, status=CallStatus.NOT_STARTED, hunar_call_id="hunar_call_9"
    )

    body = json.dumps({**RESULT_PAYLOAD_TEMPLATE, "call_id": "hunar_call_9"}).encode()
    response = client.post(
        "/api/webhooks/hunar/result",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hunar-Signature": base64.b64encode(b"not the real digest!!").decode(),
            "X-Hunar-Timestamp": str(int(time.time())),
        },
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is False
    assert response.json()["reason"] == "Signature mismatch"

    stored = reread().get(Call, call.id)
    assert stored.result == {}
    assert stored.status == CallStatus.NOT_STARTED

    event = client.get("/api/webhooks/hunar/events").json()[0]
    assert event["signature_valid"] is False
    assert event["handled"] is False


def test_a_webhook_signed_with_the_wrong_key_is_rejected(
    client, factory, hunar_key, reread
) -> None:
    job = factory.job()
    candidate = factory.candidate(job)
    campaign = factory.campaign(job)
    call = factory.call(campaign, candidate, hunar_call_id="hunar_call_9")

    response = signed_post(
        client,
        "/api/webhooks/hunar/result",
        {**RESULT_PAYLOAD_TEMPLATE, "call_id": "hunar_call_9"},
        secret="an-attacker-guess",
    )
    assert response.json()["accepted"] is False
    assert reread().get(Call, call.id).result == {}


def test_a_webhook_for_an_unknown_call_is_accepted_but_not_applied(
    client, hunar_key
) -> None:
    response = signed_post(
        client,
        "/api/webhooks/hunar/result",
        {**RESULT_PAYLOAD_TEMPLATE, "call_id": "hunar_call_does_not_exist"},
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "matched": False}

    event = client.get("/api/webhooks/hunar/events").json()[0]
    assert event["signature_valid"] is True
    assert event["handled"] is False
    assert "no matching call" in event["note"]


def test_status_and_recording_webhooks_merge_into_the_same_call(
    client, factory, hunar_key, reread
) -> None:
    """Arrival order does not matter: each callback merges, never overwrites."""
    job = factory.job()
    candidate = factory.candidate(job)
    campaign = factory.campaign(job)
    call = factory.call(campaign, candidate, hunar_call_id="hunar_call_5")

    signed_post(
        client,
        "/api/webhooks/hunar/result",
        {
            "event_type": "call_result_done",
            "call_id": "hunar_call_5",
            "result": {"consent_to_continue": True},
        },
    )
    signed_post(
        client,
        "/api/webhooks/hunar/recording",
        {
            "event_type": "call_recording_done",
            "call_id": "hunar_call_5",
            "recording_url": "https://recordings.example.com/5.mp3",
        },
    )
    signed_post(
        client,
        "/api/webhooks/hunar/status",
        {
            "event_type": "call_status_updated",
            "call_id": "hunar_call_5",
            "status": "COMPLETED",
            "duration_seconds": 42,
        },
    )

    stored = reread().get(Call, call.id)
    assert stored.result == {"consent_to_continue": True}, "not wiped by later events"
    assert stored.recording_url == "https://recordings.example.com/5.mp3"
    assert stored.status == CallStatus.COMPLETED
    assert stored.duration_seconds == 42.0


# ---------------------------------------------------------------------------
# the fictional-number guardrail
# ---------------------------------------------------------------------------
def test_fictional_only_candidates_are_skipped_with_a_readable_reason(
    client, hunar: HunarStub, hunar_key, monkeypatch, settings, reread
) -> None:
    """No DEMO_CALL_REDIRECT_NUMBER: the demo dataset must not be dialled."""
    monkeypatch.setattr(settings, "demo_call_redirect_number", "")

    job_id = client.post(
        "/api/jobs",
        json={"title": "Senior Backend Engineer", "company": "Acme", "description": JD},
    ).json()["id"]
    candidates = client.post(f"/api/jobs/{job_id}/search", json={"limit": 3}).json()[
        "candidates"
    ]
    assert all(c["phone"].startswith("+1") for c in candidates)

    chosen = [c["id"] for c in candidates]
    client.post(f"/api/jobs/{job_id}/shortlist", json={"candidate_ids": chosen})

    launch = client.post(f"/api/jobs/{job_id}/campaigns", json={}).json()

    assert launch["dispatched"] == 0
    assert hunar.calls_created == [], "not one call may leave"
    assert len(launch["skipped"]) == 3
    for skip in launch["skipped"]:
        assert skip["candidate_id"] in chosen
        assert skip["name"]
        assert skip["reason"] == (
            "Demo number (+1-555-01XX) - set DEMO_CALL_REDIRECT_NUMBER to dial"
        )
    assert any("No dialable candidates" in w for w in launch["warnings"])

    session = reread()
    for candidate_id in chosen:
        assert (
            session.get(Candidate, candidate_id).status == CandidateStatus.UNREACHABLE
        )


def test_fictional_candidates_are_dialled_to_the_redirect_number_when_set(
    client, hunar: HunarStub, hunar_key, demo_redirect, reread
) -> None:
    job_id = client.post(
        "/api/jobs",
        json={"title": "Senior Backend Engineer", "company": "Acme", "description": JD},
    ).json()["id"]
    candidates = client.post(f"/api/jobs/{job_id}/search", json={"limit": 2}).json()[
        "candidates"
    ]
    original_numbers = {c["phone"] for c in candidates}
    client.post(
        f"/api/jobs/{job_id}/shortlist",
        json={"candidate_ids": [c["id"] for c in candidates]},
    )

    launch = client.post(f"/api/jobs/{job_id}/campaigns", json={}).json()
    campaign_id = launch["campaign"]["id"]

    assert launch["dispatched"] == 2
    assert launch["skipped"] == []
    assert hunar.dialed_numbers == [FAKE_REDIRECT_NUMBER, FAKE_REDIRECT_NUMBER]
    assert not original_numbers & set(hunar.dialed_numbers)

    calls = reread().query(Call).filter(Call.campaign_id == campaign_id).all()
    assert all(c.dialed_redirected for c in calls)

    detail = client.get(f"/api/campaigns/{campaign_id}").json()
    assert any("Demo redirect is active" in w for w in detail["warnings"])
    # The operator can still see who the call was *meant* for.
    assert {c["candidate_name"] for c in detail["calls"]} == {
        c["full_name"] for c in candidates
    }


def test_a_candidate_with_a_real_number_is_dialled_directly(
    client, hunar: HunarStub, hunar_key, factory, reread
) -> None:
    job = factory.job()
    factory.candidate(job, phone="+919876500123", full_name="Priya Iyer")

    launch = client.post(f"/api/jobs/{job.id}/campaigns", json={}).json()

    assert launch["dispatched"] == 1
    assert hunar.dialed_numbers == ["+919876500123"]
    calls = (
        reread().query(Call).filter(Call.campaign_id == launch["campaign"]["id"]).all()
    )
    assert calls[0].dialed_redirected is False


def test_a_candidate_with_no_number_is_skipped(
    client, hunar: HunarStub, hunar_key, factory, reread
) -> None:
    job = factory.job()
    reachable = factory.candidate(job, phone="+919876500123", full_name="Priya Iyer")
    unreachable = factory.candidate(job, phone=None, full_name="Rohan Mehta")

    launch = client.post(f"/api/jobs/{job.id}/campaigns", json={}).json()

    assert launch["dispatched"] == 1
    assert launch["skipped"] == [
        {
            "candidate_id": unreachable.id,
            "name": "Rohan Mehta",
            "reason": "No usable phone number",
        }
    ]
    session = reread()
    assert session.get(Candidate, unreachable.id).status == CandidateStatus.UNREACHABLE
    assert session.get(Candidate, reachable.id).status == CandidateStatus.CALLING


# ---------------------------------------------------------------------------
# dispatch failures
# ---------------------------------------------------------------------------
def test_a_hunar_rejection_marks_the_call_failed_with_the_upstream_reason(
    client, respx_mock, hunar_key, factory, reread
) -> None:
    respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(201, json=AGENT_RESPONSE)
    )
    respx_mock.post(CALLS_URL).mock(
        return_value=httpx.Response(
            422,
            json={
                "success": False,
                "message": "Validation failed",
                "details": [
                    {"field_name": "mobile_number", "error_msg": "Number not reachable"}
                ],
            },
        )
    )
    job = factory.job()
    candidate = factory.candidate(job, phone="+919876500123")

    launch = client.post(f"/api/jobs/{job.id}/campaigns", json={}).json()

    assert launch["dispatched"] == 0
    assert len(launch["skipped"]) == 1
    reason = launch["skipped"][0]["reason"]
    assert "Hunar rejected the request payload (422)." in reason
    assert "mobile_number: Number not reachable" in reason
    assert launch["campaign"]["status"] == CampaignStatus.FAILED

    session = reread()
    call = (
        session.query(Call).filter(Call.campaign_id == launch["campaign"]["id"]).one()
    )
    assert call.status == CallStatus.FAILED
    assert call.error == reason
    assert session.get(Candidate, candidate.id).status == CandidateStatus.UNREACHABLE


def test_an_unreachable_hunar_fails_the_launch_readably_not_with_a_500(
    client, respx_mock, hunar_key, factory
) -> None:
    respx_mock.post(AGENTS_URL).mock(side_effect=httpx.ConnectError("no route to host"))
    job = factory.job()
    factory.candidate(job, phone="+919876500123")

    response = client.post(f"/api/jobs/{job.id}/campaigns", json={})

    assert response.status_code == 502, response.text
    error = response.json()["error"]
    assert error["code"] == "upstream_error"
    assert error["provider"] == "hunar"
    assert "Could not reach Hunar" in error["message"]


def test_dry_run_creates_the_agent_but_places_no_calls(
    client, hunar: HunarStub, hunar_key, factory, reread
) -> None:
    job = factory.job()
    factory.candidate(job, phone="+919876500123")

    launch = client.post(f"/api/jobs/{job.id}/campaigns", json={"dry_run": True}).json()

    assert launch["dispatched"] == 0
    assert hunar.calls_created == []
    assert len(hunar.agents_created) == 1
    assert launch["campaign"]["status"] == CampaignStatus.AGENT_READY
    assert any("Dry run" in w for w in launch["warnings"])

    # ...and the queue can be dispatched later.
    campaign_id = launch["campaign"]["id"]
    dispatch = client.post(f"/api/campaigns/{campaign_id}/dispatch").json()
    assert dispatch["dispatched"] == 1
    assert len(hunar.calls_created) == 1
    assert dispatch["campaign"]["status"] == CampaignStatus.RUNNING


# ---------------------------------------------------------------------------
# polling fallback
# ---------------------------------------------------------------------------
def test_sync_pulls_results_for_calls_that_never_got_a_webhook(
    client, respx_mock, hunar_key, factory, reread
) -> None:
    job = factory.job()
    candidate = factory.candidate(job)
    campaign = factory.campaign(job)
    call = factory.call(
        campaign, candidate, status=CallStatus.IN_PROGRESS, hunar_call_id="hunar_call_3"
    )

    respx_mock.get(f"{CALLS_URL}hunar_call_3/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "hunar_call_3",
                "status": "COMPLETED",
                "answered_by": "HUMAN",
                "duration_seconds": 61.0,
                "result": {"consent_to_continue": True, "notice_period": "30 days"},
            },
        )
    )

    detail = client.post(f"/api/campaigns/{campaign.id}/sync").json()

    assert detail["stats"]["completed"] == 1
    assert detail["calls"][0]["result"]["notice_period"] == "30 days"
    assert detail["calls"][0]["sync_source"] == "poll"

    session = reread()
    assert session.get(Call, call.id).status == CallStatus.COMPLETED
    assert session.get(Candidate, candidate.id).status == CandidateStatus.COMPLETED
    assert session.get(Campaign, campaign.id).status == CampaignStatus.COMPLETED


# ---------------------------------------------------------------------------
# misc surfaces
# ---------------------------------------------------------------------------
def test_health_and_config_never_leak_the_key(client, hunar_key) -> None:
    health = client.get("/api/meta/health").json()
    assert health["status"] == "ok"
    assert health["hunar_configured"] is True
    assert health["llm_configured"] is False

    config = client.get("/api/meta/config").json()
    assert config["hunar"]["configured"] is True
    assert FAKE_HUNAR_KEY not in json.dumps(config)
    assert config["hunar"]["key_fingerprint"] != FAKE_HUNAR_KEY
    assert config["people_provider"] == "mock"


def test_unknown_job_returns_a_readable_404(client) -> None:
    response = client.get("/api/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_dashboard_overview_counts_the_pipeline(
    client, hunar: HunarStub, hunar_key, factory
) -> None:
    job = factory.job()
    factory.candidate(job, phone="+919876500123")
    client.post(f"/api/jobs/{job.id}/campaigns", json={})

    overview = client.get("/api/dashboard/overview").json()
    assert overview["totals"]["jobs"] == 1
    assert overview["totals"]["candidates"] == 1
    assert overview["totals"]["campaigns"] == 1
    assert overview["totals"]["calls"] == 1
    assert overview["recent_campaigns"][0]["stats"]["total"] == 1


def test_the_csv_filename_is_header_safe(client, factory) -> None:
    """HTTP headers are latin-1; the default campaign name has an em dash."""
    job = factory.job()
    campaign = factory.campaign(job, name="HireFlow AI — Senior Backend Engineer ✨")

    response = client.get(f"/api/campaigns/{campaign.id}/export.csv")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    disposition.encode("latin-1")  # would raise before the fix
    assert disposition == (
        'attachment; filename="HireFlow_AI_Senior_Backend_Engineer_results.csv"'
    )


def test_export_of_an_empty_campaign_is_still_a_valid_csv(client, factory) -> None:
    job = factory.job()
    campaign = factory.campaign(job)
    rows = list(
        csv.reader(
            io.StringIO(client.get(f"/api/campaigns/{campaign.id}/export.csv").text)
        )
    )
    assert len(rows) == 1
    assert rows[0][0] == "candidate_name"
    assert "screening_summary" in rows[0]


# ---------------------------------------------------------------------------
# the callback URLs we hand Hunar
# ---------------------------------------------------------------------------
def test_the_callback_urls_sent_to_hunar_resolve_to_real_routes(
    client, hunar: HunarStub, hunar_key, factory, settings, monkeypatch
) -> None:
    """PUBLIC_BASE_URL + api_prefix + the router prefix must equal a live route.

    Nothing else pins this down: rename a webhook path and every result would
    silently be POSTed by Hunar into a 404 forever.
    """
    from app.main import app as fastapi_app

    monkeypatch.setattr(settings, "public_base_url", "https://hireflow.example.com")
    job = factory.job()
    factory.candidate(job, phone="+919876500123")

    launch = client.post(f"/api/jobs/{job.id}/campaigns", json={}).json()
    assert launch["dispatched"] == 1

    callback = hunar.calls_created[0]["callback_config"]
    assert set(callback) == {
        "call_status_callback_url",
        "call_recording_callback_url",
        "call_result_callback_url",
        "call_summary_callback_url",
    }

    live_paths = {r.path for r in fastapi_app.routes if hasattr(r, "path")}
    for key, url in callback.items():
        assert url.startswith("https://hireflow.example.com/api/webhooks/hunar/"), key
        assert httpx.URL(url).path in live_paths, f"{key} -> {url} is not a route"

    # ...and the calling guardrails travel with the call.
    body = hunar.calls_created[0]
    assert body["timezone"] == "Asia/Kolkata"
    assert body["guardrails"]["allowed_days"] == ["MON", "TUE", "WED", "THU", "FRI"]
    assert body["guardrails"]["earliest_call_time"] == "10:00"
    assert body["retry_config"]["retry_interval_hours"] == 6


def test_without_a_public_base_url_no_callbacks_are_promised(
    client, hunar: HunarStub, hunar_key, factory, settings, monkeypatch
) -> None:
    """A plain-http or empty base URL falls back to polling, not a dead URL.

    Loopback is the one exception - ``tools/hunar_stub.py`` posts callbacks back
    to 127.0.0.1 during local testing - and is covered separately below.
    """
    monkeypatch.setattr(settings, "public_base_url", "http://hireflow.example.com")
    job = factory.job()
    factory.candidate(job, phone="+919876500123")

    launch = client.post(f"/api/jobs/{job.id}/campaigns", json={}).json()

    assert "callback_config" not in hunar.calls_created[0]
    assert any("PUBLIC_BASE_URL" in w for w in launch["warnings"])


def test_a_loopback_base_url_still_registers_callbacks(
    client, hunar: HunarStub, hunar_key, factory, settings, monkeypatch
) -> None:
    """Loopback is allowed so the local Hunar stub can exercise the webhook path."""
    monkeypatch.setattr(settings, "public_base_url", "http://127.0.0.1:8000")
    job = factory.job()
    factory.candidate(job, phone="+919876500124")

    launch = client.post(f"/api/jobs/{job.id}/campaigns", json={}).json()

    callbacks = hunar.calls_created[0]["callback_config"]
    assert callbacks["call_result_callback_url"] == (
        "http://127.0.0.1:8000/api/webhooks/hunar/result"
    )
    assert not any("PUBLIC_BASE_URL" in w for w in launch["warnings"])


# ---------------------------------------------------------------------------
# untrusted input reaching the operator's machine
# ---------------------------------------------------------------------------
def test_csv_export_neutralises_spreadsheet_formulas(client, factory, db) -> None:
    """Answers are whatever the person said on the phone; names come from a vendor."""
    job = factory.job()
    candidate = factory.candidate(job, full_name='=HYPERLINK("https://evil.example")')
    campaign = factory.campaign(job)
    factory.call(
        campaign,
        candidate,
        status=CallStatus.COMPLETED,
        result={"current_role": "=cmd|'/c calc'!A1"},
    )

    rows = list(
        csv.reader(
            io.StringIO(client.get(f"/api/campaigns/{campaign.id}/export.csv").text)
        )
    )
    row = dict(zip(rows[0], rows[1]))

    assert row["candidate_name"].startswith("'=")
    assert row["current_role"].startswith("'=")


def test_the_webhook_event_feed_cannot_be_asked_for_everything(client, db) -> None:
    """SQLite reads LIMIT -1 as unlimited; Postgres errors. Neither is acceptable."""
    from app.models import WebhookEvent

    for index in range(5):
        db.add(WebhookEvent(event_type="call_status_updated", hunar_call_id=str(index)))
    db.commit()

    assert client.get("/api/webhooks/hunar/events?limit=-1").status_code == 422
    assert client.get("/api/webhooks/hunar/events?limit=1000").status_code == 422
    assert len(client.get("/api/webhooks/hunar/events?limit=2").json()) == 2


def test_the_spa_fallback_cannot_be_walked_out_of_its_static_root(
    client, factory, settings, monkeypatch, tmp_path
) -> None:
    """Starlette URL-decodes {full_path:path}, so "%2e%2e" arrives as "..".

    Without containment this serves any file the container can read - including
    the SQLite database with every candidate's phone number in it.
    """
    from app.main import _mount_frontend

    dist = tmp_path / "static"
    (dist / "_next").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>spa")
    secret = tmp_path / "SECRET_ENV"
    secret.write_text("HUNAR_API_KEY=hunar_va_live_sk_TOPSECRET")

    monkeypatch.setattr(settings, "serve_frontend", True)
    monkeypatch.setattr(settings, "frontend_dist_dir", str(dist))
    _mount_frontend()
    try:
        response = client.get("/%2e%2e/SECRET_ENV")
        assert "TOPSECRET" not in response.text
        assert response.text == "<!doctype html>spa"
    finally:
        from app.main import app as fastapi_app

        fastapi_app.router.routes = [
            route
            for route in fastapi_app.router.routes
            if getattr(route, "path", "") not in {"/{full_path:path}", "/_next"}
        ]


def test_listing_jobs_does_not_fetch_every_candidate_row(client, factory, db) -> None:
    """Job.candidates is selectin-loaded but JobSummary uses none of it."""
    from sqlalchemy import event

    from app.db.base import engine

    job = factory.job()
    for index in range(3):
        factory.candidate(job, dedupe_key=f"dupe-{index}")

    statements: list[str] = []

    def _record(conn, cursor, statement, params, context, executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        assert client.get("/api/jobs").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    # The counts come from aggregates; nothing may select candidate columns.
    assert not any("candidates.raw" in s for s in statements), statements
