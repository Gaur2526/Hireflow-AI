"""Shared test fixtures.

Everything in this module runs *before* any ``app.*`` import so the application
picks up a throwaway SQLite file and fake credentials instead of the developer's
real ``.env``.  Nothing here may ever touch the network.
"""

from __future__ import annotations

import os
import socket
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# 1. Environment -- MUST happen before ``app.core.config`` is imported.
# ---------------------------------------------------------------------------
#: Obviously fake. The shape mirrors a real Hunar key so the log redaction
#: patterns are exercised, but this value is not, and never was, a credential.
FAKE_HUNAR_KEY = "hunar_va_test_sk_0000000000000000_pytest"
FAKE_REDIRECT_NUMBER = "+919876543210"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="hireflow-tests-"))
_DB_PATH = _TMP_DIR / "test.db"

os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_DB_PATH}",
        "ENVIRONMENT": "local",
        "LOG_LEVEL": "INFO",  # exercise the log calls; pytest captures the output
        "HUNAR_API_KEY": FAKE_HUNAR_KEY,
        "HUNAR_WEBHOOK_SECRET": "",
        "HUNAR_BASE_URL": "https://api.voice.hunar.ai",
        "ANTHROPIC_API_KEY": "",
        "PEOPLE_PROVIDER": "mock",
        "PDL_API_KEY": "",
        "APOLLO_API_KEY": "",
        "PROXYCURL_API_KEY": "",
        "CORESIGNAL_API_KEY": "",
        "PUBLIC_BASE_URL": "",
        "DEMO_CALL_REDIRECT_NUMBER": "",
        "ENABLE_CALL_POLLER": "false",
        "SERVE_FRONTEND": "false",
        "DEFAULT_COUNTRY_CODE": "IN",
        "CORS_ORIGINS": "*",
    }
)

import app.core.config as config_module  # noqa: E402

# The module-level ``settings`` singleton was built at import time; rebuild it
# from the environment above so a stale cached instance can never leak in.
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
settings_obj = config_module.settings

assert str(_DB_PATH) in settings_obj.database_url, "test DB was not wired up"
assert settings_obj.hunar_api_key == FAKE_HUNAR_KEY

# Now it is safe to import everything that binds to ``settings``.
import respx as respx_lib  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.api.deps import db_session  # noqa: E402
from app.db.base import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Call,
    CallStatus,
    Campaign,
    CampaignStatus,
    Candidate,
    CandidateStatus,
    Job,
    JobStatus,
    SearchRun,
    WebhookEvent,
)

HUNAR_HOST = "https://api.voice.hunar.ai"
AGENTS_URL = f"{HUNAR_HOST}/external/v1/agents/"
CALLS_URL = f"{HUNAR_HOST}/external/v1/calls/"


# ---------------------------------------------------------------------------
# 2. Absolute network guard
# ---------------------------------------------------------------------------
class NetworkAccessAttempted(RuntimeError):
    """Raised when a test tries to open a real socket."""


@pytest.fixture(scope="session", autouse=True)
def _no_real_network() -> Iterator[None]:
    """Fail loudly if anything escapes respx and reaches a real host."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection

    def _blocked(*args: Any, **kwargs: Any) -> Any:
        raise NetworkAccessAttempted(
            "A test attempted a real network connection "
            f"({args[1:] or args}). Every outbound call must be mocked with respx."
        )

    socket.socket.connect = _blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked  # type: ignore[method-assign]
    socket.create_connection = _blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.create_connection = real_create  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 3. Database
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> Iterator[None]:
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    """Every test starts from an empty database."""
    yield
    with SessionLocal() as cleanup:
        for model in (WebhookEvent, Call, Campaign, Candidate, SearchRun, Job):
            cleanup.execute(delete(model))
        cleanup.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    """A session for arranging fixtures and asserting on persisted state.

    Call :meth:`Session.expire_all` (or the ``reread`` fixture) after an HTTP
    request so the identity map does not hand back pre-request state.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture
def reread(db: Session):
    """``reread()`` -> forget everything cached, then read fresh rows."""

    def _reread() -> Session:
        db.expire_all()
        return db

    return _reread


# ---------------------------------------------------------------------------
# 4. Settings helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def settings():
    """The live settings singleton every app module holds a reference to."""
    return settings_obj


@pytest.fixture
def hunar_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Guarantee a (fake) Hunar API key for the duration of a test."""
    monkeypatch.setattr(settings_obj, "hunar_api_key", FAKE_HUNAR_KEY)
    monkeypatch.setattr(settings_obj, "hunar_webhook_secret", "")
    return FAKE_HUNAR_KEY


@pytest.fixture
def demo_redirect(monkeypatch: pytest.MonkeyPatch) -> str:
    """Turn on DEMO_CALL_REDIRECT_NUMBER for this test."""
    monkeypatch.setattr(settings_obj, "demo_call_redirect_number", FAKE_REDIRECT_NUMBER)
    return FAKE_REDIRECT_NUMBER


# ---------------------------------------------------------------------------
# 5. HTTP client
# ---------------------------------------------------------------------------
@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient with the DB dependency explicitly overridden for tests."""

    def _override_db() -> Iterator[Session]:
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[db_session] = _override_db
    # ``raise_server_exceptions=False`` lets us assert on the 500 envelope the
    # app's own exception handler produces.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def respx_mock() -> Iterator[respx_lib.MockRouter]:
    """respx router; any un-registered request raises and fails the test."""
    with respx_lib.mock(assert_all_called=False) as router:
        yield router


