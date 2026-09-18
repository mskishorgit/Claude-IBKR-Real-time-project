"""Relative-volume-vs-time-of-day tracking.

Compares today's cumulative volume, at the current bar's time of day, against
the average cumulative volume observed at that same time of day across prior
sessions this tracker has seen. There is no persistence across process
restarts and no external historical warm-up by default, so the baseline is
only as good as how long the engine has been running (or how much history
the backtest/CSV mode fed it first) — this is a deliberate scope limit for
this step, not an attempt at a "real" multi-day RVOL data product.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date

from .models import Bar


@dataclass(frozen=True, slots=True)
class RelativeVolumeReading:
    ratio: float | None
    sessions_observed: int
    cumulative_volume: float
    baseline_cumulative_volume: float | None


@dataclass
class _SymbolRelativeVolume:
    max_sessions: int
    current_day: date | None = None
    current_cumulative: float = 0.0
    # time-of-day key ("HH:MM") -> cumulative volume at that point, this session
    current_snapshots: dict[str, float] = field(default_factory=dict)
    # completed sessions, oldest first, each a {time_of_day_key: cumulative_volume} map
    sessions: deque[dict[str, float]] = field(default_factory=deque)

    def _roll_day_if_needed(self, day: date) -> None:
        if self.current_day is None:
            self.current_day = day
            return
        if day == self.current_day:
            return
        self.sessions.append(self.current_snapshots)
        while len(self.sessions) > self.max_sessions:
            self.sessions.popleft()
        self.current_day = day
        self.current_cumulative = 0.0
        self.current_snapshots = {}

    def update(self, bar: Bar) -> RelativeVolumeReading:
        self._roll_day_if_needed(bar.timestamp.date())
        self.current_cumulative += bar.volume
        key = bar.timestamp.strftime("%H:%M")
        self.current_snapshots[key] = self.current_cumulative

        baseline_samples = [session[key] for session in self.sessions if key in session]
        if not baseline_samples:
            return RelativeVolumeReading(
                ratio=None,
                sessions_observed=len(self.sessions),
                cumulative_volume=self.current_cumulative,
                baseline_cumulative_volume=None,
            )

        baseline = sum(baseline_samples) / len(baseline_samples)
        ratio = self.current_cumulative / baseline if baseline > 0 else None
        return RelativeVolumeReading(
            ratio=ratio,
            sessions_observed=len(self.sessions),
            cumulative_volume=self.current_cumulative,
            baseline_cumulative_volume=baseline,
        )


class RelativeVolumeTracker:
    """Per-symbol relative-volume-by-time-of-day tracker."""

    def __init__(self, max_sessions: int = 20) -> None:
        self._max_sessions = max_sessions
        self._by_symbol: dict[str, _SymbolRelativeVolume] = {}

    def update(self, bar: Bar) -> RelativeVolumeReading:
        state = self._by_symbol.setdefault(
            bar.symbol, _SymbolRelativeVolume(max_sessions=self._max_sessions)
        )
        return state.update(bar)
