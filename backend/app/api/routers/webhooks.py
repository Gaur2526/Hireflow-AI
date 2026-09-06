"""Hunar callback receivers.

Hunar signs every callback with HMAC-SHA256 over ``f"{timestamp}." + raw_body``,
keyed by the **API key itself**, base64-encoded in ``X-Hunar-Signature``.

Hunar POSTs four event types, each to its own URL:

* ``call_status_updated``  -> /webhooks/hunar/status
* ``call_recording_done``  -> /webhooks/hunar/recording
* ``call_result_done``     -> /webhooks/hunar/result
* ``call_summary``         -> /webhooks/hunar/summary

They all carry ``call_id`` and are merged into the same ``Call`` row, so
arrival order does not matter and a missed callback is repaired by the poller.
Every request is logged verbatim (with its signature verdict) for debugging.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.config import settings
from app.core.logging import get_logger
from app.models import Call, WebhookEvent
from app.services.campaigns import apply_call_payload
from app.services.webhook_security import verify_signature

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks/hunar", tags=["webhooks"])


async def _receive(
    request: Request,
    db: Session,
    signature: str | None,
    timestamp: str | None,
    expected_event: str,
) -> dict[str, Any]:
    body = await request.body()
    verdict = verify_signature(
        secret=settings.webhook_signing_secret,
        body=body,
        signature_header=signature,
        timestamp_header=timestamp,
    )

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"raw": payload}

    event = WebhookEvent(
        event_type=str(payload.get("event_type") or expected_event),
        hunar_call_id=str(payload.get("call_id") or payload.get("id") or "") or None,
        signature_valid=verdict.valid,
        payload=payload,
        note=verdict.as_note,
    )
    db.add(event)

    # A configured secret is enforced. Without one we still accept callbacks so
    # the flow is demonstrable, but every row is flagged as unverified.
    if settings.webhook_signing_secret and not verdict.valid:
        log.warning(
            "webhook.rejected", event_type=event.event_type, reason=verdict.reason
        )
        db.flush()
        return {"accepted": False, "reason": verdict.reason}

    call = _find_call(db, payload)
    if call is None:
        event.note = f"{event.note}; no matching call".strip("; ")
        db.flush()
        log.warning("webhook.unmatched", call_id=event.hunar_call_id)
        return {"accepted": True, "matched": False}

    changed = apply_call_payload(call, _normalise(payload), source="webhook")
    event.handled = True
    db.flush()
    log.info(
        "webhook.applied",
        # NB: not ``event=`` - structlog already binds that name to the message.
        event_type=event.event_type,
        call_id=call.id,
        changed=changed,
        signature_valid=verdict.valid,
    )
    return {"accepted": True, "matched": True, "changed": changed}


def _find_call(db: Session, payload: dict[str, Any]) -> Call | None:
    hunar_id = payload.get("call_id") or payload.get("id")
    if hunar_id:
        call = db.scalar(select(Call).where(Call.hunar_call_id == str(hunar_id)))
        if call:
            return call
    request_id = payload.get("request_id")
    if request_id:
        return db.scalar(select(Call).where(Call.request_id == str(request_id)))
    return None


def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
    """Webhook bodies use ``call_id``; the REST call object uses ``id``."""
    data = dict(payload)
    if "call_id" in data and "id" not in data:
        data["id"] = data["call_id"]
    return data


@router.post("/status")
async def call_status(
    request: Request,
    db: Session = Depends(db_session),
    x_hunar_signature: str | None = Header(default=None),
    x_hunar_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    return await _receive(
        request, db, x_hunar_signature, x_hunar_timestamp, "call_status_updated"
    )


@router.post("/recording")
async def call_recording(
    request: Request,
    db: Session = Depends(db_session),
    x_hunar_signature: str | None = Header(default=None),
    x_hunar_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    return await _receive(
        request, db, x_hunar_signature, x_hunar_timestamp, "call_recording_done"
    )


@router.post("/result")
async def call_result(
    request: Request,
    db: Session = Depends(db_session),
    x_hunar_signature: str | None = Header(default=None),
    x_hunar_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    return await _receive(
        request, db, x_hunar_signature, x_hunar_timestamp, "call_result_done"
    )


@router.post("/summary")
async def call_summary(
    request: Request,
    db: Session = Depends(db_session),
    x_hunar_signature: str | None = Header(default=None),
    x_hunar_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    return await _receive(
        request, db, x_hunar_signature, x_hunar_timestamp, "call_summary"
    )


@router.get("/events")
def recent_events(
    db: Session = Depends(db_session),
    limit: int = Query(default=25, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Recent callbacks - shown in the app's diagnostics panel."""
    events = list(
        db.scalars(
            select(WebhookEvent).order_by(WebhookEvent.created_at.desc()).limit(limit)
        )
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "hunar_call_id": e.hunar_call_id,
            "signature_valid": e.signature_valid,
            "handled": e.handled,
            "note": e.note,
            "received_at": e.created_at,
        }
        for e in events
    ]
