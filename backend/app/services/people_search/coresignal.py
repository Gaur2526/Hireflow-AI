"""Coresignal - Employee (multi-source) search.

Docs: https://docs.coresignal.com

Coresignal uses a two-step pattern: ``POST /search/es_dsl`` is free and returns
a flat JSON array of integer employee IDs; ``GET /collect/{id}`` then spends
credits (20 for multi-source, 10 for base/clean) per record. Collection is the
expensive step, so it runs with bounded concurrency and a hard cap.

Note on contactability: Coresignal employee records contain a professional email
but **no personal phone number on any tier** - phone data exists only on company
records. Numbers have to come from elsewhere before a call can be placed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.services.people_search.base import (
    PeopleSearchProvider,
    SearchQuery,
    SearchResult,
    SourcedProfile,
)
from app.services.people_search.http import as_list, first, request_json

log = get_logger(__name__)

BASE = "https://api.coresignal.com/cdapi/v2"
SEARCH_URL = f"{BASE}/employee_multi_source/search/es_dsl"
COLLECT_URL = f"{BASE}/employee_multi_source/collect"

_COLLECT_CONCURRENCY = 5


class CoresignalProvider(PeopleSearchProvider):
    name = "coresignal"
    label = "Coresignal"
    docs_url = "https://docs.coresignal.com"

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def search(self, query: SearchQuery) -> SearchResult:
        body = build_es_dsl(query)
        payload, elapsed = await request_json(
            self.label,
            "POST",
            SEARCH_URL,
            headers=self._headers(),
            json_body=body,
        )

        ids = _extract_ids(payload)[: min(query.limit, 50)]
        records = await self._collect(ids)
        # Collection already spent the credits; one malformed row must not
        # throw away the whole page.
        profiles: list[SourcedProfile] = []
        for record in records:
            try:
                profiles.append(self._to_profile(record))
            except Exception as exc:  # noqa: BLE001 - vendor payloads vary
                log.warning("coresignal.record_skipped", error=str(exc)[:200])

        warnings: list[str] = []
        if len(ids) < len(_extract_ids(payload)):
            warnings.append(
                f"Coresignal matched {len(_extract_ids(payload))} records; collected "
                f"the first {len(ids)} to limit credit spend."
            )
        if profiles:
            warnings.append(
                "Coresignal employee records carry no personal phone field on any "
                "tier - its acceptable-use policy excludes personal telephone "
                "numbers. Add numbers manually (or use the professional email) "
                "before placing calls."
            )
        return SearchResult(
            provider=self.name,
            profiles=profiles,
            total_available=len(_extract_ids(payload)),
            query_sent=body,
            latency_ms=elapsed,
            warnings=warnings,
        )

    async def _collect(self, ids: list[Any]) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(_COLLECT_CONCURRENCY)

        async def _one(record_id: Any) -> dict[str, Any] | None:
            async with semaphore:
                try:
                    data, _ = await request_json(
                        self.label,
                        "GET",
                        f"{COLLECT_URL}/{record_id}",
                        headers=self._headers(),
                    )
                except UpstreamError as exc:
                    log.warning(
                        "coresignal.collect_failed", id=record_id, error=exc.message
                    )
                    return None
            return data if isinstance(data, dict) else None

        results = await asyncio.gather(*(_one(i) for i in ids))
        return [r for r in results if r]

    def _to_profile(self, record: dict[str, Any]) -> SourcedProfile:
        full_name = first(record.get("full_name"), record.get("name")) or "Unknown"
        first_name, last_name = record.get("first_name"), record.get("last_name")
        if not first_name or not last_name:
            first_name, last_name = self.split_name(str(full_name))

        experiences = [
            e
            for e in as_list(
                first(
                    record.get("experience"), record.get("member_experience_collection")
                )
            )
            if isinstance(e, dict)
        ]
        current = next(
            (e for e in experiences if _is_current(e)),
            experiences[0] if experiences else {},
        )
        title = first(
            record.get("active_experience_title"),
            record.get("title"),
            current.get("position_title"),
            current.get("title"),
        )
        company = first(
            record.get("active_experience_company_name"),
            current.get("company_name"),
            current.get("company"),
        )

        return SourcedProfile(
            external_id=str(
                first(record.get("id"), record.get("shorthand_name")) or ""
            ),
            source=self.name,
            full_name=str(full_name),
            first_name=first_name,
            last_name=last_name,
            title=title,
            headline=first(record.get("headline"), record.get("summary")),
            company=company,
            location=first(record.get("location_full"), record.get("location")),
            country_code=_code(record.get("location_country")),
            linkedin_url=first(record.get("linkedin_url"), record.get("url")),
            email=first(
                *(
                    _email_value(e)
                    for e in (
                        *as_list(record.get("primary_professional_email")),
                        *as_list(record.get("professional_emails_collection")),
                    )
                ),
            ),
            phone=_phone(record),
            years_experience=_years(record),
            seniority=first(
                record.get("active_experience_management_level"),
                self.infer_seniority(title),
            ),
            skills=[
                name
                for name in (
                    _skill_name(s)
                    for s in as_list(
                        first(record.get("inferred_skills"), record.get("skills"))
                    )
                )
                if name
            ][:20],
            experience=[
                {
                    "company": first(e.get("company_name"), e.get("company")),
                    "title": first(e.get("position_title"), e.get("title")),
                    "is_current": _is_current(e),
                    "start_date": e.get("date_from"),
                    "end_date": e.get("date_to"),
                }
                for e in experiences[:6]
            ],
            education=[
                {
                    "school": first(e.get("institution_name"), e.get("title")),
                    "degree": e.get("degree"),
                    "major": e.get("field_of_study"),
                }
                for e in as_list(
                    first(
                        record.get("education"),
                        record.get("member_education_collection"),
                    )
                )[:4]
                if isinstance(e, dict)
            ],
            raw={"id": record.get("id")},
        )


def build_es_dsl(query: SearchQuery) -> dict[str, Any]:
    must: list[dict[str, Any]] = []
    should: list[dict[str, Any]] = []

    if query.titles:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"active_experience_title": t}}
                        for t in query.titles[:6]
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    for skill in query.must_have_skills[:6]:
        must.append({"match": {"inferred_skills": skill}})
    for skill in query.nice_to_have_skills[:6]:
        should.append({"match": {"inferred_skills": skill}})

    if query.locations:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"location_full": loc}}
                        for loc in query.locations[:4]
                        if loc.lower() != "remote"
                    ]
                    or [{"match_all": {}}],
                    "minimum_should_match": 1,
                }
            }
        )
    if query.companies:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"active_experience_company_name": c}}
                        for c in query.companies[:5]
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if query.min_years is not None or query.max_years is not None:
        bounds: dict[str, float] = {}
        if query.min_years is not None:
            bounds["gte"] = query.min_years * 12
        if query.max_years is not None:
            bounds["lte"] = query.max_years * 12
        must.append({"range": {"total_experience_duration_months": bounds}})

    bool_query: dict[str, Any] = {"must": must or [{"match_all": {}}]}
    if should:
        bool_query["should"] = should
    if query.exclude_companies:
        bool_query["must_not"] = [
            {"match": {"active_experience_company_name": c}}
            for c in query.exclude_companies[:5]
        ]
    return {"query": {"bool": bool_query}}


def _extract_ids(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("ids", "data", "results", "hits"):
            value = payload.get(key)
            if isinstance(value, list):
                return [v.get("id") if isinstance(v, dict) else v for v in value]
    return []


def _is_current(entry: dict[str, Any]) -> bool:
    if entry.get("active_experience") in (1, True):
        return True
    return entry.get("date_to") in (None, "", "present")


def _phone(record: dict[str, Any]) -> str | None:
    for key in ("phone", "primary_phone", "phone_numbers", "contact_phone"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        for entry in as_list(value):
            if isinstance(entry, str) and entry.strip():
                return entry.strip()
            if isinstance(entry, dict):
                number = entry.get("number") or entry.get("phone")
                if number:
                    return str(number)
    return None


def _years(record: dict[str, Any]) -> float | None:
    months = record.get("total_experience_duration_months")
    if isinstance(months, (int, float)) and months > 0:
        return round(months / 12.0, 1)
    years = record.get("total_experience_duration_years")
    if isinstance(years, (int, float)):
        return float(years)
    return None


def _email_value(value: Any) -> str | None:
    """``professional_emails_collection`` entries are objects, not strings."""
    if isinstance(value, dict):
        return (
            value.get("professional_email")
            or value.get("email")
            or value.get("address")
        )
    return str(value) if value else None


def _skill_name(value: Any) -> str | None:
    """Skills arrive as strings, ``{"skill": ...}`` or ``{"member_skill_list": {...}}``."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        nested = value.get("member_skill_list")
        if isinstance(nested, dict):
            return _skill_name(nested)
        name = value.get("skill") or value.get("name")
        return name if isinstance(name, str) and name else None
    return None


def _code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    mapping = {
        "india": "IN",
        "united states": "US",
        "united kingdom": "GB",
        "saudi arabia": "SA",
    }
    return mapping.get(
        value.strip().lower(), value.upper()[:2] if len(value) == 2 else None
    )