# ---------------------------------------------------------------------------
# 6. Row factories
# ---------------------------------------------------------------------------
class Factory:
    """Minimal, valid rows for each entity. Override anything via kwargs.

    Every row is committed, not just flushed: the API under test runs in its
    own session, so uncommitted fixture rows would be invisible to it.
    """

    def __init__(self, session: Session) -> None:
        self.db = session

    def _persist(self, row: Any) -> Any:
        self.db.add(row)
        self.db.commit()
        return row

    # -- job ---------------------------------------------------------------
    def job(self, **kw: Any) -> Job:
        criteria = kw.pop(
            "criteria",
            {
                "role_title": "Senior Backend Engineer",
                "titles": ["Senior Backend Engineer", "Backend Engineer"],
                "seniority": ["senior"],
                "must_have_skills": ["Python", "PostgreSQL", "Kubernetes"],
                "nice_to_have_skills": ["Kafka"],
                "min_years": 5.0,
                "max_years": 9.0,
                "locations": ["Bengaluru"],
                "countries": ["IN"],
                "summary": "Senior Backend Engineer. Targets 5+ years.",
            },
        )
        questions = kw.pop("screening_questions", None)
        if questions is None:
            from app.services.screening import BASELINE_QUESTIONS

            questions = [q.model_dump() for q in BASELINE_QUESTIONS]
        from app.schemas.job import ScreeningQuestion
        from app.services.screening import build_result_schema

        job = Job(
            title=kw.pop("title", "Senior Backend Engineer"),
            company=kw.pop("company", "Acme Payments"),
            location=kw.pop("location", "Bengaluru"),
            description=kw.pop("description", "A backend role. " * 10),
            status=kw.pop("status", JobStatus.PARSED),
            criteria=criteria,
            screening_questions=questions,
            result_schema=kw.pop(
                "result_schema",
                build_result_schema([ScreeningQuestion(**q) for q in questions]),
            ),
            parsed_by=kw.pop("parsed_by", "heuristic"),
            **kw,
        )
        return self._persist(job)

    # -- candidate ---------------------------------------------------------
    def candidate(self, job: Job, **kw: Any) -> Candidate:
        name = kw.pop("full_name", "Priya Iyer")
        first, _, last = name.partition(" ")
        candidate = Candidate(
            job_id=job.id,
            dedupe_key=kw.pop("dedupe_key", uuid.uuid4().hex),
            source=kw.pop("source", "mock"),
            full_name=name,
            first_name=kw.pop("first_name", first or name),
            last_name=kw.pop("last_name", last or None),
            title=kw.pop("title", "Senior Backend Engineer"),
            headline=kw.pop("headline", "Senior Backend Engineer at Razorpay"),
            company=kw.pop("company", "Razorpay"),
            location=kw.pop("location", "Bengaluru, Karnataka, India"),
            country_code=kw.pop("country_code", "IN"),
            linkedin_url=kw.pop("linkedin_url", "https://www.linkedin.com/in/priya"),
            email=kw.pop("email", "priya@example.com"),
            phone=kw.pop("phone", "+919876500001"),
            phone_is_valid=kw.pop("phone_is_valid", True),
            years_experience=kw.pop("years_experience", 7.0),
            seniority=kw.pop("seniority", "senior"),
            skills=kw.pop("skills", ["Python", "PostgreSQL", "Kubernetes"]),
            experience=kw.pop("experience", []),
            education=kw.pop("education", []),
            fit_score=kw.pop("fit_score", 92.0),
            fit_breakdown=kw.pop("fit_breakdown", {}),
            fit_reasons=kw.pop("fit_reasons", []),
            status=kw.pop("status", CandidateStatus.SHORTLISTED),
            **kw,
        )
        return self._persist(candidate)

    # -- campaign ----------------------------------------------------------
    def campaign(self, job: Job, **kw: Any) -> Campaign:
        from app.schemas.campaign import CallDefaults

        campaign = Campaign(
            job_id=job.id,
            name=kw.pop("name", "HireFlow AI — Senior Backend Engineer"),
            status=kw.pop("status", CampaignStatus.AGENT_READY),
            hunar_agent_id=kw.pop("hunar_agent_id", "agent_test_1"),
            agent_config=kw.pop("agent_config", {}),
            result_schema=kw.pop("result_schema", dict(job.result_schema or {})),
            call_defaults=kw.pop("call_defaults", CallDefaults().model_dump()),
            **kw,
        )
        return self._persist(campaign)

    # -- call --------------------------------------------------------------
    def call(self, campaign: Campaign, candidate: Candidate, **kw: Any) -> Call:
        call = Call(
            campaign_id=campaign.id,
            candidate_id=candidate.id,
            status=kw.pop("status", CallStatus.PENDING),
            dialed_number=kw.pop("dialed_number", candidate.phone),
            dialed_redirected=kw.pop("dialed_redirected", False),
            custom_data=kw.pop("custom_data", {}),
            result=kw.pop("result", {}),
            raw=kw.pop("raw", {}),
            **kw,
        )
        return self._persist(call)


@pytest.fixture
def factory(db: Session) -> Factory:
    return Factory(db)
