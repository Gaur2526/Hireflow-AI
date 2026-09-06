"""Proxycurl (Nubela) - retired upstream, kept as an explicit tombstone.

The assignment lists Proxycurl as a candidate people-search vendor, but the API
no longer exists: LinkedIn Corporation v. Nubela Pte. Ltd. (No. 3:25-cv-00828,
N.D. Cal., filed 2025-01-24) ended with Nubela shutting Proxycurl down on
2025-07-04. Every documented endpoint - ``/v2/search/person/``, ``/v2/linkedin``
and ``/api/contact-api/personal-contact`` - now answers **HTTP 410 Gone**, and
``nubela.co/proxycurl/docs`` 301-redirects to the docs for NinjaPear, the
founder's successor product.

NinjaPear is *not* a drop-in replacement: it is keyed on company websites rather
than LinkedIn profiles, exposes ``GET /api/v2/employee/profile`` and
``GET /api/v1/employee/work-email`` only, has no person-search endpoint, and
returns no personal phone numbers.

The provider is therefore registered but permanently unavailable. It fails fast
with an explanation instead of silently returning nothing, and the registry
falls back to a live provider.
"""

from __future__ import annotations

from app.core.errors import ProviderNotConfigured
from app.services.people_search.base import (
    PeopleSearchProvider,
    SearchQuery,
    SearchResult,
)

RETIREMENT_NOTE = (
    "Proxycurl was permanently shut down on 2025-07-04 following LinkedIn Corp. "
    "v. Nubela Pte. Ltd. (No. 3:25-cv-00828, N.D. Cal.). All of its endpoints "
    "return HTTP 410 Gone and existing API keys no longer work. Use People Data "
    "Labs or Coresignal instead, or the built-in demo dataset."
)


class ProxycurlProvider(PeopleSearchProvider):
    name = "proxycurl"
    label = "Proxycurl (retired)"
    docs_url = "https://nubela.co/docs"
    requires_key = True

    #: Marks the provider as permanently unavailable in the settings screen.
    retired = True
    retirement_note = RETIREMENT_NOTE

    @property
    def configured(self) -> bool:
        return False

    async def search(self, query: SearchQuery) -> SearchResult:
        raise ProviderNotConfigured(RETIREMENT_NOTE)
