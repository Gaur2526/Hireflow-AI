"""Job-description domain schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, UTCDatetime

AnswerType = Literal["string", "boolean", "number", "enum"]


class JobCriteria(BaseModel):
    """Structured hiring criteria extracted from a free-text job description."""

    role_title: str = ""
    #: Title variants to search vendors with (the JD title plus synonyms).
    titles: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    min_years: float | None = None
    max_years: float | None = None
    locations: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    employment_type: str | None = None
    work_mode: str | None = None  # onsite | hybrid | remote
    compensation: str | None = None
    summary: str = ""

    @field_validator(
        "titles",
        "seniority",
        "must_have_skills",
        "nice_to_have_skills",
        "locations",
        "countries",
        "industries",
        "target_companies",
        "education",
        mode="before",
    )
    @classmethod
    def _dedupe(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return v
        seen: dict[str, str] = {}
        for item in v:
            if not isinstance(item, str):
                continue
            key = item.strip().lower()
            if key and key not in seen:
                seen[key] = item.strip()
        return list(seen.values())


class ScreeningQuestion(BaseModel):
    """One thing the voice agent must find out on the call."""

    #: snake_case identifier - becomes a key in Hunar's ``result_schema`` and a
    #: column in the results dashboard.
    key: str
    question: str
    answer_type: AnswerType = "string"
    options: list[str] = Field(default_factory=list)
    #: Which JD requirement this question validates (shown in the UI).
    rationale: str = ""
    required: bool = True

    @field_validator("key")
    @classmethod
    def _snake(cls, v: str) -> str:
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in v.strip().lower())
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_")[:48] or "answer"


class ScreeningPlan(BaseModel):
    """Everything needed to configure a Hunar voice agent for this role."""

    questions: list[ScreeningQuestion] = Field(default_factory=list)
    objective: str = ""
    introduction: str = ""
    agent_prompt: str = ""
    result_prompt: str = ""
    result_schema: dict[str, str] = Field(default_factory=dict)


# --- API payloads ----------------------------------------------------------
class JobCreate(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str = Field(min_length=40)


class JobUpdate(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    criteria: JobCriteria | None = None
    screening_questions: list[ScreeningQuestion] | None = None


class JobRead(ORMModel):
    id: str
    title: str
    company: str | None
    location: str | None
    description: str
    status: str
    criteria: dict[str, Any]
    screening_questions: list[dict[str, Any]]
    result_schema: dict[str, Any]
    parsed_by: str | None
    created_at: UTCDatetime | None
    updated_at: UTCDatetime | None


class JobSummary(ORMModel):
    id: str
    title: str
    company: str | None
    location: str | None
    status: str
    parsed_by: str | None
    created_at: UTCDatetime | None
    candidate_count: int = 0
    shortlisted_count: int = 0
    campaign_count: int = 0
    call_count: int = 0


class ParsePreview(BaseModel):
    """Response of the 'parse this JD' endpoint (no persistence)."""

    criteria: JobCriteria
    screening_plan: ScreeningPlan
    parsed_by: str
    warnings: list[str] = Field(default_factory=list)
