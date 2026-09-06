from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    DRAFT = "DRAFT"
    PARSED = "PARSED"
    SOURCED = "SOURCED"
    ARCHIVED = "ARCHIVED"


class CandidateSource(StrEnum):
    PDL = "pdl"
    APOLLO = "apollo"
    PROXYCURL = "proxycurl"
    CORESIGNAL = "coresignal"
    MOCK = "mock"
    MANUAL = "manual"


class CandidateStatus(StrEnum):
    SOURCED = "SOURCED"
    SHORTLISTED = "SHORTLISTED"
    REJECTED = "REJECTED"
    QUEUED = "QUEUED"
    CALLING = "CALLING"
    COMPLETED = "COMPLETED"
    UNREACHABLE = "UNREACHABLE"


class CampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    AGENT_READY = "AGENT_READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CallStatus(StrEnum):
    """Mirrors Hunar's CallStatus enum, plus a local pre-dispatch state."""

    PENDING = "PENDING"  # local only: row created, not yet sent to Hunar
    NOT_STARTED = "NOT_STARTED"
    SCHEDULED = "SCHEDULED"
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NOT_CONNECTED = "NOT_CONNECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = {
    CallStatus.COMPLETED,
    CallStatus.NOT_CONNECTED,
    CallStatus.CANCELLED,
    CallStatus.FAILED,
}

ACTIVE_CALL_STATUSES = [
    s for s in CallStatus if s not in _TERMINAL and s != CallStatus.PENDING
]
