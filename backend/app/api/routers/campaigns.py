"""Voice screening campaigns and the results dashboard."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_campaign, get_job
from app.core.errors import NotFoundError, ValidationFailure
from app.models import Campaign, Candidate, CandidateStatus, Job
from app.schemas.campaign import (
    CallWithCandidate,
    CampaignCreate,
    CampaignCallPreview,
    CampaignDetail,
    CampaignRead,
    CampaignSummary,
    LaunchResponse,
    TranscriptLine,
)
from app.schemas.common import Ack
from app.services import campaigns as service

router = APIRouter(tags=["campaigns"])


@router.post("/jobs/{job_id}/campaigns", response_model=LaunchResponse, status_code=201)
async def create_and_launch(
    payload: CampaignCreate,
    response: Response,
    job: Job = Depends(get_job),
    db: Session = Depends(db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LaunchResponse:
    if payload.candidate_ids is not None and not payload.candidate_ids:
        raise ValidationFailure(
            "Select at least one shortlisted candidate before launching."
        )
    if idempotency_key:
        existing = db.scalar(
            select(Campaign).where(
                Campaign.job_id == job.id,
                Campaign.request_id == idempotency_key[:64],
            )
        )
        if existing:
            response.status_code = 200
            return LaunchResponse(
                campaign=CampaignRead.model_validate(existing),
                dispatched=0,
                skipped=[],
                warnings=["Duplicate launch request; returning the existing campaign."],
            )
    try:
        campaign, skipped, warnings = await service.create_campaign(
            db, job, payload, idempotency_key=idempotency_key
        )
    except IntegrityError:
        if not idempotency_key:
            raise
        db.rollback()
        existing = db.get(
            Campaign,
            hashlib.sha256(f"{job.id}:{idempotency_key}".encode()).hexdigest()[:36],
        )
        if existing is None:
            raise
        response.status_code = 200
        return LaunchResponse(
            campaign=CampaignRead.model_validate(existing),
            dispatched=0,
            skipped=[],
            warnings=["Duplicate launch request; returning the existing campaign."],
        )

    dispatched = 0
    if payload.dry_run:
        warnings.append("Dry run - the agent was created but no calls were placed.")
    else:
        (
            dispatched,
            dispatch_skipped,
            dispatch_warnings,
        ) = await service.dispatch_campaign(db, campaign)
        skipped.extend(dispatch_skipped)
        warnings.extend(dispatch_warnings)

    db.flush()
    return LaunchResponse(
        campaign=CampaignRead.model_validate(campaign),
        dispatched=dispatched,
        skipped=skipped,
        warnings=warnings,
    )


@router.post("/campaigns/{campaign_id}/dispatch", response_model=LaunchResponse)
async def dispatch(
    campaign: Campaign = Depends(get_campaign), db: Session = Depends(db_session)
) -> LaunchResponse:
    """Place any calls still sitting in PENDING (e.g. after a dry run)."""
    dispatched, skipped, warnings = await service.dispatch_campaign(db, campaign)
    return LaunchResponse(
        campaign=CampaignRead.model_validate(campaign),
        dispatched=dispatched,
        skipped=skipped,
        warnings=warnings,
    )


@router.get("/campaigns", response_model=list[CampaignSummary])
def list_campaigns(
    db: Session = Depends(db_session),
    job_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CampaignSummary]:
    stmt = select(Campaign).order_by(Campaign.created_at.desc()).limit(limit)
    if job_id:
        stmt = stmt.where(Campaign.job_id == job_id)
    campaigns = list(db.scalars(stmt))
    if not campaigns:
        return []

    titles = dict(
        db.execute(
            select(Job.id, Job.title).where(Job.id.in_([c.job_id for c in campaigns]))
        ).all()
    )
    return [
        CampaignSummary(
            **CampaignSummary.model_validate(c).model_dump(
                exclude={"job_title", "stats", "call_previews"}
            ),
            job_title=titles.get(c.job_id, ""),
            stats=service.compute_stats(list(c.calls)),
            call_previews=[
                CampaignCallPreview(
                    call_id=call.id,
                    candidate_name=call.candidate.full_name
                    if call.candidate
                    else "Candidate",
                    status=call.status,
                    duration_seconds=call.duration_seconds,
                    outcome=_call_outcome(call),
                )
                for call in sorted(
                    c.calls, key=lambda item: item.created_at, reverse=True
                )[:3]
            ],
        )
        for c in campaigns
    ]


def _call_outcome(call: Any) -> str:
    status = str(call.status)
    answered_by = str(call.answered_by or "").upper()
    if answered_by in {"VOICEMAIL", "MACHINE"}:
        return "Voicemail"
    if status == "NOT_CONNECTED":
        return "No answer"
    if status == "FAILED":
        return "Failed"
    if status == "CANCELLED":
        return "Cancelled"
    if status not in {"COMPLETED"}:
        return (
            "Live" if status in {"INITIATED", "RINGING", "IN_PROGRESS"} else "Pending"
        )

    result = call.result or {}
    for key in ("interested", "is_interested", "open_to_opportunity"):
        if key not in result:
            continue
        value = result[key]
        if isinstance(value, bool):
            return "Interested" if value else "Not interested"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"yes", "true", "interested", "high"}:
                return "Interested"
            if normalized in {"no", "false", "not interested", "low"}:
                return "Not interested"
    level = str(result.get("interest_level") or "").strip().lower()
    if level in {"high", "interested"}:
        return "Interested"
    if level in {"low", "not interested"}:
        return "Not interested"
    return "Completed"


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetail)
def campaign_detail(
    campaign: Campaign = Depends(get_campaign), db: Session = Depends(db_session)
) -> CampaignDetail:
    job = db.get(Job, campaign.job_id)
    calls = _calls_with_candidates(campaign)
    warnings: list[str] = []
    if campaign.error:
        warnings.append(campaign.error)
    if any(c.dialed_redirected for c in campaign.calls):
        warnings.append(
            "Demo redirect is active: calls were placed to the configured test "
            "number, not to the candidates."
        )
    return CampaignDetail(
        campaign=CampaignRead.model_validate(campaign),
        job_title=job.title if job else "",
        job_id=campaign.job_id,
        stats=service.compute_stats(list(campaign.calls)),
        calls=calls,
        answer_columns=service.answer_columns(campaign.result_schema),
        warnings=warnings,
    )


def _calls_with_candidates(campaign: Campaign) -> list[CallWithCandidate]:
    rows: list[CallWithCandidate] = []
    for call in sorted(
        campaign.calls,
        key=lambda c: (-(c.candidate.fit_score if c.candidate else 0), c.created_at),
    ):
        base = CallWithCandidate.model_validate(call).model_dump(
            exclude={
                "candidate_name",
                "candidate_title",
                "candidate_company",
                "candidate_linkedin",
                "candidate_fit_score",
                "transcript",
            }
        )
        candidate = call.candidate
        rows.append(
            CallWithCandidate(
                **base,
                candidate_name=candidate.full_name if candidate else "",
                candidate_title=candidate.title if candidate else None,
                candidate_company=candidate.company if candidate else None,
                candidate_linkedin=candidate.linkedin_url if candidate else None,
                candidate_fit_score=candidate.fit_score if candidate else 0.0,
                transcript=_transcript_from_raw(call.raw or {}),
            )
        )
    return rows


def _transcript_from_raw(raw: dict[str, Any]) -> list[TranscriptLine]:
    """Return transcript snippets when Hunar includes them in its call payload."""
    source: Any = next(
        (
            raw.get(key)
            for key in ("transcript", "transcript_segments", "messages", "conversation")
            if raw.get(key)
        ),
        None,
    )
    if isinstance(source, str):
        lines: list[TranscriptLine] = []
        for row in source.splitlines():
            text = row.strip()
            if not text:
                continue
            timestamp = None
            if text.startswith("[") and "]" in text:
                timestamp, text = text[1:].split("]", 1)
                text = text.strip()
            speaker = "Speaker"
            if ":" in text:
                maybe_speaker, remainder = text.split(":", 1)
                if maybe_speaker.strip().lower() in {
                    "agent",
                    "assistant",
                    "candidate",
                    "user",
                    "recruiter",
                }:
                    speaker, text = maybe_speaker.strip().title(), remainder.strip()
            if text:
                lines.append(
                    TranscriptLine(speaker=speaker, text=text, timestamp=timestamp)
                )
        return lines
    if isinstance(source, dict):
        source = source.get("segments") or source.get("messages") or source.get("items")
    if not isinstance(source, list):
        return []

    lines: list[TranscriptLine] = []
    for item in source:
        if isinstance(item, str):
            text = item.strip()
            speaker = "Speaker"
            if ":" in text:
                maybe_speaker, remainder = text.split(":", 1)
                if maybe_speaker.strip().lower() in {
                    "agent",
                    "assistant",
                    "candidate",
                    "user",
                    "recruiter",
                }:
                    speaker, text = maybe_speaker.strip(), remainder.strip()
            if text:
                lines.append(TranscriptLine(speaker=speaker, text=text))
            continue
        if not isinstance(item, dict):
            continue
        text = (
            item.get("text")
            or item.get("content")
            or item.get("message")
            or item.get("transcript")
        )
        if not isinstance(text, str) or not text.strip():
            continue
        speaker = (
            item.get("speaker")
            or item.get("role")
            or item.get("participant")
            or "Speaker"
        )
        timestamp = item.get("timestamp") or item.get("start_time") or item.get("time")
        if timestamp is None and isinstance(item.get("offset_seconds"), (int, float)):
            timestamp = str(item["offset_seconds"])
        lines.append(
            TranscriptLine(
                speaker=str(speaker).replace("_", " ").title(),
                text=text.strip(),
                timestamp=str(timestamp) if timestamp is not None else None,
            )
        )
    return lines


@router.post("/campaigns/{campaign_id}/sync", response_model=CampaignDetail)
async def sync(
    campaign: Campaign = Depends(get_campaign), db: Session = Depends(db_session)
) -> CampaignDetail:
    """Pull the latest status/results from Hunar right now."""
    await service.sync_campaign(db, campaign)
    db.flush()
    db.refresh(campaign)
    return campaign_detail(campaign=campaign, db=db)


@router.get(
    "/campaigns/{campaign_id}/calls/{call_id}", response_model=CallWithCandidate
)
def call_detail(
    call_id: str,
    campaign: Campaign = Depends(get_campaign),
) -> CallWithCandidate:
    for row in _calls_with_candidates(campaign):
        if row.id == call_id:
            return row
    raise NotFoundError(f"Call {call_id} is not part of this campaign.")


@router.get("/campaigns/{campaign_id}/export.csv")
def export_csv(campaign: Campaign = Depends(get_campaign)) -> StreamingResponse:
    """Flat export: one row per call, one column per screening answer."""
    columns = service.answer_columns(campaign.result_schema)
    header = [
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
        *[c["key"] for c in columns],
    ]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for call in sorted(
        campaign.calls,
        key=lambda c: -(c.candidate.fit_score if c.candidate else 0),
    ):
        candidate = call.candidate
        result = call.result or {}
        writer.writerow(
            [
                _cell(candidate.full_name if candidate else ""),
                _cell(candidate.title if candidate else ""),
                _cell(candidate.company if candidate else ""),
                _cell(candidate.linkedin_url if candidate else ""),
                candidate.fit_score if candidate else "",
                call.dialed_number or "",  # already E.164 from normalise_phone
                call.status,
                call.answered_by or "",
                call.duration_seconds or "",
                _cell(call.recording_url or ""),
                *[_cell(_flat(result.get(c["key"]))) for c in columns],
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_safe_filename(campaign.name)}"'
            )
        },
    )


def _safe_filename(name: str) -> str:
    """ASCII-only download name.

    HTTP header values are latin-1, and the default campaign name
    ("HireFlow AI — <job title>") carries an em dash, so the raw name cannot go
    into Content-Disposition.
    """
    folded = (
        unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", folded).strip("_")
    return f"{(slug or 'campaign')[:40]}_results.csv"


def _cell(value: str | None) -> str:
    """Neutralise spreadsheet formulas.

    Both the candidate fields and the screening answers come from outside the
    operator's control (a vendor payload, or whatever the person said on the
    phone), and Excel/Sheets execute a cell that starts with one of these.
    """
    text = value or ""
    return f"'{text}" if text and text[0] in "=+-@\t\r" else text


def _flat(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


@router.delete("/campaigns/{campaign_id}", response_model=Ack)
def delete_campaign(
    campaign: Campaign = Depends(get_campaign), db: Session = Depends(db_session)
) -> Ack:
    db.delete(campaign)
    return Ack(message="Campaign deleted (calls already placed are not cancelled)")


@router.get("/dashboard/overview")
def overview(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Numbers for the landing dashboard."""
    jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(5)))
    campaigns = list(
        db.scalars(select(Campaign).order_by(Campaign.created_at.desc()).limit(5))
    )
    stats = service.compute_stats_across(db)

    return {
        "totals": {
            "jobs": db.scalar(select(func.count(Job.id))) or 0,
            "candidates": db.scalar(select(func.count(Candidate.id))) or 0,
            "shortlisted": db.scalar(
                select(func.count(Candidate.id)).where(
                    Candidate.status == CandidateStatus.SHORTLISTED
                )
            )
            or 0,
            "campaigns": db.scalar(select(func.count(Campaign.id))) or 0,
            "calls": stats.total,
        },
        "call_stats": stats.model_dump(),
        "recent_jobs": [
            {
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "status": j.status,
                "created_at": j.created_at,
            }
            for j in jobs
        ],
        "recent_campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "job_id": c.job_id,
                "status": c.status,
                "created_at": c.created_at,
                "stats": service.compute_stats(list(c.calls)).model_dump(),
            }
            for c in campaigns
        ],
    }
