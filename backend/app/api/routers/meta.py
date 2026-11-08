"""Health and capability endpoints.

Deliberately reports *whether* credentials exist, never their values.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import mask
from app.db.base import engine
from app.services import hunar as hunar_mod
from app.services.hunar import get_hunar_client
from app.services.llm import get_llm
from app.services.people_search.registry import provider_status

router = APIRouter(prefix="/meta", tags=["meta"])

_HUNAR_HEALTH_TTL_SECONDS = 60
_hunar_health_cache: tuple[float, dict[str, Any]] | None = None


@router.get("/health")
def health() -> dict[str, Any]:
    db_ok = True
    db_error = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - only on a broken deployment
        db_ok, db_error = False, str(exc)[:200]

    return {
        "status": "ok" if db_ok else "degraded",
        "environment": settings.environment,
        "database": {"ok": db_ok, "error": db_error},
        "hunar_configured": settings.hunar_configured,
        "llm_configured": settings.llm_configured,
        "people_provider": settings.people_provider,
        "webhooks_available": settings.webhooks_available,
    }


@router.get("/config")
def config() -> dict[str, Any]:
    """What the frontend needs to render honest status badges."""
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "people_provider": settings.people_provider,
        "providers": provider_status(),
        "hunar": {
            "configured": settings.hunar_configured,
            "key_fingerprint": mask(settings.hunar_api_key),
            "base_url": settings.hunar_base_url,
            "webhook_secret_set": bool(settings.hunar_webhook_secret),
        },
        "llm": {
            "configured": settings.llm_configured,
            "model": settings.llm_model if settings.llm_configured else None,
        },
        "webhooks": {
            "available": settings.webhooks_available,
            "public_base_url": settings.public_base_url or None,
            "poll_interval_seconds": settings.call_poll_interval_seconds,
        },
        "demo_call_redirect": {
            "enabled": bool(settings.demo_redirect_number),
            "number": _mask_redirect(settings.demo_redirect_number),
        },
        "voice_options": {
            "personas": hunar_mod.VOICE_PERSONAS,
            "languages": hunar_mod.LANGUAGES,
            "timezones": hunar_mod.TIMEZONES,
            "allowed_days": hunar_mod.ALLOWED_DAYS,
        },
        "defaults": {
            "voice_persona": settings.default_voice_persona,
            "language": settings.default_language,
            "timezone": settings.default_timezone,
            "country_code": settings.default_country_code,
            "max_candidates_per_search": settings.max_candidates_per_search,
        },
    }


def _mask_redirect(number: str) -> str | None:
    digits = "".join(char for char in number if char.isdigit())
    if not digits:
        return None
    suffix = digits[-5:]
    prefix = f"+{digits[:-10]}" if len(digits) > 10 else "+"
    return f"{prefix} ••••• {suffix}"


@router.get("/hunar/ping")
async def hunar_ping() -> dict[str, Any]:
    """Shared authenticated Hunar health check, cached for one minute."""
    global _hunar_health_cache
    now = time.monotonic()
    if (
        _hunar_health_cache is not None
        and now - _hunar_health_cache[0] < _HUNAR_HEALTH_TTL_SECONDS
    ):
        return dict(_hunar_health_cache[1])

    if not settings.hunar_configured:
        result: dict[str, Any] = {
            "status": "not_configured",
            "ok": False,
            "reason": "HUNAR_API_KEY is not set. Add it to the backend environment.",
        }
    else:
        ping = await get_hunar_client().ping()
        result = {
            **ping,
            "status": "ok" if ping.get("ok") else "failing",
        }
    _hunar_health_cache = (now, result)
    return dict(result)


@router.get("/hunar/agents")
async def hunar_agents(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """Agents already living in the Hunar org - useful for reuse."""
    return await get_hunar_client().list_agents(page=page, page_size=page_size)


@router.get("/hunar/numbers")
async def hunar_numbers() -> dict[str, Any]:
    return await get_hunar_client().list_numbers()


@router.get("/llm/status")
def llm_status() -> dict[str, Any]:
    client = get_llm()
    return {
        "configured": client.configured,
        "model": client.model if client.configured else None,
    }
