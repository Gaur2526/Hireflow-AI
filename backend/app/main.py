"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import campaigns, candidates, jobs, meta, webhooks
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.db.base import init_db
from app.workers.poller import run_poller

configure_logging()
log = get_logger(__name__)

DESCRIPTION = """\
Paste a job description, source matching people from a people-search API, let an
AI voice agent screen them over the phone, and read the structured answers back
in a dashboard.

* **People search** - People Data Labs, Apollo.io, Proxycurl or Coresignal behind
  one interface, plus a built-in demo dataset so the flow works with no vendor key.
* **Voice AI** - [Hunar Voice Agents](https://api.voice.hunar.ai/docs/external/).
  The job description becomes the agent's prompt and its `result_schema`.
* **Dashboard** - each screening answer becomes a column, backed by webhooks with
  polling as a fallback.
"""


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    log.info(
        "startup",
        environment=settings.environment,
        people_provider=settings.people_provider,
        hunar_configured=settings.hunar_configured,
        llm_configured=settings.llm_configured,
        webhooks_available=settings.webhooks_available,
    )

    stop = asyncio.Event()
    task: asyncio.Task[None] | None = None
    if settings.enable_call_poller and settings.hunar_configured:
        task = asyncio.create_task(run_poller(stop))

    try:
        yield
    finally:
        stop.set()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(task, timeout=5)


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- error handling --------------------------------------------------------
@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_failed",
                "message": "The request body did not validate.",
                "details": _readable(exc.errors()),
            }
        },
    )


def _readable(errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for err in errors[:20]:
        location = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        out.append({"field": location or "body", "message": str(err.get("msg", ""))})
    return out


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_error", error=str(exc)[:500], exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Something went wrong on our side.",
            }
        },
    )


# --- routes ----------------------------------------------------------------
for router in (
    meta.router,
    jobs.router,
    candidates.router,
    campaigns.router,
    webhooks.router,
):
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# --- optional single-container mode ----------------------------------------
# When SERVE_FRONTEND=true the exported Next.js build is served from the same
# process, so the whole product is one deployable unit with no CORS setup.
def _mount_frontend() -> None:
    dist = Path(settings.frontend_dist_dir)
    if not settings.serve_frontend or not dist.is_dir():
        return

    app.mount("/_next", StaticFiles(directory=dist / "_next"), name="next-assets")
    root = dist.resolve()

    def _within(candidate: Path) -> bool:
        """Starlette URL-decodes the path param, so "%2e%2e" arrives as "..";
        nothing normalises it away before we join it onto the static root."""
        try:
            return candidate.resolve().is_relative_to(root)
        except OSError:
            return False

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if candidate.is_file() and _within(candidate):
            return FileResponse(candidate)
        html = dist / f"{full_path.rstrip('/')}.html"
        if html.is_file() and _within(html):
            return FileResponse(html)
        return FileResponse(dist / "index.html")

    log.info("frontend.mounted", directory=str(dist))


_mount_frontend()
