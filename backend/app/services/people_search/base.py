"""Provider-agnostic contract for people search.

Every vendor (PDL, Apollo, Proxycurl, Coresignal, plus a built-in offline
provider) returns the same :class:`SourcedProfile` shape, so the rest of the
application never learns which vendor produced a candidate.
"""

from __future__ import annotations

import abc
import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger

log = get_logger(__name__)


class SearchQuery(BaseModel):
    """Normalised search intent, derived from a job description."""

    titles: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)  # ISO-3166 alpha-2
    industries: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    min_years: float | None = None
    max_years: float | None = None
    limit: int = 25
    require_phone: bool = False

    @property
    def all_skills(self) -> list[str]:
        seen: dict[str, None] = {}
        for skill in [*self.must_have_skills, *self.nice_to_have_skills]:
            seen.setdefault(skill.lower(), None)
        return list(seen)


class SourcedProfile(BaseModel):
    """A person, normalised across vendors."""

    external_id: str | None = None
    source: str = "mock"
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    headline: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    country_code: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    phone: str | None = None
    years_experience: float | None = None
    seniority: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        """Stable identity: LinkedIn > email > provider id > name+company."""
        for candidate in (
            _norm_linkedin(self.linkedin_url),
            (self.email or "").strip().lower(),
            f"{self.source}:{self.external_id}" if self.external_id else "",
            f"{(self.full_name or '').strip().lower()}|{(self.company or '').strip().lower()}",
        ):
            if candidate:
                return hashlib.sha1(candidate.encode()).hexdigest()  # noqa: S324
        return hashlib.sha1(self.model_dump_json().encode()).hexdigest()  # noqa: S324


class SearchResult(BaseModel):
    provider: str
    profiles: list[SourcedProfile] = Field(default_factory=list)
    total_available: int | None = None
    query_sent: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    warnings: list[str] = Field(default_factory=list)


class PeopleSearchProvider(abc.ABC):
    """Interface every people-search integration implements."""

    #: Registry key, e.g. ``"pdl"``.
    name: str = "base"
    #: Human-readable name shown in the UI.
    label: str = "Base"
    #: Vendor docs, surfaced in the settings screen.
    docs_url: str = ""
    #: Whether an API key is mandatory.
    requires_key: bool = True
    #: Set when the upstream vendor no longer exists.
    retired: bool = False
    retirement_note: str = ""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    @property
    def configured(self) -> bool:
        return (not self.requires_key) or bool(self.api_key)

    @abc.abstractmethod
    async def search(self, query: SearchQuery) -> SearchResult:
        """Run a search and return normalised profiles."""

    # -- shared helpers -----------------------------------------------------
    @staticmethod
    def split_name(full_name: str) -> tuple[str | None, str | None]:
        parts = [p for p in re.split(r"\s+", (full_name or "").strip()) if p]
        if not parts:
            return None, None
        if len(parts) == 1:
            return parts[0], None
        return parts[0], parts[-1]

    @staticmethod
    def infer_seniority(title: str | None, years: float | None = None) -> str | None:
        text = (title or "").lower()
        ladder = [
            ("cxo", ("chief ", "cto", "ceo", "cfo", "coo", "cpo", "founder")),
            ("vp", ("vp ", "vice president", "svp", "evp")),
            ("director", ("director", "head of")),
            ("manager", ("manager", "lead", "principal", "staff")),
            ("senior", ("senior", "sr.", "sr ", "iii")),
            ("entry", ("intern", "trainee", "junior", "associate", "graduate")),
        ]
        for level, needles in ladder:
            if any(n in text for n in needles):
                return level
        if years is not None:
            if years >= 12:
                return "director"
            if years >= 7:
                return "manager"
            if years >= 4:
                return "senior"
            if years <= 1:
                return "entry"
        return "mid"


def _norm_linkedin(url: str | None) -> str:
    if not url:
        return ""
    cleaned = url.strip().lower().split("?")[0].rstrip("/")
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = re.sub(r"^([a-z]{2,3}\.)?linkedin\.com/", "linkedin.com/", cleaned)
    return cleaned
