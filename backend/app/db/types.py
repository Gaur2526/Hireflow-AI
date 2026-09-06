"""Timezone-safe datetime column.

SQLite has no native timestamp type, so ``DateTime(timezone=True)`` silently
round-trips a naive value. Anything downstream then reads it as local time -
a call placed a minute ago renders as "6h ago" in IST.

This decorator normalises on the way in (always store UTC) and re-attaches UTC
on the way out, so the application only ever sees aware datetimes on both
SQLite and Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        return dialect.type_descriptor(DateTime(timezone=dialect.name != "sqlite"))

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        # SQLite compares timestamps as strings, so store them naive-UTC to keep
        # ordering and range filters correct.
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
