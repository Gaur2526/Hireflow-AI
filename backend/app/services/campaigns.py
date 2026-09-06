"""Campaign orchestration: JD -> voice agent -> outbound calls -> answers.

Everything that talks to Hunar on behalf of a campaign lives here so the API
routers stay thin and the same logic is reachable from the background poller.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, ConflictError, UpstreamError, ValidationFailure
from app.core.logging import get_logger
from app.models import (
    ACTIVE_CALL_STATUSES,
    Call,
    CallStatus,
    Campaign,
    CampaignStatus,
    Candidate,
    CandidateStatus,
    Job,
)
from app.schemas.campaign import CallDefaults, CampaignCreate, CampaignStats
from app.schemas.job import JobCriteria, ScreeningQuestion
from app.services import screening
from app.services.hunar import HunarClient, get_hunar_client
from app.services.phone import is_fictional, normalise_phone
from app.services.screening import build_plan, build_result_schema

log = get_logger(__name__)

#: Hunar is happy with parallel call creation; keep it polite anyway.
_DISPATCH_CONCURRENCY = 5


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
async def create_campaign(
    db: Session,
    job: Job,
    payload: CampaignCreate,
    *,
    client: HunarClient | None = None,
) -> tuple[Campaign, list[dict[str, str]], list[str]]:
    """Create the Hunar agent and one PENDING call row per selected candidate."""
    client = client or get_hunar_client()
    warnings: list[str] = []

    candidates = _resolve_candidates(db, job, payload.candidate_ids)
    if not candidates:
        raise ValidationFailure(
            "Select at least one candidate with a usable phone number before launching."
        )

    criteria = JobCriteria(**(job.criteria or {}))
    questions = _resolve_questions(job, payload)
    plan = build_plan(criteria, questions, company=job.company)

    cfg = payload.agent_config
    agent_prompt = cfg.agent_prompt or plan.agent_prompt
    introduction = cfg.introduction or plan.introduction
    objective = cfg.objective or plan.objective
    result_prompt = cfg.result_prompt or plan.result_prompt
    result_schema = build_result_schema(questions)

    missing = screening.extract_placeholders(agent_prompt, introduction) - set(
        screening.CUSTOM_VARIABLES
    )
    if missing:
        raise ValidationFailure(
            "The agent script references variables that no call will supply: "
            + ", ".join(sorted(f"{{{m}}}" for m in missing)),
            details={"unknown_variables": sorted(missing)},
        )

    name = (payload.name or f"HireFlow AI — {job.title}")[:64]
    agent_config: dict[str, Any] = {
        "name": name,
        "language": cfg.language,
        "voice_persona": cfg.voice_persona,
        "persona_name": cfg.persona_name,
        "agent_prompt": agent_prompt,
        "objective": objective,
        "introduction": introduction,
        "result_prompt": result_prompt,
        "result_schema": result_schema,
        "questions": [q.model_dump() for q in questions],
    }

    campaign = Campaign(
        job_id=job.id,
        name=name,
        status=CampaignStatus.DRAFT,
        agent_config=agent_config,
        result_schema=result_schema,
        call_defaults=payload.call_defaults.model_dump(),
    )
    db.add(campaign)
    db.flush()

    # --- provision the voice agent -----------------------------------------
    try:
        if payload.reuse_agent_id:
            agent = await client.get_agent(payload.reuse_agent_id)
            campaign.hunar_agent_id = agent["id"]
            campaign.result_schema = agent.get("result_schema") or result_schema
            agent_config["reused"] = True
            warnings.append(f"Reusing existing Hunar agent {agent['id']}.")
        else:
            agent = await client.create_agent(
                name=name,
                language=cfg.language,
                voice_persona=cfg.voice_persona,
                persona_name=cfg.persona_name,
                agent_prompt=agent_prompt,
                objective=objective,
                introduction=introduction,
                result_prompt=result_prompt,
                result_schema=result_schema,
            )
            campaign.hunar_agent_id = agent["id"]
        agent_config["hunar_agent"] = {
            k: agent.get(k)
            for k in (
                "id",
                "status",
                "agent_code",
                "custom_variables",
                "required_variables",
            )
        }
        campaign.agent_config = agent_config
        campaign.status = CampaignStatus.AGENT_READY
    except AppError as exc:
        campaign.status = CampaignStatus.FAILED
        campaign.error = exc.message
        # Commit, not flush: the request-scoped session rolls back on the way
        # out, which would discard the row *and* the hunar_agent_id of an agent
        # that already exists upstream.
        db.commit()
        raise

    # Hunar derives custom_variables from {tokens} in agent_prompt +
    # introduction. Single-call creation 422s unless custom_data carries every
    # one of them, so check here rather than letting every call fail.
    custom_data = screening.build_custom_data(
        job_title=job.title, company=job.company, criteria=criteria
    )
    declared = set(agent.get("custom_variables") or [])
    unsupplied = declared - set(custom_data)
    if unsupplied:
        campaign.status = CampaignStatus.FAILED
        campaign.error = (
            "Hunar requires custom variables this campaign cannot supply: "
            + ", ".join(sorted(unsupplied))
        )
        db.commit()  # keep the orphaned agent id auditable across the rollback
        raise ValidationFailure(
            campaign.error,
            details={"missing_custom_data": sorted(unsupplied)},
        )

    agent_status = str(agent.get("status") or "").upper()
    if agent_status and agent_status != "ACTIVE":
        warnings.append(
            f"Hunar agent {campaign.hunar_agent_id} is {agent_status}, not ACTIVE. "
            "Calls will fail with 'Active agent version not found' until it activates."
        )

    # --- build the call queue ----------------------------------------------
    skipped: list[dict[str, str]] = []
    for candidate in candidates:
        number, valid = normalise_phone(
            candidate.phone, default_region=candidate.country_code
        )
        if not number:
            skipped.append(
                {
                    "candidate_id": candidate.id,
                    "name": candidate.full_name,
                    "reason": "No usable phone number",
                }
            )
            candidate.status = CandidateStatus.UNREACHABLE
            continue

        dialed, redirected = _apply_redirect(number)
        if is_fictional(number) and not redirected:
            skipped.append(
                {
                    "candidate_id": candidate.id,
                    "name": candidate.full_name,
                    "reason": "Demo number (+1-555-01XX) - set DEMO_CALL_REDIRECT_NUMBER to dial",
                }
            )
            candidate.status = CandidateStatus.UNREACHABLE
            continue

        call = Call(
            campaign_id=campaign.id,
            candidate_id=candidate.id,
            status=CallStatus.PENDING,
            dialed_number=dialed,
            dialed_redirected=redirected,
            custom_data={
                **custom_data,
                "candidate_current_role": candidate.title or "",
                "candidate_company": candidate.company or "",
            },
        )
        db.add(call)
        candidate.status = CandidateStatus.QUEUED
        if not valid:
            warnings.append(
                f"{candidate.full_name}: number {number} may not be dialable."
            )

    db.flush()
    if not campaign.calls:
        warnings.append("No dialable candidates - nothing was queued.")
    return campaign, skipped, warnings


def _resolve_candidates(db: Session, job: Job, ids: list[str]) -> list[Candidate]:
    stmt = select(Candidate).where(Candidate.job_id == job.id)
    if ids:
        stmt = stmt.where(Candidate.id.in_(ids))
    else:
        stmt = stmt.where(Candidate.status == CandidateStatus.SHORTLISTED)
    return list(db.scalars(stmt.order_by(Candidate.fit_score.desc())))


def _resolve_questions(job: Job, payload: CampaignCreate) -> list[ScreeningQuestion]:
    if payload.agent_config.questions:
        return payload.agent_config.questions
    stored = job.screening_questions or []
    if stored:
        return [ScreeningQuestion(**q) for q in stored]
    raise ValidationFailure(
        "This job has no screening questions yet. Parse the job description first."
    )


def _apply_redirect(number: str) -> tuple[str, bool]:
    """Route to the operator's test handset when DEMO_CALL_REDIRECT_NUMBER is set."""
    redirect = settings.demo_call_redirect_number.strip()
    if not redirect:
        return number, False
    normalised, _ = normalise_phone(redirect)
    return (normalised or redirect), True


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def _callback_config() -> dict[str, str] | None:
    if not settings.webhooks_available:
        return None
    base = (
        settings.public_base_url.rstrip("/") + settings.api_prefix + "/webhooks/hunar"
    )
    return {
        "call_status_callback_url": f"{base}/status",
        "call_recording_callback_url": f"{base}/recording",
        "call_result_callback_url": f"{base}/result",
        "call_summary_callback_url": f"{base}/summary",
    }


