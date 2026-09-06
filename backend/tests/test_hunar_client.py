"""The Hunar API client: auth, paths, payload coercion, retries, error text.

Every request is intercepted by respx; the session-wide socket guard in
``conftest`` fails the test if anything escapes.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import tenacity

from app.core.errors import ProviderNotConfigured, UpstreamError
from app.services.hunar import HunarClient, _as_str, get_hunar_client

from tests.conftest import AGENTS_URL, CALLS_URL, FAKE_HUNAR_KEY, HUNAR_HOST

TEST_KEY = "hunar_va_test_sk_client_suite_0000"

AGENT_KWARGS: dict[str, Any] = {
    "name": "HireFlow AI — Senior Backend Engineer",
    "voice_persona": "NEHA",
    "agent_prompt": "You are screening for {job_title} at {company}.",
    "objective": "Screen candidates.",
    "introduction": "Hi {callee_name}!",
    "result_prompt": "Extract only what was said.",
    "result_schema": {"consent_to_continue": "boolean — did they agree?"},
}


@pytest.fixture
def hunar() -> HunarClient:
    return HunarClient(api_key=TEST_KEY)


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the retry tests fast without changing how many attempts happen."""
    monkeypatch.setattr(
        "app.services.hunar.wait_exponential", lambda **_: tenacity.wait_none()
    )


# ===========================================================================
# Auth + routing
# ===========================================================================
async def test_sends_x_api_key_and_never_an_authorization_header(
    hunar: HunarClient, respx_mock
) -> None:
    route = respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(201, json={"id": "agent_1", "status": "ACTIVE"})
    )

    await hunar.create_agent(**AGENT_KWARGS)

    request = route.calls.last.request
    assert request.headers["X-API-Key"] == TEST_KEY
    assert "authorization" not in request.headers, "Hunar authenticates by X-API-Key"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Accept"] == "application/json"


@pytest.mark.parametrize(
    ("call", "method", "url"),
    [
        (lambda c: c.create_agent(**AGENT_KWARGS), "POST", AGENTS_URL),
        (lambda c: c.list_agents(), "GET", AGENTS_URL),
        (lambda c: c.get_agent("agent_1"), "GET", f"{AGENTS_URL}agent_1/"),
        (
            lambda c: c.create_call(
                agent_id="a", callee_name="Priya", mobile_number="+919876543210"
            ),
            "POST",
            CALLS_URL,
        ),
        (lambda c: c.get_call("call_1"), "GET", f"{CALLS_URL}call_1/"),
        (lambda c: c.list_calls(), "GET", CALLS_URL),
        (lambda c: c.list_numbers(), "GET", f"{HUNAR_HOST}/external/v1/numbers/"),
    ],
)
async def test_hits_the_exact_documented_paths(
    hunar: HunarClient, respx_mock, call, method: str, url: str
) -> None:
    route = respx_mock.request(method, url).mock(
        return_value=httpx.Response(200, json={"id": "x"})
    )
    await call(hunar)
    assert route.called
    assert route.calls.last.request.url.path == httpx.URL(url).path
    assert route.calls.last.request.url.path.startswith("/external/v1/")


async def test_no_key_raises_before_any_request_is_made(respx_mock) -> None:
    unconfigured = HunarClient(api_key="")
    assert unconfigured.configured is False
    with pytest.raises(ProviderNotConfigured) as exc:
        await unconfigured.create_agent(**AGENT_KWARGS)
    assert "HUNAR_API_KEY" in exc.value.message
    assert not respx_mock.calls, "no request may leave without a key"


def test_the_default_client_picks_up_the_configured_key(hunar_key: str) -> None:
    client = get_hunar_client()
    assert client.api_key == FAKE_HUNAR_KEY == hunar_key
    assert client.base_url == HUNAR_HOST
    assert client._url("/calls/") == CALLS_URL


