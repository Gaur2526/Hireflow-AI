"""Async client for the Hunar Voice Agents API.

Mirrors ``https://api.voice.hunar.ai/external/v1`` exactly as published in the
OpenAPI document. Everything the rest of the app needs from Hunar goes through
here, so there is a single place that knows about auth, retries and error
translation.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.errors import ProviderNotConfigured, UpstreamError
from app.core.logging import get_logger, mask

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Enum values accepted by the upstream API (kept in sync with the OpenAPI spec)
# ---------------------------------------------------------------------------
VOICE_PERSONAS = ["NEHA", "ROY", "ZOE", "SAM", "MIRA", "EESHA"]

LANGUAGES = [
    "ENGLISH",
    "HINDI",
    "TAMIL",
    "TELUGU",
    "KANNADA",
    "MARATHI",
    "MALAYALAM",
    "GUJARATI",
    "BENGALI",
    "TURKISH",
    "ARABIC",
    "SPANISH",
]

CALL_STATUSES = [
    "NOT_STARTED",
    "SCHEDULED",
    "INITIATED",
    "RINGING",
    "IN_PROGRESS",
    "COMPLETED",
    "NOT_CONNECTED",
    "CANCELLED",
    "FAILED",
]

TIMEZONES = [
    "Asia/Kolkata",
    "America/New_York",
    "America/Los_Angeles",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Anchorage",
    "Pacific/Honolulu",
    "Asia/Riyadh",
    "Europe/London",
]

ALLOWED_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

COUNTRY_CODES = ["IN", "US", "SA", "GB"]

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class _Retryable(Exception):
    """Internal marker so tenacity retries transient upstream failures."""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


class HunarClient:
    """Thin, typed wrapper around the Hunar REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        prefix: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.hunar_api_key
        self.base_url = (base_url or settings.hunar_base_url).rstrip("/")
        self.prefix = prefix or settings.hunar_api_prefix
        self.timeout = timeout or settings.hunar_timeout_seconds
        self._transport = transport

    # -- plumbing -----------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{self.prefix}{path}"

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hireflow-ai/1.0",
        }

    def _require_key(self) -> None:
        if not self.configured:
            raise ProviderNotConfigured(
                "HUNAR_API_KEY is not set. Add it to the backend environment to place calls."
            )

    async def _request(
        self,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        attempts: int = 3,
    ) -> Any:
        self._require_key()
        url = self._url(path)
        clean_params = _clean_params(params or {})

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential(multiplier=0.6, min=0.6, max=6),
                retry=retry_if_exception_type(_Retryable),
                reraise=True,
            ):
                with attempt:
                    try:
                        async with httpx.AsyncClient(
                            timeout=self.timeout, transport=self._transport
                        ) as client:
                            response = await client.request(
                                method,
                                url,
                                params=clean_params or None,
                                json=json_body,
                                headers=self._headers(),
                            )
                    except httpx.HTTPError as exc:  # network-level failure
                        raise _Retryable(exc) from exc

                    if response.status_code in _RETRYABLE_STATUS:
                        raise _Retryable(
                            UpstreamError(
                                _describe(response.status_code, _safe_body(response)),
                                provider="hunar",
                                status=response.status_code,
                                details=_safe_body(response),
                            )
                        )

                    if response.status_code >= 400:
                        body = _safe_body(response)
                        log.warning(
                            "hunar.error",
                            method=method,
                            path=path,
                            status=response.status_code,
                            body=_truncate(body),
                        )
                        raise UpstreamError(
                            _describe(response.status_code, body),
                            provider="hunar",
                            status=response.status_code,
                            details=body,
                        )

                    if response.status_code == 204 or not response.content:
                        return None
                    return response.json()
        except _Retryable as exc:
            # ``reraise=True`` hands back the *marker* once the attempts run
            # out. Callers only ever catch AppError/UpstreamError, so unwrap it
            # here - otherwise an unavailable Hunar surfaces as an opaque 500.
            original = exc.original
            if isinstance(original, UpstreamError):
                raise original from None
            log.warning(
                "hunar.unreachable", method=method, path=path, error=str(original)[:200]
            )
            raise UpstreamError(
                f"Could not reach Hunar: {original}", provider="hunar"
            ) from original

        raise UpstreamError(
            "Hunar request failed", provider="hunar"
        )  # pragma: no cover

    # -- agents -------------------------------------------------------------
    async def list_agents(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/agents/",
            params={
                "page": page,
                "page_size": page_size,
                "status": status,
                "language": language,
            },
        )

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/agents/{agent_id}/")

    async def create_agent(
        self,
        *,
        name: str,
        voice_persona: str,
        agent_prompt: str,
        objective: str,
        introduction: str,
        result_prompt: str,
        result_schema: dict[str, Any],
        language: str = "ENGLISH",
        persona_name: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name[:64],
            "language": language,
            "voice_persona": voice_persona,
            "agent_prompt": agent_prompt,
            "objective": objective,
            "introduction": introduction,
            "result_prompt": result_prompt,
            "result_schema": result_schema,
        }
        if persona_name:
            body["persona_name"] = persona_name[:64]
        return await self._request("POST", "/agents/", json_body=body)

    async def update_agent(self, agent_id: str, **fields: Any) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/agents/{agent_id}/",
            json_body={k: v for k, v in fields.items() if v is not None},
        )

    # -- calls --------------------------------------------------------------
    async def create_call(
        self,
        *,
        agent_id: str,
        callee_name: str,
        mobile_number: str,
        custom_data: dict[str, str] | None = None,
        request_id: str | None = None,
        from_phone_number: str | None = None,
        timezone: str | None = None,
        callback_config: dict[str, str] | None = None,
        retry_config: dict[str, int] | None = None,
        guardrails: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "agent_id": agent_id,
            "callee_name": callee_name,
            "mobile_number": mobile_number,
        }
        if custom_data:
            # Hunar requires custom_data values to be strings.
            body["custom_data"] = {
                k: _as_str(v) for k, v in custom_data.items() if v is not None
            }
        if request_id:
            body["request_id"] = request_id[:64]
        if from_phone_number:
            body["from_phone_number"] = from_phone_number
        if timezone:
            body["timezone"] = timezone
        if callback_config:
            body["callback_config"] = callback_config
        if retry_config:
            body["retry_config"] = retry_config
        if guardrails:
            body["guardrails"] = guardrails
        return await self._request("POST", "/calls/", json_body=body)

    async def create_bulk_calls(
        self,
        *,
        agent_id: str,
        recipients: list[dict[str, Any]],
        request_id: str | None = None,
        timezone: str | None = None,
        callback_config: dict[str, str] | None = None,
        retry_config: dict[str, int] | None = None,
        guardrails: dict[str, Any] | None = None,
        remove_invalid_rows: bool = True,
        remove_duplicate_phone_numbers: bool = True,
    ) -> Any:
        data = []
        for r in recipients:
            entry: dict[str, Any] = {
                "callee_name": r["callee_name"],
                "mobile_number": r["mobile_number"],
            }
            if r.get("custom_data"):
                entry["custom_data"] = {
                    k: _as_str(v) for k, v in r["custom_data"].items() if v is not None
                }
            data.append(entry)

        body: dict[str, Any] = {
            "agent_id": agent_id,
            "data": data,
            "remove_invalid_rows": remove_invalid_rows,
            "remove_duplicate_phone_numbers": remove_duplicate_phone_numbers,
        }
        if request_id:
            body["request_id"] = request_id[:64]
        if timezone:
            body["timezone"] = timezone
        if callback_config:
            body["callback_config"] = callback_config
        if retry_config:
            body["retry_config"] = retry_config
        if guardrails:
            body["guardrails"] = guardrails
        return await self._request("POST", "/calls/bulk/", json_body=body)

    async def get_call(self, call_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/calls/{call_id}/")

    async def list_calls(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        agent_id: str | list[str] | None = None,
        status: str | list[str] | None = None,
        campaign_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/calls/",
            params={
                "page": page,
                "page_size": min(page_size, 200),
                "agent_id": agent_id,
                "status": status,
                "campaign_id": campaign_id,
            },
        )

    # -- numbers ------------------------------------------------------------
    async def list_numbers(
        self, *, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        return await self._request(
            "GET", "/numbers/", params={"page": page, "page_size": page_size}
        )

    # -- health -------------------------------------------------------------
    async def ping(self) -> dict[str, Any]:
        """Cheap authenticated round-trip used by /api/meta/health."""
        try:
            data = await self.list_agents(page=1, page_size=1)
            return {
                "ok": True,
                "agents_visible": data.get("count", 0),
                "key": mask(self.api_key),
            }
        except ProviderNotConfigured as exc:
            return {"ok": False, "reason": exc.message, "key": ""}
        except UpstreamError as exc:
            return {
                "ok": False,
                "reason": exc.message,
                "status": exc.upstream_status,
                "key": mask(self.api_key),
            }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values; httpx encodes list values as repeated query params."""
    return {k: v for k, v in params.items() if v is not None and v != []}


def _as_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_as_str(v) for v in value)
    return json.dumps(value, ensure_ascii=False)


def _safe_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text[:2000]


def _truncate(value: Any, limit: int = 500) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text[:limit]


def _describe(status: int, body: Any) -> str:
    """Render Hunar's ``{success, message, details}`` envelope as one sentence."""
    detail = ""
    if isinstance(body, dict):
        detail = str(
            body.get("message") or body.get("detail") or body.get("error") or ""
        )[:400]
        fields = body.get("details")
        if isinstance(fields, list) and fields:
            parts = [
                f"{f.get('field_name')}: {f.get('error_msg')}"
                for f in fields[:5]
                if isinstance(f, dict)
            ]
            if parts:
                detail = f"{detail} ({'; '.join(parts)})".strip()
    elif isinstance(body, str):
        detail = body[:400]

    base = {
        401: "Hunar rejected the API key (401). Check HUNAR_API_KEY - the assignment key expires.",
        402: "Hunar reports the subscription is expired or calling minutes are exhausted (402).",
        403: "Hunar denied this request (403).",
        404: "Hunar resource not found (404).",
        422: "Hunar rejected the request payload (422).",
    }.get(status, f"Hunar request failed with HTTP {status}.")
    return f"{base} {detail}".strip()


def get_hunar_client() -> HunarClient:
    return HunarClient()
