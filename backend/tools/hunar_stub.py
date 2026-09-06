"""A local stand-in for the Hunar Voice API.

Lets you exercise the full pipeline - create agent, dispatch calls, receive
signed webhooks, render answers - without placing a single real phone call.
It mimics the documented contract closely enough to be a real test:

* ``X-API-Key`` is required, and a wrong key gets Hunar's own 401 body.
* ``custom_variables`` is derived from ``{tokens}`` in ``agent_prompt`` +
  ``introduction``, minus the system tokens - exactly as the real API does.
* ``POST /calls/`` rejects with 422 when ``custom_data`` misses a declared
  variable, and rejects non-string ``custom_data`` values.
* Each call then progresses RINGING -> IN_PROGRESS -> COMPLETED on a timer,
  posting the four webhook events with genuine
  ``base64(HMAC-SHA256(api_key, f"{timestamp}." + body))`` signatures.
* Answers are synthesised against the agent's own ``result_schema``.

Usage:
    .venv/bin/python tools/hunar_stub.py --port 8910
    # then, in backend/.env:
    #   HUNAR_BASE_URL=http://127.0.0.1:8910
    #   PUBLIC_BASE_URL=http://127.0.0.1:8000     (webhooks post straight back)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import random
import re
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

SYSTEM_VARIABLES = {"callee_name", "persona_name", "mobile_number", "greeting", "current_time"}

app = FastAPI(title="Hunar stub", docs_url="/docs")

AGENTS: dict[str, dict[str, Any]] = {}
CALLS: dict[str, dict[str, Any]] = {}
API_KEY = "stub-key"
#: Seconds between simulated call-state transitions.
TICK = 2.0


def _error(status: int, message: str, details: list[dict[str, str]] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "message": message, "details": details or []},
    )


def _auth(key: str | None) -> JSONResponse | None:
    if not key:
        return _error(401, "Missing API key")
    if key != API_KEY:
        return _error(401, "Invalid API key")
    return None


def _placeholders(*texts: str) -> list[str]:
    found: set[str] = set()
    for text in texts:
        found.update(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", text or ""))
    return sorted(found - SYSTEM_VARIABLES)


@app.post("/external/v1/agents/")
async def create_agent(request: Request, x_api_key: str | None = Header(default=None)) -> Any:
    if (denied := _auth(x_api_key)) is not None:
        return denied
    body = await request.json()

    for field in ("name", "voice_persona", "agent_prompt", "objective", "introduction", "result_schema"):
        if not body.get(field):
            return _error(422, "Validation Failed", [{"field_name": field, "error_msg": "required"}])

    schema = body["result_schema"]
    if not isinstance(schema, dict) or not schema:
        return _error(422, "Validation Failed", [{"field_name": "result_schema", "error_msg": "must be a non-empty object"}])
    if "properties" in schema and "type" in schema:
        # The real API accepts this and then corrupts extraction; be louder.
        return _error(422, "Validation Failed", [
            {"field_name": "result_schema", "error_msg": "send a flat by-example object, not a JSON Schema envelope"}
        ])

    agent_id = str(uuid.uuid4())
    AGENTS[agent_id] = {
        "id": agent_id,
        "status": "ACTIVE",
        "agent_code": f"ST{len(AGENTS) + 1:03d}",
        "custom_variables": _placeholders(body["agent_prompt"], body["introduction"]),
        "required_variables": ["callee_name", "mobile_number"],
        "result_variables": list(schema),
        **body,
    }
    return AGENTS[agent_id]


@app.get("/external/v1/agents/")
async def list_agents(page: int = 1, page_size: int = 20, x_api_key: str | None = Header(default=None)) -> Any:
    if (denied := _auth(x_api_key)) is not None:
        return denied
    rows = list(AGENTS.values())
    start = (page - 1) * page_size
    return {"count": len(rows), "next": None, "previous": None, "results": rows[start : start + page_size]}


@app.get("/external/v1/agents/{agent_id}/")
async def get_agent(agent_id: str, x_api_key: str | None = Header(default=None)) -> Any:
    if (denied := _auth(x_api_key)) is not None:
        return denied
    agent = AGENTS.get(agent_id)
    return agent if agent else _error(404, "Agent not found")


@app.get("/external/v1/numbers/")
async def list_numbers(x_api_key: str | None = Header(default=None)) -> Any:
    if (denied := _auth(x_api_key)) is not None:
        return denied
    return {"count": 0, "next": None, "previous": None, "results": []}


@app.post("/external/v1/calls/")
async def create_call(request: Request, x_api_key: str | None = Header(default=None)) -> Any:
    if (denied := _auth(x_api_key)) is not None:
        return denied
    body = await request.json()

    agent = AGENTS.get(str(body.get("agent_id")))
    if agent is None:
        return _error(404, "Active agent version not found.")

    custom = body.get("custom_data") or {}
    bad = [k for k, v in custom.items() if not isinstance(v, str)]
    if bad:
        return _error(422, "Validation Failed", [
            {"field_name": "custom_data", "error_msg": f"values must be strings: {bad}"}
        ])
    missing = set(agent["custom_variables"]) - set(custom)
    if missing:
        return _error(422, "Validation Failed", [
            {"field_name": "custom_data", "error_msg": f"Custom data keys are not present: {missing}"}
        ])

    call_id = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    CALLS[call_id] = {
        "id": call_id,
        "request_id": body.get("request_id") or call_id[:16],
        "agent_id": agent["id"],
        "callee_name": body["callee_name"],
        "mobile_number": body["mobile_number"],
        "status": "NOT_STARTED",
        "lifecycle_status": "NOT_STARTED",
        "call_type": "INDIVIDUAL",
        "language": agent.get("language", "ENGLISH"),
        "timezone": body.get("timezone") or "Asia/Kolkata",
        "custom_data": custom,
        "system_data": {
            "greeting": "Good evening",
            "callee_name": body["callee_name"],
            "current_time": now,
            "persona_name": agent.get("persona_name") or "NEHA",
            "mobile_number": body["mobile_number"],
        },
        "duration_seconds": 0,
        "duration_minutes": 0,
        "user_speech_duration": 0,
        "result": {},
        "recording_url": None,
        "engagement_status": None,
        "answered_by": None,
        "call_ended_by": None,
        "retry_count": 0,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "ended_at": None,
    }

    callbacks = body.get("callback_config") or {}
    asyncio.create_task(_run_call(call_id, agent, callbacks))
    return {k: CALLS[call_id][k] for k in ("id", "request_id", "status", "callee_name", "mobile_number", "timezone")}


@app.get("/external/v1/calls/{call_id}/")
async def get_call(call_id: str, x_api_key: str | None = Header(default=None)) -> Any:
    if (denied := _auth(x_api_key)) is not None:
        return denied
    call = CALLS.get(call_id)
    return call if call else _error(404, "Call not found")


@app.get("/external/v1/calls/")
async def list_calls(page: int = 1, page_size: int = 10, x_api_key: str | None = Header(default=None)) -> Any:
    if (denied := _auth(x_api_key)) is not None:
        return denied
    rows = list(CALLS.values())
    start = (page - 1) * page_size
    return {"count": len(rows), "next": None, "previous": None, "results": rows[start : start + page_size]}


# ---------------------------------------------------------------------------
async def _run_call(call_id: str, agent: dict[str, Any], callbacks: dict[str, str]) -> None:
    """Walk one call through its lifecycle, posting signed webhooks as it goes."""
    rng = random.Random(call_id)
    call = CALLS[call_id]

    # One call in six never connects, so the dashboard shows a realistic mix.
    connects = rng.random() > 0.17

    for status in ("RINGING", "IN_PROGRESS"):
        await asyncio.sleep(TICK)
        call["status"] = status
        call["lifecycle_status"] = "IN_PROGRESS"
        if status == "RINGING":
            call["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        await _post(callbacks.get("call_status_callback_url"), {
            "event_type": "call_status_updated",
            "call_id": call_id,
            "agent_id": agent["id"],
            "request_id": call["request_id"],
            "status": status,
            "lifecycle_status": "IN_PROGRESS",
            "to_number": call["mobile_number"],
        })
        if not connects:
            break

    await asyncio.sleep(TICK)
    if not connects:
        call.update({
            "status": "NOT_CONNECTED",
            "lifecycle_status": "NOT_CONNECTED",
            "answered_by": "UNKNOWN",
            "engagement_status": "NOT_ENGAGED",
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        })
        await _post(callbacks.get("call_status_callback_url"), {
            "event_type": "call_status_updated",
            "call_id": call_id,
            "agent_id": agent["id"],
            "request_id": call["request_id"],
            "status": "NOT_CONNECTED",
            "lifecycle_status": "NOT_CONNECTED",
            "answered_by": "UNKNOWN",
            "duration_seconds": 0,
        })
        return

    duration = rng.randint(58, 173)
    call.update({
        "status": "COMPLETED",
        "lifecycle_status": "COMPLETED",
        "answered_by": "HUMAN",
        "engagement_status": "ENGAGED",
        "call_ended_by": "AGENT",
        "duration_seconds": duration,
        "duration_minutes": round(duration / 60, 2),
        "user_speech_duration": round(duration * rng.uniform(0.3, 0.55), 1),
        "recording_url": f"https://recordings.example.invalid/{call_id}.wav",
        "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
    })
    await _post(callbacks.get("call_status_callback_url"), {
        "event_type": "call_status_updated",
        "call_id": call_id,
        "agent_id": agent["id"],
        "request_id": call["request_id"],
        "status": "COMPLETED",
        "lifecycle_status": "COMPLETED",
        "answered_by": "HUMAN",
        "duration_seconds": duration,
    })
    await _post(callbacks.get("call_recording_callback_url"), {
        "event_type": "call_recording_done",
        "call_id": call_id,
        "agent_id": agent["id"],
        "request_id": call["request_id"],
        "recording_url": call["recording_url"],
    })

    await asyncio.sleep(TICK)
    call["result"] = _synth_result(agent["result_schema"], call, rng)
    await _post(callbacks.get("call_result_callback_url"), {
        "event_type": "call_result_done",
        "call_id": call_id,
        "agent_id": agent["id"],
        "request_id": call["request_id"],
        "result": call["result"],
    })


def _synth_result(schema: dict[str, Any], call: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Build a plausible answer for each declared field, from its type hint."""
    keen = rng.random() > 0.3
    out: dict[str, Any] = {}
    for key, spec in schema.items():
        hint = str(spec).lower()
        if key == "consent_to_continue":
            out[key] = True
        elif key == "do_not_contact_requested":
            out[key] = rng.random() < 0.12
        elif key == "open_to_opportunity":
            out[key] = keen
        elif key == "current_role":
            out[key] = call["custom_data"].get("candidate_current_role") or "Senior Backend Engineer"
        elif key == "notice_period":
            out[key] = rng.choice(["30 days", "60 days", "90 days", "Immediate", "NOT DISCUSSED"])
        elif key == "best_time_to_talk":
            out[key] = rng.choice(["Weekday evenings after 7pm", "Saturday morning", "NOT AVAILABLE"])
        elif key == "recommended_next_step":
            out[key] = "schedule_interview" if keen else rng.choice(["recruiter_callback", "not_a_fit"])
        elif key == "screening_summary":
            out[key] = (
                f"{call['callee_name']} confirmed their current role and said they are "
                + ("open to hearing more about the position." if keen else "not looking to move right now.")
            )
        elif hint.startswith("boolean"):
            out[key] = keen
        elif hint.startswith("number"):
            out[key] = rng.randint(4, 12)
        elif "one of:" in hint:
            options = hint.split("one of:", 1)[1].split(".")[0]
            out[key] = rng.choice([o.strip() for o in options.split(",") if o.strip()])
        else:
            out[key] = rng.choice([
                "Yes, extensively in my current role.",
                "Some exposure, mostly in side projects.",
                "NOT AVAILABLE",
            ])
    return out


async def _post(url: str | None, payload: dict[str, Any]) -> None:
    if not url:
        return
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = base64.b64encode(
        hmac.new(API_KEY.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Hunar-Voice-Agents/1.0",
                    "X-Hunar-Timestamp": timestamp,
                    "X-Hunar-Signature": signature,
                },
            )
    except httpx.HTTPError as exc:  # a stub should never take the app down
        print(f"  webhook to {url} failed: {exc}")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8910)
    parser.add_argument("--api-key", default="stub-key")
    parser.add_argument("--tick", type=float, default=2.0, help="seconds between call-state transitions")
    args = parser.parse_args()

    API_KEY = args.api_key
    TICK = args.tick
    print(f"Hunar stub on http://127.0.0.1:{args.port}  (X-API-Key: {args.api_key})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
