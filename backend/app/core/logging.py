"""Structured logging with automatic secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

from app.core.config import settings

# Anything that looks like a credential is scrubbed before it can reach a log
# sink. Belt-and-braces: we also never pass keys into log calls on purpose.
_SECRET_PATTERNS = [
    re.compile(r"(hunar_va_(?:live|test)_sk_)[A-Za-z0-9_\-]+"),
    re.compile(r"(sk-ant-)[A-Za-z0-9_\-]+"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{12,}"),
]

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "x-api-key",
    "authorization",
    "hunar_api_key",
    "anthropic_api_key",
    "pdl_api_key",
    "apollo_api_key",
    "proxycurl_api_key",
    "coresignal_api_key",
    "password",
    "token",
    "secret",
}


def mask(value: str | None, keep: int = 4) -> str:
    """Return a display-safe fingerprint of a secret (never the secret)."""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]}"


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key, val in list(event_dict.items()):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = mask(str(val)) if val else ""
        elif isinstance(val, str):
            for pat in _SECRET_PATTERNS:
                val = pat.sub(r"\1<redacted>", val)
            event_dict[key] = val
    return event_dict


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    renderer: Any = (
        structlog.dev.ConsoleRenderer(colors=settings.environment == "local")
        if settings.environment == "local"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