# ===========================================================================
# create_call payload
# ===========================================================================
async def test_custom_data_values_are_coerced_to_strings(
    hunar: HunarClient, respx_mock
) -> None:
    route = respx_mock.post(CALLS_URL).mock(
        return_value=httpx.Response(201, json={"id": "call_1", "status": "NOT_STARTED"})
    )

    await hunar.create_call(
        agent_id="agent_1",
        callee_name="Priya",
        mobile_number="+919876543210",
        custom_data={
            "job_title": "Backend Engineer",
            "years": 7,
            "rate": 4.5,
            "urgent": True,
            "not_urgent": False,
            "skills": ["Python", "Kafka"],
            "meta": {"team": "payments"},
            "dropped": None,
        },
    )

    body = json.loads(route.calls.last.request.content)
    assert body["custom_data"] == {
        "job_title": "Backend Engineer",
        "years": "7",
        "rate": "4.5",
        "urgent": "yes",
        "not_urgent": "no",
        "skills": "Python, Kafka",
        "meta": '{"team": "payments"}',
    }
    assert all(isinstance(v, str) for v in body["custom_data"].values())
    assert "dropped" not in body["custom_data"], "None values are omitted, not 'None'"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("already a string", "already a string"),
        (True, "yes"),
        (False, "no"),
        (7, "7"),
        (4.5, "4.5"),
        (["a", 1], "a, 1"),
        (("a", "b"), "a, b"),
        ({"k": "v"}, '{"k": "v"}'),
    ],
)
def test_as_str_coercion_table(value: Any, expected: str) -> None:
    assert _as_str(value) == expected


async def test_request_id_is_truncated_to_64_characters(
    hunar: HunarClient, respx_mock
) -> None:
    route = respx_mock.post(CALLS_URL).mock(
        return_value=httpx.Response(201, json={"id": "call_1"})
    )
    long_id = "rc-" + "x" * 200

    await hunar.create_call(
        agent_id="agent_1",
        callee_name="Priya",
        mobile_number="+919876543210",
        request_id=long_id,
    )

    body = json.loads(route.calls.last.request.content)
    assert len(body["request_id"]) == 64
    assert body["request_id"] == long_id[:64]


async def test_from_phone_number_is_omitted_when_none(
    hunar: HunarClient, respx_mock
) -> None:
    """Sending a null ``from_phone_number`` makes Hunar reject the call."""
    route = respx_mock.post(CALLS_URL).mock(
        return_value=httpx.Response(201, json={"id": "call_1"})
    )

    await hunar.create_call(
        agent_id="agent_1",
        callee_name="Priya",
        mobile_number="+919876543210",
        from_phone_number=None,
        timezone=None,
        callback_config=None,
        retry_config=None,
        guardrails=None,
        custom_data=None,
    )

    body = json.loads(route.calls.last.request.content)
    assert set(body) == {"agent_id", "callee_name", "mobile_number"}
    assert "from_phone_number" not in body


async def test_from_phone_number_is_sent_when_provided(
    hunar: HunarClient, respx_mock
) -> None:
    route = respx_mock.post(CALLS_URL).mock(
        return_value=httpx.Response(201, json={"id": "call_1"})
    )
    await hunar.create_call(
        agent_id="agent_1",
        callee_name="Priya",
        mobile_number="+919876543210",
        from_phone_number="+911140000000",
    )
    assert json.loads(route.calls.last.request.content)["from_phone_number"] == (
        "+911140000000"
    )


async def test_agent_name_is_truncated_to_64_characters(
    hunar: HunarClient, respx_mock
) -> None:
    route = respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(201, json={"id": "agent_1"})
    )
    await hunar.create_agent(**{**AGENT_KWARGS, "name": "N" * 300})
    assert len(json.loads(route.calls.last.request.content)["name"]) == 64


async def test_none_query_params_are_dropped(hunar: HunarClient, respx_mock) -> None:
    route = respx_mock.get(CALLS_URL).mock(return_value=httpx.Response(200, json={}))
    await hunar.list_calls(page=2, page_size=500, agent_id=None, status=None)

    params = route.calls.last.request.url.params
    assert params["page"] == "2"
    assert params["page_size"] == "200", "page_size is capped"
    assert "agent_id" not in params
    assert "status" not in params


# ===========================================================================
# Retries
# ===========================================================================
@pytest.mark.parametrize("status", [500, 502, 503, 504, 429, 408, 425])
async def test_retries_transient_failures_then_gives_up_with_upstream_error(
    hunar: HunarClient, respx_mock, status: int
) -> None:
    route = respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(status, json={"message": "try again"})
    )

    with pytest.raises(UpstreamError) as exc:
        await hunar.create_agent(**AGENT_KWARGS)

    assert route.call_count == 3, "three attempts, then surrender"
    assert exc.value.upstream_status == status
    assert exc.value.provider == "hunar"
    assert exc.value.status_code == 502, "a bad upstream is a 502 to our clients"


