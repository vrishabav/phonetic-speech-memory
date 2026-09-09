"""Time is a dependency.

Decay, recency and activation windows are all functions of time. A test that
cannot freeze the clock is not testing decay, it is testing today's date.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware, UTC."""
        ...
