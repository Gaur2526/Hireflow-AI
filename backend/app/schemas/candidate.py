from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, UTCDatetime


class CandidateRead(ORMModel):
    id: str
    job_id: str
    source: str
    external_id: str | None
    full_name: str
    first_name: str | None
    last_name: str | None
    headline: str | None
    title: str | None
    company: str | None
    location: str | None
    country_code: str | None
    linkedin_url: str | None
    email: str | None
    phone: str | None
    phone_is_valid: bool
    years_experience: float | None
    seniority: str | None
    skills: list[str]
    experience: list[dict[str, Any]]
    education: list[dict[str, Any]]
    fit_score: float
    fit_breakdown: dict[str, Any]
    fit_reasons: list[str]
    status: str
    created_at: UTCDatetime | None


class SearchRequest(BaseModel):
    """Override any part of the criteria before hitting the vendor."""

    provider: str | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    titles: list[str] | None = None
    must_have_skills: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    locations: list[str] | None = None
    countries: list[str] | None = None
    min_years: float | None = None
    max_years: float | None = None
    require_phone: bool = False
    replace_existing: bool = False


class SearchRunRead(ORMModel):
    id: str
    job_id: str
    provider: str
    query: dict[str, Any]
    total_available: int | None
    returned: int
    new_candidates: int
    latency_ms: int | None
    error: str | None
    created_at: UTCDatetime | None


class SearchResponse(BaseModel):
    run: SearchRunRead
    candidates: list[CandidateRead]
    warnings: list[str] = Field(default_factory=list)
    provider_label: str = ""


class ShortlistRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    status: str = "SHORTLISTED"


class CandidatePhoneUpdate(BaseModel):
    phone: str