def _guardrails(defaults: CallDefaults) -> dict[str, Any] | None:
    if not defaults.allowed_days:
        return None
    return {
        "allowed_days": defaults.allowed_days,
        "earliest_call_time": defaults.earliest_call_time,
        "last_call_time": defaults.last_call_time,
    }


async def dispatch_campaign(
    db: Session, campaign: Campaign, *, client: HunarClient | None = None
) -> tuple[int, list[dict[str, str]], list[str]]:
    """Place every PENDING call. Returns ``(dispatched, skipped, warnings)``."""
    client = client or get_hunar_client()
    if not campaign.hunar_agent_id:
        raise ConflictError("This campaign has no Hunar agent yet.")

    defaults = CallDefaults(**(campaign.call_defaults or {}))
    pending = [c for c in campaign.calls if c.status == CallStatus.PENDING]
    if not pending:
        return 0, [], ["No pending calls to dispatch."]

    callback = _callback_config()
    warnings: list[str] = []
    if callback is None:
        warnings.append(
            "PUBLIC_BASE_URL is not set to a public https URL, so Hunar cannot "
            "call back. Results will be reconciled by polling instead."
        )

    retry_config = (
        {
            "max_retry_count": defaults.max_retry_count,
            "retry_interval_hours": defaults.retry_interval_hours,
        }
        if defaults.max_retry_count
        else None
    )
    guardrails = _guardrails(defaults)
    semaphore = asyncio.Semaphore(_DISPATCH_CONCURRENCY)

    async def _place(call: Call) -> tuple[Call, dict[str, Any] | None, str | None]:
        candidate = call.candidate
        async with semaphore:
            try:
                response = await client.create_call(
                    agent_id=campaign.hunar_agent_id,
                    callee_name=candidate.first_name or candidate.full_name,
                    mobile_number=call.dialed_number or "",
                    custom_data=call.custom_data,
                    request_id=f"rc-{campaign.id[:8]}-{call.id[:8]}",
                    from_phone_number=defaults.from_phone_number,
                    timezone=defaults.timezone,
                    callback_config=callback,
                    retry_config=retry_config,
                    guardrails=guardrails,
                )
                return call, response, None
            except UpstreamError as exc:
                return call, None, exc.message
            except AppError as exc:
                return call, None, exc.message

    results = await asyncio.gather(*(_place(c) for c in pending))

    dispatched = 0
    skipped: list[dict[str, str]] = []
    for call, response, error in results:
        if error or not response:
            call.status = CallStatus.FAILED
            call.error = error or "Unknown dispatch error"
            call.candidate.status = CandidateStatus.UNREACHABLE
            skipped.append(
                {
                    "candidate_id": call.candidate_id,
                    "name": call.candidate.full_name,
                    "reason": call.error,
                }
            )
            continue
        call.hunar_call_id = response.get("id")
        call.request_id = response.get("request_id")
        call.status = response.get("status") or CallStatus.NOT_STARTED
        call.error = None
        call.raw = response
        call.last_synced_at = _now()
        call.sync_source = "dispatch"
        call.candidate.status = CandidateStatus.CALLING
        dispatched += 1

    campaign.status = CampaignStatus.RUNNING if dispatched else CampaignStatus.FAILED
    if not dispatched and skipped:
        campaign.error = skipped[0]["reason"]
    db.flush()
    log.info(
        "campaign.dispatched",
        campaign_id=campaign.id,
        dispatched=dispatched,
        skipped=len(skipped),
    )
    return dispatched, skipped, warnings


