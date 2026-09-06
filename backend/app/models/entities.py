"""Persistence model for the sourcing -> screening -> results pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.enums import (
    CallStatus,
    CampaignStatus,
    CandidateSource,
    CandidateStatus,
    JobStatus,
)


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class Job(Base, TimestampMixin):
    """A job description plus everything derived from it."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=JobStatus.DRAFT, nullable=False
    )

    #: Structured search criteria extracted from the JD (see schemas.job.JobCriteria).
    criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Questions the voice agent must get answered on the call.
    screening_questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    #: Hunar `result_schema` derived from those questions -> becomes dashboard columns.
    result_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: How the criteria were produced: "llm" or "heuristic".
    parsed_by: Mapped[str | None] = mapped_column(String(32))

    candidates: Mapped[list[Candidate]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    campaigns: Mapped[list[Campaign]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    searches: Mapped[list[SearchRun]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class SearchRun(Base, TimestampMixin):
    """One people-search API call: what we asked, what came back, what it cost."""

    __tablename__ = "search_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    query: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total_available: Mapped[int | None] = mapped_column(Integer)
    returned: Mapped[int] = mapped_column(Integer, default=0)
    new_candidates: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship(back_populates="searches")


class Candidate(Base, TimestampMixin):
    """A normalised person record, provider-agnostic."""

    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("job_id", "dedupe_key", name="uq_candidate_job_dedupe"),
        Index("ix_candidate_job_score", "job_id", "fit_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    search_run_id: Mapped[str | None] = mapped_column(String(36))

    source: Mapped[str] = mapped_column(
        String(32), default=CandidateSource.MOCK, nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    #: Stable identity used to avoid inserting the same person twice per job.
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    headline: Mapped[str | None] = mapped_column(String(512))
    title: Mapped[str | None] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    country_code: Mapped[str | None] = mapped_column(String(8))
    linkedin_url: Mapped[str | None] = mapped_column(String(512))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    phone_is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    years_experience: Mapped[float | None] = mapped_column(Float)
    seniority: Mapped[str | None] = mapped_column(String(64))
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    experience: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    education: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    fit_score: Mapped[float] = mapped_column(Float, default=0.0)
    fit_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fit_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(
        String(32), default=CandidateStatus.SOURCED, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="candidates")
    calls: Mapped[list[Call]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class Campaign(Base, TimestampMixin):
    """A batch of voice screening calls driven by one Hunar agent."""

    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=CampaignStatus.DRAFT, nullable=False
    )

    hunar_agent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    #: Exactly what we POSTed to /agents/ - useful for auditing and re-creation.
    agent_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Copy of the job's result_schema at launch time (jobs can change later).
    result_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    call_defaults: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    error: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship(back_populates="campaigns")
    calls: Mapped[list[Call]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", lazy="selectin"
    )


class Call(Base, TimestampMixin):
    """One outbound voice call and the structured answers it produced."""

    __tablename__ = "calls"
    __table_args__ = (Index("ix_calls_campaign_status", "campaign_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )

    hunar_call_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(
        String(32), default=CallStatus.PENDING, nullable=False
    )
    lifecycle_status: Mapped[str | None] = mapped_column(String(32))
    engagement_status: Mapped[str | None] = mapped_column(String(32))
    answered_by: Mapped[str | None] = mapped_column(String(32))
    call_ended_by: Mapped[str | None] = mapped_column(String(32))

    dialed_number: Mapped[str | None] = mapped_column(String(32))
    #: True when DEMO_CALL_REDIRECT_NUMBER rerouted this call away from the candidate.
    dialed_redirected: Mapped[bool] = mapped_column(Boolean, default=False)

    duration_seconds: Mapped[float | None] = mapped_column(Float)
    user_speech_duration: Mapped[float | None] = mapped_column(Float)
    recording_url: Mapped[str | None] = mapped_column(String(1024))

    #: The heart of the dashboard: the agent's structured answers.
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    custom_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    #: "webhook" | "poll" - shows the operator how fresh data arrived.
    sync_source: Mapped[str | None] = mapped_column(String(16))

    campaign: Mapped[Campaign] = relationship(back_populates="calls")
    candidate: Mapped[Candidate] = relationship(back_populates="calls")


class WebhookEvent(Base, TimestampMixin):
    """Append-only log of Hunar callbacks (for debugging and replay)."""

    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_type: Mapped[str | None] = mapped_column(String(64), index=True)
    hunar_call_id: Mapped[str | None] = mapped_column(String(64), index=True)
    signature_valid: Mapped[bool | None] = mapped_column(Boolean)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    handled: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
