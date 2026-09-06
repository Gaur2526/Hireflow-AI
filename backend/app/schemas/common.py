from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer


def _iso_utc(value: datetime | None) -> str | None:
    """Always emit an offset so browsers do not read UTC as local time."""
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat()


#: A datetime that serialises as an unambiguous UTC ISO-8601 string.
UTCDatetime = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 50


class Ack(BaseModel):
    ok: bool = True
    message: str | None = None
    data: dict[str, Any] | None = None