# ---------------------------------------------------------------------------
# Reconciliation (webhook + poller share this)
# ---------------------------------------------------------------------------
_STATUS_TO_CANDIDATE = {
    CallStatus.COMPLETED: CandidateStatus.COMPLETED,
    CallStatus.NOT_CONNECTED: CandidateStatus.UNREACHABLE,
    CallStatus.FAILED: CandidateStatus.UNREACHABLE,
    CallStatus.CANCELLED: CandidateStatus.COMPLETED,
}

#: How far along a call is. Hunar retries callbacks on 4XX *and* 5XX, so the
#: same delivery can arrive twice and out of order; ranking lets a replay be
#: recognised as old news instead of walking the row backwards.
_STATUS_RANK = {
    CallStatus.PENDING: 0,
    CallStatus.NOT_STARTED: 1,
    CallStatus.SCHEDULED: 2,
    CallStatus.INITIATED: 3,
    CallStatus.RINGING: 4,
    CallStatus.IN_PROGRESS: 5,
}
_TERMINAL_RANK = 6


def _status_rank(status: str) -> int:
    try:
        return _STATUS_RANK.get(CallStatus(status), _TERMINAL_RANK)
    except ValueError:
        return -1


def _is_stale_status(call: Call, payload: dict[str, Any]) -> bool:
    """True when ``payload`` describes an earlier moment than the stored row."""
    incoming = str(payload.get("status") or "")
    if not incoming or incoming == call.status:
        return False
    # Hunar legitimately re-opens a finished call for a retry.
    if str(payload.get("redial_status") or "").upper() == "REDIALING":
        return False
    retry_count = payload.get("retry_count")
    if isinstance(retry_count, int) and retry_count > (call.retry_count or 0):
        return False
    current, new = _status_rank(call.status), _status_rank(incoming)
    if new < 0:  # a status we don't model: let it through rather than guess
        return False
    # A terminal status is the verdict for this attempt; a *different* terminal
    # status afterwards is a duplicate delivery, not progress.
    return new < current or current >= _TERMINAL_RANK


