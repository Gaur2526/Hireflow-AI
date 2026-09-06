# syntax=docker/dockerfile:1
#
# Production image for the FastAPI backend.
#
#   docker build -f backend/Dockerfile -t hireflow-api backend
#   docker run --rm -p 8000:8000 --env-file backend/.env hireflow-api
#
# Stage 1 compiles wheels into a self-contained virtualenv; stage 2 copies only
# that virtualenv, so no compiler or build header ever reaches the final image.
# $PORT is honoured because Render, Railway and Fly all inject it.

# ---------------------------------------------------------------------------
# Stage 1 - builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Only needed for source-only sdists; never copied into the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Requirements first: this layer is cached until requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 - runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    HOST=0.0.0.0

# Non-root, no login shell, fixed uid so bind-mounted volumes are predictable.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser . .

# Default DATABASE_URL is sqlite:///./data/hireflow.db - the directory has to
# exist and be writable by the non-root user. NOTE: on Render free / Vercel this
# filesystem is ephemeral; point DATABASE_URL at Postgres for real deployments.
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8000

# stdlib-only probe: keeps curl (and its CVE surface) out of the final image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz',timeout=5).status==200 else 1)"]

# exec form via sh so ${PORT} is expanded at runtime, but uvicorn still ends up
# as PID 1 and receives SIGTERM directly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
