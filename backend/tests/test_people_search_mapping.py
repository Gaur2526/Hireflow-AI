"""Vendor payload -> SourcedProfile mapping.

Every provider is paid per result, so a single record shaped differently from
the happy path must never take the whole search down with it.
"""

from __future__ import annotations

import httpx

from app.services.people_search.apollo import build_body
from app.services.people_search.base import SearchQuery
from app.services.people_search.coresignal import CoresignalProvider
from app.services.people_search.pdl import PDLProvider, build_es_query


# ---------------------------------------------------------------------------
# People Data Labs
# ---------------------------------------------------------------------------
def test_pdl_emails_are_objects_not_strings() -> None:
    """PDL's documented shape: emails: [{"address": ..., "type": ...}]."""
    profile = PDLProvider(api_key="x")._to_profile(
        {
            "id": "abc",
            "full_name": "Sean Thorne",
            "emails": [{"address": "sean@peopledatalabs.com", "type": "professional"}],
        }
    )

    assert profile.email == "sean@peopledatalabs.com"


def test_pdl_country_filter_drops_a_code_it_cannot_name() -> None:
    """location_country holds names; a bare ISO code matches nothing at all."""
    query = build_es_query(SearchQuery(countries=["FR"]))

    assert not any(
        "location_country" in str(clause) for clause in query["bool"]["must"]
    )


def test_pdl_country_filter_still_maps_the_codes_it_knows() -> None:
    query = build_es_query(SearchQuery(countries=["IN"]))

    assert {
        "bool": {
            "should": [{"term": {"location_country": "india"}}],
            "minimum_should_match": 1,
        }
    } in query["bool"]["must"]


async def test_pdl_skips_an_unmappable_record_instead_of_failing_the_page(
    respx_mock,
) -> None:
    respx_mock.post("https://api.peopledatalabs.com/v5/person/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "1", "full_name": "Asha Menon"},
                    {
                        "id": "2",
                        "full_name": "Broken Row",
                        "emails": [{"address": {"nested": "object"}}],
                    },
                ],
                "total": 2,
            },
        )
    )

    result = await PDLProvider(api_key="x").search(SearchQuery(limit=2))

    assert [p.full_name for p in result.profiles] == ["Asha Menon"]


# ---------------------------------------------------------------------------
# Coresignal
# ---------------------------------------------------------------------------
def test_coresignal_professional_emails_are_objects() -> None:
    profile = CoresignalProvider(api_key="x")._to_profile(
        {
            "id": 1,
            "full_name": "Priya Iyer",
            "professional_emails_collection": [
                {
                    "professional_email": "priya@razorpay.com",
                    "professional_email_status": "verified",
                }
            ],
        }
    )

    assert profile.email == "priya@razorpay.com"


def test_coresignal_skills_may_be_nested_objects() -> None:
    profile = CoresignalProvider(api_key="x")._to_profile(
        {
            "id": 1,
            "full_name": "Priya Iyer",
            "skills": [
                {"member_skill_list": {"skill": "Python"}},
                {"skill": "PostgreSQL"},
                "Kubernetes",
                {"unexpected": "shape"},
            ],
        }
    )

    assert profile.skills == ["Python", "PostgreSQL", "Kubernetes"]


# ---------------------------------------------------------------------------
# Apollo
# ---------------------------------------------------------------------------
def test_apollo_does_not_translate_require_phone_into_an_email_filter() -> None:
    body = build_body(SearchQuery(titles=["Backend Engineer"], require_phone=True))

    assert "contact_email_status" not in body