def apply_call_payload(call: Call, payload: dict[str, Any], *, source: str) -> bool:
    """Merge a Hunar call object (or webhook body) into a local Call row.

    Returns True when something actually changed. Fields absent from the payload
    are left alone, so a partial webhook never wipes data a poll already fetched.
    """
    before = (
        call.status,
        call.result,
        call.recording_url,
        call.duration_seconds,
        call.lifecycle_status,
    )

    # Everything describing *this attempt* is skipped for a replayed delivery;
    # results and recordings still merge, because those only ever add data.
    stale = _is_stale_status(call, payload)
    if not stale:
        if payload.get("status"):
            call.status = str(payload["status"])
        for field, key in (
            ("lifecycle_status", "lifecycle_status"),
            ("engagement_status", "engagement_status"),
            ("answered_by", "answered_by"),
            ("call_ended_by", "call_ended_by"),
        ):
            value = payload.get(key)
            if value not in (None, "", "-"):
                setattr(call, field, str(value))

        for field, key in (
            ("duration_seconds", "duration_seconds"),
            ("user_speech_duration", "user_speech_duration"),
        ):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                setattr(call, field, float(value))

        if isinstance(payload.get("retry_count"), int):
            call.retry_count = payload["retry_count"]

        for field, key in (("started_at", "started_at"), ("ended_at", "ended_at")):
            parsed = _parse_dt(payload.get(key))
            if parsed:
                setattr(call, field, parsed)

    if payload.get("recording_url"):
        call.recording_url = str(payload["recording_url"])
    if isinstance(payload.get("result"), dict) and payload["result"]:
        call.result = payload["result"]
    if isinstance(payload.get("custom_data"), dict) and payload["custom_data"]:
        call.custom_data = {**call.custom_data, **payload["custom_data"]}

    if payload.get("id") and not call.hunar_call_id:
        call.hunar_call_id = str(payload["id"])

    call.raw = {**(call.raw or {}), **payload}
    call.last_synced_at = _now()
    call.sync_source = source

    try:
        status = CallStatus(call.status)
    except ValueError:
        status = None
    if status and call.candidate:
        mapped = _STATUS_TO_CANDIDATE.get(status)
        if mapped:
            call.candidate.status = mapped
        elif status in ACTIVE_CALL_STATUSES:
            call.candidate.status = CandidateStatus.CALLING

    after = (
        call.status,
        call.result,
        call.recording_url,
        call.duration_seconds,
        call.lifecycle_status,
    )
    return before != after


