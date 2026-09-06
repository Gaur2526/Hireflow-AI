"""Provider selection and normalisation helpers."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.errors import ProviderNotConfigured
from app.core.logging import get_logger
from app.schemas.job import JobCriteria
from app.services.people_search.apollo import ApolloProvider
from app.services.people_search.base import (
    PeopleSearchProvider,
    SearchQuery,
    SourcedProfile,
)
from app.services.people_search.coresignal import CoresignalProvider
from app.services.people_search.mock import MockPeopleSearchProvider
from app.services.people_search.pdl import PDLProvider
from app.services.people_search.proxycurl import ProxycurlProvider

log = get_logger(__name__)

_CLASSES: dict[str, type[PeopleSearchProvider]] = {
    MockPeopleSearchProvider.name: MockPeopleSearchProvider,
    PDLProvider.name: PDLProvider,
    ApolloProvider.name: ApolloProvider,
    ProxycurlProvider.name: ProxycurlProvider,
    CoresignalProvider.name: CoresignalProvider,
}


def build_provider(name: str | None = None) -> PeopleSearchProvider:
    """Instantiate a provider by name, defaulting to the configured one."""
    key = (name or settings.people_provider or "mock").strip().lower()
    cls = _CLASSES.get(key)
    if cls is None:
        raise ProviderNotConfigured(
            f"Unknown people-search provider '{key}'. "
            f"Available: {', '.join(sorted(_CLASSES))}."
        )
    provider = cls(api_key=settings.provider_key(key))
    if provider.retired:
        raise ProviderNotConfigured(provider.retirement_note)
    if not provider.configured:
        raise ProviderNotConfigured(
            f"{provider.label} needs an API key. Set {key.upper()}_API_KEY, or "
            "switch PEOPLE_PROVIDER to 'mock' to use the built-in demo dataset."
        )
    return provider


def resolve_provider(name: str | None = None) -> tuple[PeopleSearchProvider, list[str]]:
    """Like :func:`build_provider` but falls back to mock instead of raising."""
    warnings: list[str] = []
    try:
        return build_provider(name), warnings
    except ProviderNotConfigured as exc:
        warnings.append(f"{exc.message} Falling back to the built-in demo dataset.")
        log.warning("people_search.fallback_to_mock", reason=exc.message)
        return MockPeopleSearchProvider(), warnings


def provider_status() -> list[dict[str, Any]]:
    """Non-secret provider inventory for the settings screen."""
    out: list[dict[str, Any]] = []
    for key, cls in _CLASSES.items():
        instance = cls(api_key=settings.provider_key(key))
        out.append(
            {
                "name": key,
                "label": instance.label,
                "docs_url": instance.docs_url,
                "requires_key": instance.requires_key,
                "configured": instance.configured,
                "retired": instance.retired,
                "note": instance.retirement_note,
                "active": key == (settings.people_provider or "mock"),
            }
        )
    return out


def query_from_criteria(
    criteria: JobCriteria,
    *,
    limit: int | None = None,
    require_phone: bool = False,
) -> SearchQuery:
    return SearchQuery(
        titles=criteria.titles
        or ([criteria.role_title] if criteria.role_title else []),
        seniority=criteria.seniority,
        must_have_skills=criteria.must_have_skills,
        nice_to_have_skills=criteria.nice_to_have_skills,
        locations=criteria.locations,
        countries=criteria.countries,
        industries=criteria.industries,
        companies=criteria.target_companies,
        keywords=[criteria.role_title] if criteria.role_title else [],
        min_years=criteria.min_years,
        max_years=criteria.max_years,
        limit=limit or settings.max_candidates_per_search,
        require_phone=require_phone,
    )


__all__ = [
    "PeopleSearchProvider",
    "SearchQuery",
    "SourcedProfile",
    "build_provider",
    "provider_status",
    "query_from_criteria",
    "resolve_provider",
]
