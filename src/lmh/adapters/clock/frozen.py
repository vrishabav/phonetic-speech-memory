from __future__ import annotations

from datetime import UTC, datetime, timedelta


class FrozenClock:
    """Deterministic clock for tests, fixtures and reproducible evaluation.

    Every eval case that involves decay, dormancy or an activation window pins
    its own clock, so a result produced today is identical to one produced next
    year.
    """

    def __init__(self, at: datetime | str | None = None) -> None:
        if isinstance(at, str):
            at = datetime.fromisoformat(at)
        self._at = at or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        if self._at.tzinfo is None:
            self._at = self._at.replace(tzinfo=UTC)

    def now(self) -> datetime:
        return self._at

    def advance(self, *, days: float = 0.0, seconds: float = 0.0) -> FrozenClock:
        self._at = self._at + timedelta(days=days, seconds=seconds)
        return self

    def set(self, at: datetime) -> FrozenClock:
        self._at = at if at.tzinfo else at.replace(tzinfo=UTC)
        return self