async def test_a_retry_that_eventually_succeeds_returns_the_payload(
    hunar: HunarClient, respx_mock
) -> None:
    route = respx_mock.post(AGENTS_URL).mock(
        side_effect=[
            httpx.Response(500, json={"message": "boom"}),
            httpx.Response(429, json={"message": "slow down"}),
            httpx.Response(201, json={"id": "agent_1", "status": "ACTIVE"}),
        ]
    )

    agent = await hunar.create_agent(**AGENT_KWARGS)

    assert agent["id"] == "agent_1"
    assert route.call_count == 3


async def test_network_errors_are_retried_then_surface_as_upstream_error(
    hunar: HunarClient, respx_mock
) -> None:
    """The internal ``_Retryable`` marker must never escape the client.

    Callers (dispatch, the poller, ``ping``) only catch ``AppError``; leaking
    the retry plumbing turns an unreachable Hunar into an opaque HTTP 500.
    """
    route = respx_mock.post(AGENTS_URL).mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with pytest.raises(UpstreamError) as exc:
        await hunar.create_agent(**AGENT_KWARGS)

    assert route.call_count == 3
    assert exc.value.provider == "hunar"
    assert exc.value.status_code == 502
    assert "Could not reach Hunar" in exc.value.message


async def test_a_timeout_is_reported_as_an_upstream_error(
    hunar: HunarClient, respx_mock
) -> None:
    respx_mock.get(f"{CALLS_URL}call_1/").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )
    with pytest.raises(UpstreamError):
        await hunar.get_call("call_1")


async def test_ping_survives_an_unreachable_host(
    hunar: HunarClient, respx_mock
) -> None:
    respx_mock.get(AGENTS_URL).mock(side_effect=httpx.ConnectError("no route"))
    result = await hunar.ping()
    assert result["ok"] is False
    assert "Could not reach Hunar" in result["reason"]


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
async def test_client_errors_are_not_retried(
    hunar: HunarClient, respx_mock, status: int
) -> None:
    route = respx_mock.post(AGENTS_URL).mock(
        return_value=httpx.Response(status, json={"message": "nope"})
    )
    with pytest.raises(UpstreamError):
        await hunar.create_agent(**AGENT_KWARGS)
    assert route.call_count == 1, "a 4xx will not fix itself"


# ===========================================================================
# Error rendering
# ===========================================================================
async def test_renders_the_hunar_error_envelope_into_one_sentence(
    hunar: HunarClient, respx_mock
) -> None:
    respx_mock.post(CALLS_URL).mock(
        return_value=httpx.Response(
            422,
            json={
                "success": False,
                "message": "Validation failed",
                "details": [
                    {"field_name": "mobile_number", "error_msg": "Invalid number"},
                    {"field_name": "custom_data", "error_msg": "Missing job_title"},
                ],
            },
        )
    )

    with pytest.raises(UpstreamError) as exc:
        await hunar.create_call(
            agent_id="agent_1", callee_name="Priya", mobile_number="bad"
        )

    message = exc.value.message
    assert "Hunar rejected the request payload (422)." in message
    assert "Validation failed" in message
    assert "mobile_number: Invalid number" in message
    assert "custom_data: Missing job_title" in message
    # The raw envelope is preserved for the diagnostics panel.
    assert exc.value.details["details"][0]["field_name"] == "mobile_number"
    assert exc.value.to_dict()["error"]["provider"] == "hunar"
    assert exc.value.to_dict()["error"]["upstream_status"] == 422


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (401, "rejected the API key (401)"),
        (402, "subscription is expired or calling minutes are exhausted (402)"),
        (403, "denied this request (403)"),
        (404, "resource not found (404)"),
        (422, "rejected the request payload (422)"),
        (418, "failed with HTTP 418"),
    ],
)
async def test_status_specific_messages(
    hunar: HunarClient, respx_mock, status: int, fragment: str
) -> None:
    respx_mock.get(f"{CALLS_URL}call_1/").mock(
        return_value=httpx.Response(status, json={"message": "context"})
    )
    with pytest.raises(UpstreamError) as exc:
        await hunar.get_call("call_1")
    assert fragment in exc.value.message
    assert "context" in exc.value.message


