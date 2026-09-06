"""Job description intake, parsing, and screening-plan design."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, noload

from app.api.deps import db_session, get_job
from app.core.errors import ValidationFailure
from app.models import Call, Campaign, Candidate, CandidateStatus, Job, JobStatus
from app.schemas.common import Ack
from app.schemas.job import (
    JobCreate,
    JobCriteria,
    JobRead,
    JobSummary,
    JobUpdate,
    ParsePreview,
    ScreeningQuestion,
)
from app.services.jd_parser import parse_job_description
from app.services.screening import build_result_schema, design_screening_plan

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/parse", response_model=ParsePreview)
async def parse_only(payload: JobCreate) -> ParsePreview:
    """Parse a JD without saving it - powers the live preview in the composer."""
    criteria, parsed_by, warnings = await parse_job_description(
        payload.description, title_hint=payload.title, location_hint=payload.location
    )
    plan, designed_by = await design_screening_plan(
        criteria, description=payload.description, company=payload.company
    )
    if designed_by == "heuristic" and parsed_by == "llm":
        warnings.append("Screening questions fell back to the deterministic designer.")
    return ParsePreview(
        criteria=criteria, screening_plan=plan, parsed_by=parsed_by, warnings=warnings
    )


@router.post("", response_model=JobRead, status_code=201)
async def create_job(payload: JobCreate, db: Session = Depends(db_session)) -> Job:
    criteria, parsed_by, _ = await parse_job_description(
        payload.description, title_hint=payload.title, location_hint=payload.location
    )
    plan, _ = await design_screening_plan(
        criteria, description=payload.description, company=payload.company
    )

    job = Job(
        title=payload.title or criteria.role_title or "Untitled role",
        company=payload.company,
        location=payload.location
        or (criteria.locations[0] if criteria.locations else None),
        description=payload.description,
        status=JobStatus.PARSED,
        criteria=criteria.model_dump(),
        screening_questions=[q.model_dump() for q in plan.questions],
        result_schema=plan.result_schema,
        parsed_by=parsed_by,
    )
    db.add(job)
    db.flush()
    return job


@router.get("", response_model=list[JobSummary])
def list_jobs(
    db: Session = Depends(db_session), limit: int = Query(default=50, ge=1, le=200)
) -> list[JobSummary]:
    # Job.candidates is selectin-loaded; JobSummary uses none of it, and the
    # counts come from _counts_by_job, so skip the extra fetch entirely.
    jobs = list(
        db.scalars(
            select(Job)
            .options(noload(Job.candidates))
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
    )
    if not jobs:
        return []

    ids = [j.id for j in jobs]
    counts = _counts_by_job(db, ids)
    return [
        JobSummary(
            **{
                **JobSummary.model_validate(job).model_dump(),
                **counts.get(job.id, {}),
            }
        )
        for job in jobs
    ]


def _counts_by_job(db: Session, job_ids: list[str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {jid: {} for jid in job_ids}

    rows = db.execute(
        select(Candidate.job_id, func.count(Candidate.id))
        .where(Candidate.job_id.in_(job_ids))
        .group_by(Candidate.job_id)
    ).all()
    for job_id, count in rows:
        out[job_id]["candidate_count"] = count

    rows = db.execute(
        select(Candidate.job_id, func.count(Candidate.id))
        .where(Candidate.job_id.in_(job_ids))
        .where(Candidate.status == CandidateStatus.SHORTLISTED)
        .group_by(Candidate.job_id)
    ).all()
    for job_id, count in rows:
        out[job_id]["shortlisted_count"] = count

    rows = db.execute(
        select(Campaign.job_id, func.count(Campaign.id))
        .where(Campaign.job_id.in_(job_ids))
        .group_by(Campaign.job_id)
    ).all()
    for job_id, count in rows:
        out[job_id]["campaign_count"] = count

    rows = db.execute(
        select(Campaign.job_id, func.count(Call.id))
        .join(Call, Call.campaign_id == Campaign.id)
        .where(Campaign.job_id.in_(job_ids))
        .group_by(Campaign.job_id)
    ).all()
    for job_id, count in rows:
        out[job_id]["call_count"] = count
    return out


@router.get("/{job_id}", response_model=JobRead)
def get_one(job: Job = Depends(get_job)) -> Job:
    return job


@router.patch("/{job_id}", response_model=JobRead)
async def update_job(
    payload: JobUpdate, job: Job = Depends(get_job), db: Session = Depends(db_session)
) -> Job:
    data = payload.model_dump(exclude_unset=True)
    for field in ("title", "company", "location", "description"):
        if data.get(field) is not None:
            setattr(job, field, data[field])

    if payload.criteria is not None:
        job.criteria = payload.criteria.model_dump()
    if payload.screening_questions is not None:
        if not payload.screening_questions:
            raise ValidationFailure("A screening plan needs at least one question.")
        job.screening_questions = [q.model_dump() for q in payload.screening_questions]
        job.result_schema = build_result_schema(payload.screening_questions)
    db.flush()
    return job


@router.post("/{job_id}/reparse", response_model=JobRead)
async def reparse(
    job: Job = Depends(get_job), db: Session = Depends(db_session)
) -> Job:
    criteria, parsed_by, _ = await parse_job_description(
        job.description, title_hint=job.title, location_hint=job.location
    )
    plan, _ = await design_screening_plan(
        criteria, description=job.description, company=job.company
    )
    job.criteria = criteria.model_dump()
    job.screening_questions = [q.model_dump() for q in plan.questions]
    job.result_schema = plan.result_schema
    job.parsed_by = parsed_by
    job.status = JobStatus.PARSED
    db.flush()
    return job


@router.get("/{job_id}/screening-plan")
def screening_plan(job: Job = Depends(get_job)) -> dict[str, Any]:
    """The agent script this job would produce, for review before launch."""
    from app.services.screening import build_plan

    criteria = JobCriteria(**(job.criteria or {}))
    questions = [ScreeningQuestion(**q) for q in (job.screening_questions or [])]
    if not questions:
        raise ValidationFailure("This job has no screening questions yet.")
    plan = build_plan(criteria, questions, company=job.company)
    return plan.model_dump()


@router.delete("/{job_id}", response_model=Ack)
def delete_job(job: Job = Depends(get_job), db: Session = Depends(db_session)) -> Ack:
    db.delete(job)
    return Ack(message=f"Deleted job {job.id}")
