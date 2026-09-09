from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Wall clock, UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)
