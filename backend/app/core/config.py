"""Application settings.

Every secret is read from the environment (or a local, git-ignored ``.env``).
Nothing sensitive is ever hard-coded, logged, or returned by the API - the
``/api/meta/providers`` endpoint only reports *whether* a credential is present.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PeopleProvider = Literal["mock", "pdl", "apollo", "proxycurl", "coresignal"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---------------------------------------------------------------
    app_name: str = "HireFlow AI"
    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # Comma-separated list, or "*" for any origin.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Public base URL of *this* backend. Required for Hunar webhooks to reach
    # us; when empty we fall back to polling the Hunar API instead.
    public_base_url: str = ""

    # --- persistence -------------------------------------------------------
    database_url: str = "sqlite:///./data/hireflow.db"

    # --- Hunar Voice AI ----------------------------------------------------
    hunar_api_key: str = ""
    hunar_base_url: str = "https://api.voice.hunar.ai"
    hunar_api_prefix: str = "/external/v1"
    #: Hunar signs callbacks with the API key itself; this is only for the case
    #: where an org is issued a separate signing secret.
    hunar_webhook_secret: str = ""
    hunar_timeout_seconds: float = 30.0

    # Default calling configuration (overridable per campaign from the UI).
    default_country_code: str = "IN"
    default_timezone: str = "Asia/Kolkata"
    default_voice_persona: str = "NEHA"
    default_language: str = "ENGLISH"

    # --- people search providers ------------------------------------------
    people_provider: PeopleProvider = "mock"
    pdl_api_key: str = ""
    apollo_api_key: str = ""
    proxycurl_api_key: str = ""
    coresignal_api_key: str = ""

    # Providers rarely return dialable mobile numbers on free tiers. When set,
    # every outbound call is placed to this number instead of the candidate's,
    # which makes the whole pipeline demonstrable end-to-end without spamming
    # real people. The UI shows a prominent banner whenever it is active.
    demo_call_redirect_number: str = ""

    # --- LLM (optional) ----------------------------------------------------
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = 4096

    # --- background sync ---------------------------------------------------
    call_poll_interval_seconds: int = 15
    call_poll_max_age_minutes: int = 180
    enable_call_poller: bool = True

    # --- static frontend (single-container deploys) ------------------------
    serve_frontend: bool = False
    frontend_dist_dir: str = "static"

    max_candidates_per_search: int = Field(default=25, ge=1, le=100)

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    # --- derived -----------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def hunar_configured(self) -> bool:
        return bool(self.hunar_api_key)

    @property
    def webhook_signing_secret(self) -> str:
        """Hunar signs webhooks with the API key unless a secret is issued."""
        return self.hunar_webhook_secret or self.hunar_api_key

    @property
    def llm_configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def webhooks_available(self) -> bool:
        """True when Hunar (or the local stub) can reach our callback URLs.

        Production needs https. Plain http is accepted only for loopback, which
        is what ``tools/hunar_stub.py`` posts back to during local testing.
        """
        url = self.public_base_url.strip()
        if not url:
            return False
        if url.startswith("https://"):
            return True
        return url.startswith(("http://localhost", "http://127.0.0.1"))

    def provider_key(self, provider: str) -> str:
        return {
            "pdl": self.pdl_api_key,
            "apollo": self.apollo_api_key,
            "proxycurl": self.proxycurl_api_key,
            "coresignal": self.coresignal_api_key,
            "mock": "built-in",
        }.get(provider, "")


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
