from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.base import get_db
from app.models import Campaign, Job

DbSession = Session


def db_session() -> Iterator[Session]:
    yield from get_db()


def get_job(job_id: str, db: Session = Depends(db_session)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id} was not found.")
    return job


def get_campaign(campaign_id: str, db: Session = Depends(db_session)) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise NotFoundError(f"Campaign {campaign_id} was not found.")
    return campaign
