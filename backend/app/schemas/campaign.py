from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ORMModel, UTCDatetime
from app.schemas.job import ScreeningQuestion

VALID_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


class AgentConfigInput(BaseModel):
    """Voice-agent knobs exposed in the campaign launcher."""

    language: str = "ENGLISH"
    voice_persona: str = "NEHA"
    persona_name: str | None = None
    #: Optional operator edits to the generated copy.
    introduction: str | None = None
    agent_prompt: str | None = None
    objective: str | None = None
    result_prompt: str | None = None
    questions: list[ScreeningQuestion] | None = None


#: Hunar's docs narrow the spec's 0-24 range to this set.
RETRY_INTERVALS = (0, 3, 6, 9, 12, 24)
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class CallDefaults(BaseModel):
    """Calling window and retry policy.

    The constraints here mirror what Hunar enforces server-side, so an invalid
    combination is rejected with a readable message instead of a raw 422.
    """

    timezone: str = "Asia/Kolkata"
    max_retry_count: int = Field(default=1, ge=0, le=10)
    retry_interval_hours: int = 6
    #: At least three distinct days, per Hunar's guardrail rules.
    allowed_days: list[str] = Field(
        default_factory=lambda: ["MON", "TUE", "WED", "THU", "FRI"]
    )
    earliest_call_time: str = "10:00"
    last_call_time: str = "19:00"
    #: Leave unset: the platform assigns a pooled outbound number. Only set this
    #: when the org owns a number registered for the destination country.
    from_phone_number: str | None = None

    @field_validator("retry_interval_hours")
    @classmethod
    def _interval(cls, v: int) -> int:
        if v not in RETRY_INTERVALS:
            raise ValueError(
                "retry_interval_hours must be one of "
                + ", ".join(str(i) for i in RETRY_INTERVALS)
            )
        return v

    @field_validator("allowed_days")
    @classmethod
    def _days(cls, v: list[str]) -> list[str]:
        days = list(dict.fromkeys(d.strip().upper() for d in v if d.strip()))
        unknown = [d for d in days if d not in VALID_DAYS]
        if unknown:
            raise ValueError(f"Unknown day(s): {', '.join(unknown)}")
        if len(days) < 3:
            raise ValueError("Pick at least three calling days.")
        return days

    @field_validator("earliest_call_time", "last_call_time")
    @classmethod
    def _time(cls, v: str) -> str:
        if not _TIME_RE.match(v.strip()):
            raise ValueError(f"'{v}' must be HH:MM in 24-hour time (not HH:MM:SS).")
        return v.strip()

    @model_validator(mode="after")
    def _window(self) -> "CallDefaults":
        start = _minutes(self.earliest_call_time)
        end = _minutes(self.last_call_time)
        if end - start < 180:
            raise ValueError("The calling window must be at least 3 hours long.")
        return self


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


class CampaignCreate(BaseModel):
    name: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    agent_config: AgentConfigInput = Field(default_factory=AgentConfigInput)
    call_defaults: CallDefaults = Field(default_factory=CallDefaults)
    #: Reuse an existing Hunar agent instead of creating a new one.
    reuse_agent_id: str | None = None
    #: Build the agent + call rows but do not dial yet.
    dry_run: bool = False


class CallRead(ORMModel):
    id: str
    campaign_id: str
    candidate_id: str
    hunar_call_id: str | None
    request_id: str | None
    status: str
    lifecycle_status: str | None
    engagement_status: str | None
    answered_by: str | None
    call_ended_by: str | None
    dialed_number: str | None
    dialed_redirected: bool
    duration_seconds: float | None
    user_speech_duration: float | None
    recording_url: str | None
    result: dict[str, Any]
    custom_data: dict[str, Any]
    retry_count: int
    error: str | None
    started_at: UTCDatetime | None
    ended_at: UTCDatetime | None
    last_synced_at: UTCDatetime | None
    sync_source: str | None
    created_at: UTCDatetime | None
    updated_at: UTCDatetime | None


class CallWithCandidate(CallRead):
    candidate_name: str = ""
    candidate_title: str | None = None
    candidate_company: str | None = None
    candidate_linkedin: str | None = None
    candidate_fit_score: float = 0.0


class CampaignRead(ORMModel):
    id: str
    job_id: str
    name: str
    status: str
    hunar_agent_id: str | None
    agent_config: dict[str, Any]
    result_schema: dict[str, Any]
    call_defaults: dict[str, Any]
    request_id: str | None
    error: str | None
    created_at: UTCDatetime | None
    updated_at: UTCDatetime | None


class CampaignStats(BaseModel):
    total: int = 0
    pending: int = 0
    in_flight: int = 0
    completed: int = 0
    not_connected: int = 0
    failed: int = 0
    cancelled: int = 0
    answered_human: int = 0
    consented: int = 0
    interested: int = 0
    do_not_contact: int = 0
    avg_duration_seconds: float | None = None
    total_talk_minutes: float = 0.0


class CampaignDetail(BaseModel):
    campaign: CampaignRead
    job_title: str
    job_id: str
    stats: CampaignStats
    calls: list[CallWithCandidate]
    #: Ordered answer columns for the results table, derived from result_schema.
    answer_columns: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CampaignSummary(ORMModel):
    id: str
    job_id: str
    name: str
    status: str
    hunar_agent_id: str | None
    created_at: UTCDatetime | None
    job_title: str = ""
    stats: CampaignStats = Field(default_factory=CampaignStats)


class LaunchResponse(BaseModel):
    campaign: CampaignRead
    dispatched: int
    skipped: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
