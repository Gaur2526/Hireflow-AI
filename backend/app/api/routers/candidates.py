"""Candidate sourcing: run a people-search, score, shortlist."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_job
from app.core.errors import NotFoundError, UpstreamError, ValidationFailure
from app.core.logging import get_logger
from app.models import Candidate, CandidateStatus, Job, JobStatus, SearchRun
from app.schemas.candidate import (
    CandidatePhoneUpdate,
    CandidateRead,
    SearchRequest,
    SearchResponse,
    SearchRunRead,
    ShortlistRequest,
)
from app.schemas.common import Ack
from app.schemas.job import JobCriteria
from app.services.people_search.base import SearchResult, SourcedProfile
from app.services.people_search.registry import query_from_criteria, resolve_provider
from app.services.phone import normalise_phone
from app.services.scoring import score_profile

log = get_logger(__name__)

router = APIRouter(tags=["candidates"])


@router.post("/jobs/{job_id}/search", response_model=SearchResponse)
async def search_candidates(
    payload: SearchRequest,
    job: Job = Depends(get_job),
    db: Session = Depends(db_session),
) -> SearchResponse:
    criteria = JobCriteria(**(job.criteria or {}))
    query = query_from_criteria(
        criteria, limit=payload.limit, require_phone=payload.require_phone
    )
    # Operator overrides from the search panel.
    for field in (
        "titles",
        "must_have_skills",
        "nice_to_have_skills",
        "locations",
        "countries",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(query, field, value)
    if payload.min_years is not None:
        query.min_years = payload.min_years
    if payload.max_years is not None:
        query.max_years = payload.max_years
    if not query.titles:
        raise ValidationFailure(
            "No job titles to search for. Add at least one title to the criteria."
        )

    provider, warnings = resolve_provider(payload.provider)
    started = time.perf_counter()
    error: str | None = None
    try:
        result = await provider.search(query)
    except UpstreamError as exc:
        error = exc.message
        result = SearchResult(provider=provider.name, query_sent=query.model_dump())
        warnings.append(exc.message)
    warnings.extend(result.warnings)

    if payload.replace_existing:
        db.execute(
            delete(Candidate)
            .where(Candidate.job_id == job.id)
            .where(
                Candidate.status.in_(
                    [CandidateStatus.SOURCED, CandidateStatus.REJECTED]
                )
            )
        )
        db.flush()

    run = SearchRun(
        job_id=job.id,
        provider=provider.name,
        query=query.model_dump(exclude_none=True),
        total_available=result.total_available,
        returned=len(result.profiles),
        latency_ms=result.latency_ms or int((time.perf_counter() - started) * 1000),
        error=error,
    )
    db.add(run)
    db.flush()

    existing = {
        key
        for key in db.scalars(
            select(Candidate.dedupe_key).where(Candidate.job_id == job.id)
        )
    }
    created: list[Candidate] = []
    for profile in result.profiles:
        key = profile.dedupe_key
        if key in existing:
            continue
        existing.add(key)
        created.append(_to_candidate(job, run, profile, criteria))

    db.add_all(created)
    run.new_candidates = len(created)
    if created:
        job.status = JobStatus.SOURCED
    db.flush()

    everything = list(
        db.scalars(
            select(Candidate)
            .where(Candidate.job_id == job.id)
            .order_by(Candidate.fit_score.desc(), Candidate.full_name)
        )
    )
    return SearchResponse(
        run=SearchRunRead.model_validate(run),
        candidates=[CandidateRead.model_validate(c) for c in everything],
        warnings=warnings,
        provider_label=provider.label,
    )


def _to_candidate(
    job: Job, run: SearchRun, profile: SourcedProfile, criteria: JobCriteria
) -> Candidate:
    fit = score_profile(profile, criteria)
    phone, phone_valid = normalise_phone(
        profile.phone, default_region=profile.country_code
    )
    return Candidate(
        job_id=job.id,
        search_run_id=run.id,
        source=profile.source,
        external_id=profile.external_id,
        dedupe_key=profile.dedupe_key,
        full_name=profile.full_name,
        first_name=profile.first_name,
        last_name=profile.last_name,
        headline=profile.headline,
        title=profile.title,
        company=profile.company,
        location=profile.location,
        country_code=profile.country_code,
        linkedin_url=profile.linkedin_url,
        email=profile.email,
        phone=phone,
        phone_is_valid=phone_valid,
        years_experience=profile.years_experience,
        seniority=profile.seniority,
        skills=profile.skills,
        experience=profile.experience,
        education=profile.education,
        raw=profile.raw,
        fit_score=fit.score,
        fit_breakdown=fit.as_dict(),
        fit_reasons=fit.reasons,
        status=CandidateStatus.SOURCED,
    )


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateRead])
def list_candidates(
    job: Job = Depends(get_job),
    db: Session = Depends(db_session),
    status: str | None = Query(default=None),
    min_score: float = Query(default=0.0, ge=0, le=100),
    has_phone: bool | None = Query(default=None),
) -> list[Candidate]:
    stmt = select(Candidate).where(Candidate.job_id == job.id)
    if status:
        stmt = stmt.where(Candidate.status == status)
    if min_score:
        stmt = stmt.where(Candidate.fit_score >= min_score)
    if has_phone is True:
        stmt = stmt.where(Candidate.phone.is_not(None))
    elif has_phone is False:
        stmt = stmt.where(Candidate.phone.is_(None))
    return list(
        db.scalars(stmt.order_by(Candidate.fit_score.desc(), Candidate.full_name))
    )


@router.get("/jobs/{job_id}/searches", response_model=list[SearchRunRead])
def list_searches(
    job: Job = Depends(get_job), db: Session = Depends(db_session)
) -> list[SearchRun]:
    return list(
        db.scalars(
            select(SearchRun)
            .where(SearchRun.job_id == job.id)
            .order_by(SearchRun.created_at.desc())
        )
    )


@router.post("/jobs/{job_id}/shortlist", response_model=list[CandidateRead])
def shortlist(
    payload: ShortlistRequest,
    job: Job = Depends(get_job),
    db: Session = Depends(db_session),
) -> list[Candidate]:
    if payload.status not in {s.value for s in CandidateStatus}:
        raise ValidationFailure(f"Unknown candidate status '{payload.status}'.")
    candidates = list(
        db.scalars(
            select(Candidate)
            .where(Candidate.job_id == job.id)
            .where(Candidate.id.in_(payload.candidate_ids))
        )
    )
    if not candidates:
        raise NotFoundError("None of those candidates belong to this job.")
    for candidate in candidates:
        candidate.status = payload.status
    db.flush()
    return candidates


@router.patch("/candidates/{candidate_id}/phone", response_model=CandidateRead)
def set_phone(
    candidate_id: str,
    payload: CandidatePhoneUpdate,
    db: Session = Depends(db_session),
) -> Candidate:
    """Let an operator paste in a number the vendor did not return."""
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFoundError(f"Candidate {candidate_id} was not found.")
    phone, valid = normalise_phone(payload.phone, default_region=candidate.country_code)
    if not phone:
        raise ValidationFailure(f"'{payload.phone}' is not a phone number we can dial.")
    candidate.phone = phone
    candidate.phone_is_valid = valid
    if candidate.status == CandidateStatus.UNREACHABLE:
        candidate.status = CandidateStatus.SHORTLISTED
    db.flush()
    return candidate


@router.delete("/candidates/{candidate_id}", response_model=Ack)
def delete_candidate(candidate_id: str, db: Session = Depends(db_session)) -> Ack:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFoundError(f"Candidate {candidate_id} was not found.")
    db.delete(candidate)
    return Ack(message="Candidate removed")