async def sync_campaign(
    db: Session, campaign: Campaign, *, client: HunarClient | None = None
) -> int:
    """Poll Hunar for every non-terminal call in this campaign."""
    client = client or get_hunar_client()
    if not client.configured:
        return 0

    active = {s.value for s in ACTIVE_CALL_STATUSES}
    open_calls = [
        c
        for c in campaign.calls
        if c.hunar_call_id
        and (c.status in active or (c.status == CallStatus.COMPLETED and not c.result))
    ]
    updated = await _sync_calls(db, open_calls, client)
    _refresh_campaign_status(campaign)
    db.flush()
    return updated


async def sync_stale_calls(db: Session, *, client: HunarClient | None = None) -> int:
    """Background poller entry point: reconcile every in-flight call."""
    client = client or get_hunar_client()
    if not client.configured:
        return 0

    cutoff = _now() - timedelta(minutes=settings.call_poll_max_age_minutes)
    # Result extraction lands *after* a call reaches COMPLETED, so a completed
    # call with an empty result is still worth re-polling.
    stmt = (
        select(Call)
        .where(Call.hunar_call_id.is_not(None))
        # Age off the last successful sync, not creation: Hunar parks
        # guardrail-deferred calls in SCHEDULED until the next morning and
        # retries hours later, which a created_at window would drop entirely.
        .where(or_(Call.last_synced_at >= cutoff, Call.created_at >= cutoff))
        .where(
            or_(
                Call.status.in_([s.value for s in ACTIVE_CALL_STATUSES]),
                and_(
                    Call.status == CallStatus.COMPLETED,
                    or_(Call.result.is_(None), Call.result == {}),
                ),
            )
        )
        # Least recently synced first, so a bounded batch still rotates fairly.
        .order_by(Call.last_synced_at.asc(), Call.created_at.asc())
        .limit(100)
    )
    calls = list(db.scalars(stmt))
    if not calls:
        return 0

    updated = await _sync_calls(db, calls, client)
    for campaign in {c.campaign for c in calls if c.campaign}:
        _refresh_campaign_status(campaign)
    db.flush()
    return updated


async def _sync_calls(db: Session, calls: list[Call], client: HunarClient) -> int:
    if not calls:
        return 0
    semaphore = asyncio.Semaphore(_DISPATCH_CONCURRENCY)

    async def _fetch(call: Call) -> tuple[Call, dict[str, Any] | None, str | None]:
        async with semaphore:
            try:
                return call, await client.get_call(call.hunar_call_id or ""), None
            except AppError as exc:
                return call, None, exc.message

    updated = 0
    for call, payload, error in await asyncio.gather(*(_fetch(c) for c in calls)):
        if error or not payload:
            log.warning("call.sync_failed", call_id=call.id, error=error)
            continue
        if apply_call_payload(call, payload, source="poll"):
            updated += 1
    return updated


def _refresh_campaign_status(campaign: Campaign) -> None:
    statuses = {c.status for c in campaign.calls}
    if not statuses or statuses == {CallStatus.PENDING.value}:
        return
    active = {s.value for s in ACTIVE_CALL_STATUSES} | {CallStatus.PENDING.value}
    if statuses & active:
        campaign.status = CampaignStatus.RUNNING
    else:
        campaign.status = CampaignStatus.COMPLETED


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
_TRUTHY = {"true", "yes", "y", "1", "interested", "high"}


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return False


