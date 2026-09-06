"""Health and capability endpoints.

Deliberately reports *whether* credentials exist, never their values.
"""

from __future__ import annotations

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
            "enabled": bool(settings.demo_call_redirect_number),
            "number": settings.demo_call_redirect_number or None,
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


@router.get("/hunar/ping")
async def hunar_ping() -> dict[str, Any]:
    return await get_hunar_client().ping()


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
