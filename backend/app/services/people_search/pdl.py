"""People Data Labs - Person Search API.

Docs: https://docs.peopledatalabs.com/docs/person-search-api

Search is Elasticsearch-flavoured. PDL only returns phone numbers on plans that
license them, so :attr:`SearchQuery.require_phone` adds an existence filter
rather than silently returning uncallable profiles.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.people_search.base import (
    PeopleSearchProvider,
    SearchQuery,
    SearchResult,
    SourcedProfile,
)
from app.services.people_search.http import as_list, first, request_json

log = get_logger(__name__)

BASE_URL = "https://api.peopledatalabs.com/v5/person/search"


class PDLProvider(PeopleSearchProvider):
    name = "pdl"
    label = "People Data Labs"
    docs_url = "https://docs.peopledatalabs.com/docs/person-search-api"

    async def search(self, query: SearchQuery) -> SearchResult:
        es_query = build_es_query(query)
        body = {
            "query": es_query,
            # `size` defaults to 1, so it always has to be sent explicitly.
            "size": min(query.limit, 100),
            # The default `resume` dataset fills mobile_phone on ~7% of records;
            # `all` is what makes the results dialable.
            "dataset": "all",
            "titlecase": True,
            "pretty": False,
        }
        payload, elapsed = await request_json(
            self.label,
            "POST",
            BASE_URL,
            headers={
                "X-Api-Key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json_body=body,
        )

        records = payload.get("data") or []
        # One malformed vendor row must not throw away a paid page of results.
        profiles: list[SourcedProfile] = []
        for record in records:
            try:
                profiles.append(self._to_profile(record))
            except Exception as exc:  # noqa: BLE001 - vendor payloads vary
                log.warning("pdl.record_skipped", error=str(exc)[:200])
        warnings: list[str] = []
        unmapped = [c for c in query.countries[:3] if not _country_name(c)]
        if unmapped:
            warnings.append(
                "Ignored the country filter for "
                + ", ".join(unmapped)
                + ": People Data Labs matches on country names and these ISO "
                "codes are not mapped, so filtering on them returns nothing."
            )
        without_phone = sum(1 for p in profiles if not p.phone)
        if without_phone:
            warnings.append(
                f"{without_phone}/{len(profiles)} People Data Labs profiles came back "
                "without a phone number - PDL only returns those on plans that "
                "license contact data. Add numbers manually to call them."
            )
        return SearchResult(
            provider=self.name,
            profiles=profiles,
            total_available=payload.get("total"),
            query_sent=body,
            latency_ms=elapsed,
            warnings=warnings,
        )

    def _to_profile(self, record: dict[str, Any]) -> SourcedProfile:
        full_name = first(record.get("full_name"), record.get("name")) or "Unknown"
        first_name, last_name = (
            record.get("first_name"),
            record.get("last_name"),
        )
        if not first_name or not last_name:
            first_name, last_name = self.split_name(str(full_name))

        phone = first(
            record.get("mobile_phone"),
            *(as_list(record.get("phone_numbers")) or [None]),
        )
        title = first(record.get("job_title"), record.get("headline"))
        company = record.get("job_company_name")
        years = record.get("inferred_years_experience")

        return SourcedProfile(
            external_id=record.get("id"),
            source=self.name,
            full_name=str(full_name).title()
            if str(full_name).islower()
            else str(full_name),
            first_name=first_name,
            last_name=last_name,
            title=title,
            headline=first(
                record.get("headline"),
                f"{title} at {company}" if title and company else title,
            ),
            company=company,
            location=first(
                record.get("location_name"), record.get("location_locality")
            ),
            country_code=_country_code(record.get("location_country")),
            linkedin_url=_linkedin(record),
            email=_email_value(
                first(
                    record.get("work_email"),
                    record.get("recommended_personal_email"),
                    *(as_list(record.get("emails")) or [None]),
                )
            ),
            phone=_phone_value(phone),
            years_experience=float(years) if isinstance(years, (int, float)) else None,
            seniority=first(
                *(as_list(record.get("job_title_levels")) or [None]),
                self.infer_seniority(
                    title, years if isinstance(years, (int, float)) else None
                ),
            ),
            skills=[s for s in as_list(record.get("skills")) if isinstance(s, str)][
                :20
            ],
            experience=_experience(record),
            education=_education(record),
            raw={
                k: v for k, v in record.items() if k not in {"experience", "education"}
            },
        )


def build_es_query(query: SearchQuery) -> dict[str, Any]:
    """Compose the Elasticsearch bool query PDL expects."""
    must: list[dict[str, Any]] = []
    should: list[dict[str, Any]] = []

    if query.titles:
        # job_title is a keyword field; only job_title.text is analysed, so
        # free-text title matching has to target the sub-field.
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"job_title.text": title}}
                        for title in query.titles[:6]
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    # `skills` is an un-canonicalised keyword array. Demanding every must-have
    # exactly is the fastest way to get zero results, so require a majority and
    # let the fit score rank the rest.
    must_skills = [s.lower() for s in query.must_have_skills[:8] if s.strip()]
    if must_skills:
        must.append(
            {
                "bool": {
                    "should": [{"term": {"skills": skill}} for skill in must_skills],
                    "minimum_should_match": max(1, (len(must_skills) + 1) // 2),
                }
            }
        )
    for skill in query.nice_to_have_skills[:6]:
        should.append({"term": {"skills": skill.lower()}})

    if query.locations:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"location_name": loc}}
                        for loc in query.locations[:4]
                        if loc.lower() != "remote"
                    ]
                    or [{"match_all": {}}],
                    "minimum_should_match": 1,
                }
            }
        )
    named = [n for n in (_country_name(c) for c in query.countries[:3]) if n]
    if named:
        must.append(
            {
                "bool": {
                    "should": [{"term": {"location_country": name}} for name in named],
                    "minimum_should_match": 1,
                }
            }
        )

    if query.min_years is not None or query.max_years is not None:
        bounds: dict[str, float] = {}
        if query.min_years is not None:
            bounds["gte"] = query.min_years
        if query.max_years is not None:
            bounds["lte"] = query.max_years
        must.append({"range": {"inferred_years_experience": bounds}})

    if query.require_phone:
        must.append(
            {
                "bool": {
                    "should": [
                        {"exists": {"field": "mobile_phone"}},
                        {"exists": {"field": "phone_numbers"}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if query.companies:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"job_company_name": c}} for c in query.companies[:5]
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    bool_query: dict[str, Any] = {"must": must or [{"match_all": {}}]}
    if should:
        bool_query["should"] = should
    if query.exclude_companies:
        bool_query["must_not"] = [
            {"match": {"job_company_name": c}} for c in query.exclude_companies[:5]
        ]
    return {"bool": bool_query}


_COUNTRY_NAMES = {
    "IN": "india",
    "US": "united states",
    "GB": "united kingdom",
    "SA": "saudi arabia",
    "AE": "united arab emirates",
    "SG": "singapore",
    "CA": "canada",
    "AU": "australia",
    "DE": "germany",
    "NL": "netherlands",
}
_NAME_TO_CODE = {v: k for k, v in _COUNTRY_NAMES.items()}


def _country_name(code: str) -> str | None:
    """None for an unmapped code.

    ``location_country`` holds full country names, so falling back to the ISO
    code would emit a term clause that can never match and silently zero out
    the whole search.
    """
    return _COUNTRY_NAMES.get(code.upper())


def _country_code(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    return _NAME_TO_CODE.get(
        name.strip().lower(), name.upper()[:2] if len(name) == 2 else None
    )


def _linkedin(record: dict[str, Any]) -> str | None:
    url = first(record.get("linkedin_url"), record.get("linkedin_username"))
    if not url:
        return None
    text = str(url)
    return text if text.startswith("http") else f"https://www.linkedin.com/in/{text}"


def _phone_value(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("number") or value.get("phone")
    return str(value) if value else None


def _email_value(value: Any) -> str | None:
    """``emails`` is a list of ``{"address": ..., "type": ...}`` objects."""
    if isinstance(value, dict):
        return value.get("address") or value.get("email")
    return str(value) if value else None


def _experience(record: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in as_list(record.get("experience"))[:6]:
        if not isinstance(entry, dict):
            continue
        company = entry.get("company") or {}
        title = entry.get("title") or {}
        out.append(
            {
                "company": company.get("name")
                if isinstance(company, dict)
                else company,
                "title": title.get("name") if isinstance(title, dict) else title,
                "is_current": bool(entry.get("is_primary")),
                "start_date": entry.get("start_date"),
                "end_date": entry.get("end_date"),
            }
        )
    return out


def _education(record: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in as_list(record.get("education"))[:4]:
        if not isinstance(entry, dict):
            continue
        school = entry.get("school") or {}
        out.append(
            {
                "school": school.get("name") if isinstance(school, dict) else school,
                "degree": first(*as_list(entry.get("degrees"))),
                "major": first(*as_list(entry.get("majors"))),
            }
        )
    return out
