"""Apollo.io - People Search.

Docs: https://docs.apollo.io/reference/people-search

Apollo masks emails and direct dials by default; ``person.phone_numbers`` is
usually empty on search responses. The enrichment endpoint can reveal them but
consumes credits and (for phone) requires an async webhook, so this client
surfaces what search returns and tells the operator when nothing is dialable.
"""

from __future__ import annotations

from typing import Any

from app.services.people_search.base import (
    PeopleSearchProvider,
    SearchQuery,
    SearchResult,
    SourcedProfile,
)
from app.services.people_search.http import as_list, first, request_json

BASE_URL = "https://api.apollo.io/api/v1/mixed_people/search"

SENIORITY_MAP = {
    "entry": "entry",
    "mid": "senior",
    "senior": "senior",
    "manager": "manager",
    "director": "director",
    "vp": "vp",
    "cxo": "c_suite",
}


class ApolloProvider(PeopleSearchProvider):
    name = "apollo"
    label = "Apollo.io"
    docs_url = "https://docs.apollo.io/reference/people-search"

    async def search(self, query: SearchQuery) -> SearchResult:
        body = build_body(query)
        payload, elapsed = await request_json(
            self.label,
            "POST",
            BASE_URL,
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            },
            json_body=body,
        )

        records = (payload.get("people") or []) + (payload.get("contacts") or [])
        profiles = [self._to_profile(r) for r in records][: query.limit]
        pagination = payload.get("pagination") or {}

        warnings: list[str] = []
        if query.require_phone:
            warnings.append(
                "Apollo cannot filter on phone availability at search time, so "
                '"only with a phone" was not applied to this result set.'
            )
        if profiles and not any(p.phone for p in profiles):
            warnings.append(
                "Apollo search does not return direct dials. Reveal them with the "
                "People Enrichment endpoint, or paste numbers in manually to call."
            )
        return SearchResult(
            provider=self.name,
            profiles=profiles,
            total_available=pagination.get("total_entries"),
            query_sent=body,
            latency_ms=elapsed,
            warnings=warnings,
        )

    def _to_profile(self, record: dict[str, Any]) -> SourcedProfile:
        org = record.get("organization") or record.get("account") or {}
        full_name = (
            first(
                record.get("name"),
                " ".join(
                    filter(None, [record.get("first_name"), record.get("last_name")])
                ),
            )
            or "Unknown"
        )
        title = record.get("title")
        company = org.get("name") if isinstance(org, dict) else None
        location = ", ".join(
            [
                p
                for p in (
                    record.get("city"),
                    record.get("state"),
                    record.get("country"),
                )
                if p
            ]
        )
        phone = first(
            record.get("sanitized_phone"),
            record.get("phone"),
            *(_phone_numbers(record) or [None]),
            org.get("phone") if isinstance(org, dict) else None,
        )

        return SourcedProfile(
            external_id=record.get("id"),
            source=self.name,
            full_name=str(full_name),
            first_name=record.get("first_name"),
            last_name=record.get("last_name"),
            title=title,
            headline=first(
                record.get("headline"),
                f"{title} at {company}" if title and company else title,
            ),
            company=company,
            location=location or None,
            country_code=_country_code(record.get("country")),
            linkedin_url=record.get("linkedin_url"),
            email=_email(record),
            phone=str(phone) if phone else None,
            years_experience=None,  # Apollo does not expose a years field.
            seniority=first(record.get("seniority"), self.infer_seniority(title)),
            skills=[
                s
                for s in as_list(
                    first(
                        record.get("keywords"),
                        org.get("keywords") if isinstance(org, dict) else None,
                    )
                )
                if isinstance(s, str)
            ][:20],
            experience=_experience(record),
            education=[],
            raw={k: v for k, v in record.items() if k != "employment_history"},
        )


def build_body(query: SearchQuery) -> dict[str, Any]:
    body: dict[str, Any] = {
        "page": 1,
        "per_page": min(query.limit, 100),
    }
    if query.titles:
        body["person_titles"] = query.titles[:8]
    if query.locations:
        body["person_locations"] = [
            loc for loc in query.locations[:5] if loc.lower() != "remote"
        ]
    if query.seniority:
        levels = [SENIORITY_MAP.get(s.lower()) for s in query.seniority]
        body["person_seniorities"] = [level for level in levels if level]
    if query.companies:
        body["organization_names"] = query.companies[:10]
    keywords = [*query.must_have_skills[:8], *query.keywords[:2]]
    if keywords:
        body["q_keywords"] = " ".join(dict.fromkeys(keywords))
    # NB: no phone filter. Apollo's search API cannot filter on phone
    # availability, and narrowing by contact_email_status instead just drops
    # people who have a direct dial but an unverified email.
    return body


def _phone_numbers(record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for entry in as_list(record.get("phone_numbers")):
        if isinstance(entry, dict):
            value = entry.get("sanitized_number") or entry.get("raw_number")
            if value:
                out.append(str(value))
        elif isinstance(entry, str):
            out.append(entry)
    return out


def _email(record: dict[str, Any]) -> str | None:
    email = record.get("email")
    if isinstance(email, str) and "email_not_unlocked" not in email:
        return email
    for entry in as_list(record.get("personal_emails")):
        if isinstance(entry, str):
            return entry
    return None


def _experience(record: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in as_list(record.get("employment_history"))[:6]:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "company": entry.get("organization_name"),
                "title": entry.get("title"),
                "is_current": bool(entry.get("current")),
                "start_date": entry.get("start_date"),
                "end_date": entry.get("end_date"),
            }
        )
    return out


_COUNTRY_CODES = {
    "india": "IN",
    "united states": "US",
    "united kingdom": "GB",
    "saudi arabia": "SA",
    "united arab emirates": "AE",
    "singapore": "SG",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "netherlands": "NL",
}


def _country_code(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    return _COUNTRY_CODES.get(name.strip().lower())