def compute_stats(calls: list[Call]) -> CampaignStats:
    stats = CampaignStats(total=len(calls))
    durations: list[float] = []
    for call in calls:
        status = call.status
        if status == CallStatus.PENDING:
            stats.pending += 1
        elif status == CallStatus.COMPLETED:
            stats.completed += 1
        elif status == CallStatus.NOT_CONNECTED:
            stats.not_connected += 1
        elif status == CallStatus.FAILED:
            stats.failed += 1
        elif status == CallStatus.CANCELLED:
            stats.cancelled += 1
        else:
            stats.in_flight += 1

        if (call.answered_by or "").upper() == "HUMAN":
            stats.answered_human += 1
        if call.duration_seconds:
            durations.append(call.duration_seconds)

        result = call.result or {}
        if _is_true(result.get("consent_to_continue")):
            stats.consented += 1
        if _is_true(result.get("open_to_opportunity")) or _is_true(
            result.get("interest_level")
        ):
            stats.interested += 1
        if _is_true(result.get("do_not_contact_requested")):
            stats.do_not_contact += 1

    if durations:
        stats.avg_duration_seconds = round(sum(durations) / len(durations), 1)
    stats.total_talk_minutes = round(sum(durations) / 60.0, 2)
    return stats


#: Status -> the CampaignStats counter it increments; anything else is in-flight.
_STATUS_COUNTER = {
    CallStatus.PENDING: "pending",
    CallStatus.COMPLETED: "completed",
    CallStatus.NOT_CONNECTED: "not_connected",
    CallStatus.FAILED: "failed",
    CallStatus.CANCELLED: "cancelled",
}


def _json_truthy(key: str) -> Any:
    """``_is_true`` as SQL sees it (SQLite renders a JSON bool as 1/0)."""
    return func.lower(Call.result[key].as_string()).in_(sorted(_TRUTHY))


def compute_stats_across(db: Session) -> CampaignStats:
    """Whole-database call stats, aggregated in SQL.

    The landing dashboard is the most-hit endpoint in the app, so it must not
    scale with lifetime call volume the way :func:`compute_stats` does.
    """
    stats = CampaignStats()
    for status, count in db.execute(
        select(Call.status, func.count()).group_by(Call.status)
    ):
        stats.total += count
        field = _STATUS_COUNTER.get(status)
        counter = field or "in_flight"
        setattr(stats, counter, getattr(stats, counter) + count)

    stats.answered_human = (
        db.scalar(
            select(func.count())
            .select_from(Call)
            .where(func.upper(Call.answered_by) == "HUMAN")
        )
        or 0
    )

    total_seconds, spoken = db.execute(
        select(
            func.sum(Call.duration_seconds), func.count(Call.duration_seconds)
        ).where(Call.duration_seconds > 0)
    ).one()
    if spoken:
        stats.avg_duration_seconds = round((total_seconds or 0.0) / spoken, 1)
    stats.total_talk_minutes = round((total_seconds or 0.0) / 60.0, 2)

    for field, keys in (
        ("consented", ("consent_to_continue",)),
        ("interested", ("open_to_opportunity", "interest_level")),
        ("do_not_contact", ("do_not_contact_requested",)),
    ):
        setattr(
            stats,
            field,
            db.scalar(
                select(func.count())
                .select_from(Call)
                .where(or_(*(_json_truthy(key) for key in keys)))
            )
            or 0,
        )
    return stats


_TYPE_PREFIX = re.compile(r"^\s*(?:string|boolean|number|enum)\s*(?:—|–|-)\s*", re.I)


def answer_columns(result_schema: dict[str, Any]) -> list[dict[str, str]]:
    """Turn Hunar's result_schema into ordered dashboard columns."""
    columns: list[dict[str, str]] = []
    for key, spec in (result_schema or {}).items():
        text = str(spec)
        kind = "string"
        lowered = text.lower()
        if lowered.startswith("boolean"):
            kind = "boolean"
        elif lowered.startswith("number"):
            kind = "number"
        elif "one of:" in lowered:
            kind = "enum"
        # Strip only the leading "<type> — " marker: an unanchored "-" split
        # would chop the question at any hyphen inside it ("hands-on").
        description = _TYPE_PREFIX.sub("", text).strip()
        columns.append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "type": kind,
                "description": description[:240],
            }
        )
    return columns


# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
