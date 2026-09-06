"""Voice screening campaigns and the results dashboard."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_campaign, get_job
from app.core.errors import NotFoundError
from app.models import Campaign, Candidate, CandidateStatus, Job
from app.schemas.campaign import (
    CallWithCandidate,
    CampaignCreate,
    CampaignDetail,
    CampaignRead,
    CampaignSummary,
    LaunchResponse,
)
from app.schemas.common import Ack
from app.services import campaigns as service

router = APIRouter(tags=["campaigns"])


@router.post("/jobs/{job_id}/campaigns", response_model=LaunchResponse, status_code=201)
async def create_and_launch(
    payload: CampaignCreate,
    job: Job = Depends(get_job),
    db: Session = Depends(db_session),
) -> LaunchResponse:
    campaign, skipped, warnings = await service.create_campaign(db, job, payload)

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
                exclude={"job_title", "stats"}
            ),
            job_title=titles.get(c.job_id, ""),
            stats=service.compute_stats(list(c.calls)),
        )
        for c in campaigns
    ]


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
            )
        )
    return rows


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