async def test_a_non_json_error_body_is_still_readable(
    hunar: HunarClient, respx_mock
) -> None:
    respx_mock.post(CALLS_URL).mock(
        return_value=httpx.Response(403, text="<html>Forbidden by the WAF</html>")
    )
    with pytest.raises(UpstreamError) as exc:
        await hunar.create_call(
            agent_id="a", callee_name="P", mobile_number="+919876543210"
        )
    assert "Forbidden by the WAF" in exc.value.message


async def test_the_error_message_never_contains_the_api_key(
    hunar: HunarClient, respx_mock
) -> None:
    respx_mock.post(CALLS_URL).mock(
        return_value=httpx.Response(401, json={"message": "Invalid API key"})
    )
    with pytest.raises(UpstreamError) as exc:
        await hunar.create_call(
            agent_id="a", callee_name="P", mobile_number="+919876543210"
        )
    assert TEST_KEY not in exc.value.message
    assert TEST_KEY not in json.dumps(exc.value.to_dict())


# ===========================================================================
# Responses without a body
# ===========================================================================
async def test_a_204_response_returns_none(hunar: HunarClient, respx_mock) -> None:
    respx_mock.put(f"{AGENTS_URL}agent_1/").mock(return_value=httpx.Response(204))
    assert await hunar.update_agent("agent_1", name="Renamed") is None


async def test_update_agent_drops_none_fields(hunar: HunarClient, respx_mock) -> None:
    route = respx_mock.put(f"{AGENTS_URL}agent_1/").mock(
        return_value=httpx.Response(200, json={"id": "agent_1"})
    )
    await hunar.update_agent("agent_1", name="Renamed", objective=None)
    assert json.loads(route.calls.last.request.content) == {"name": "Renamed"}


# ===========================================================================
# ping()
# ===========================================================================
async def test_ping_reports_ok_and_only_a_masked_key(
    hunar: HunarClient, respx_mock
) -> None:
    respx_mock.get(AGENTS_URL).mock(
        return_value=httpx.Response(200, json={"count": 3, "results": []})
    )
    result = await hunar.ping()
    assert result["ok"] is True
    assert result["agents_visible"] == 3
    assert result["key"] != TEST_KEY
    assert TEST_KEY not in json.dumps(result)


async def test_ping_reports_an_upstream_failure_without_raising(
    hunar: HunarClient, respx_mock
) -> None:
    respx_mock.get(AGENTS_URL).mock(
        return_value=httpx.Response(401, json={"message": "Invalid API key"})
    )
    result = await hunar.ping()
    assert result["ok"] is False
    assert result["status"] == 401
    assert "rejected the API key" in result["reason"]


async def test_ping_without_a_key_does_not_touch_the_network(respx_mock) -> None:
    result = await HunarClient(api_key="").ping()
    assert result == {
        "ok": False,
        "reason": (
            "HUNAR_API_KEY is not set. Add it to the backend environment to place calls."
        ),
        "key": "",
    }
    assert not respx_mock.calls


# ===========================================================================
# Bulk
# ===========================================================================
async def test_bulk_calls_coerce_custom_data_and_set_the_hygiene_flags(
    hunar: HunarClient, respx_mock
) -> None:
    route = respx_mock.post(f"{CALLS_URL}bulk/").mock(
        return_value=httpx.Response(202, json={"accepted": 2})
    )

    await hunar.create_bulk_calls(
        agent_id="agent_1",
        recipients=[
            {
                "callee_name": "Priya",
                "mobile_number": "+919876543210",
                "custom_data": {"years": 7, "skip": None},
            },
            {"callee_name": "Rohan", "mobile_number": "+919876543211"},
        ],
        request_id="rc-" + "y" * 100,
    )

    body = json.loads(route.calls.last.request.content)
    assert body["data"][0]["custom_data"] == {"years": "7"}
    assert "custom_data" not in body["data"][1]
    assert body["remove_invalid_rows"] is True
    assert body["remove_duplicate_phone_numbers"] is True
    assert len(body["request_id"]) == 64
