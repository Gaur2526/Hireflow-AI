"""Shared HTTP plumbing for vendor people-search clients."""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx

from app.core.errors import UpstreamError
from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 30.0


async def request_json(
    provider: str,
    method: Literal["GET", "POST"],
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[Any, int]:
    """Return ``(payload, elapsed_ms)`` or raise :class:`UpstreamError`."""
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params={
                    k: v for k, v in (params or {}).items() if v not in (None, [], "")
                }
                or None,
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise UpstreamError(
            f"Could not reach {provider}: {exc}", provider=provider
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        body = _safe(response)
        log.warning(
            "people_search.error",
            provider=provider,
            status=response.status_code,
            body=str(body)[:400],
        )
        raise UpstreamError(
            _describe(provider, response.status_code, body),
            provider=provider,
            status=response.status_code,
            details=body,
        )
    try:
        return response.json(), elapsed_ms
    except ValueError as exc:
        raise UpstreamError(
            f"{provider} returned a non-JSON response.", provider=provider
        ) from exc


def _safe(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:1000]


def _describe(provider: str, status: int, body: Any) -> str:
    detail = ""
    if isinstance(body, dict):
        detail = str(
            body.get("error")
            or body.get("message")
            or body.get("detail")
            or body.get("description")
            or ""
        )[:300]
    elif isinstance(body, str):
        detail = body[:300]

    base = {
        401: f"{provider} rejected the API key (401).",
        402: f"{provider} reports no credits left (402).",
        403: f"{provider} denied this request - the plan may not include search (403).",
        404: f"{provider} found no matching records (404).",
        422: f"{provider} rejected the query (422).",
        429: f"{provider} rate limit exceeded (429).",
    }.get(status, f"{provider} request failed with HTTP {status}.")
    return f"{base} {detail}".strip()


def first(*values: Any) -> Any:
    """First non-empty value."""
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
