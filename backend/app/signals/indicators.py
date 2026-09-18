"""Small, dependency-free indicator building blocks shared by rules/engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import Bar


def ema_next(previous: float | None, price: float, period: int) -> float:
    """Next EMA value given the previous EMA (or None to seed with price)."""
    if previous is None:
        return price
    k = 2 / (period + 1)
    return price * k + previous * (1 - k)


def mean_std(values: list[float]) -> tuple[float, float]:
    """Population mean/std of a list of values. (0.0, 0.0) for an empty list."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n == 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / n
    return mean, variance**0.5


@dataclass
class SessionVwap:
    """Cumulative volume-weighted average price, reset at each new UTC
    calendar day. See the frontend's equivalent (indicators.ts) for the same
    approximation and its caveats around session boundaries."""

    _day: date | None = None
    _cum_pv: float = 0.0
    _cum_volume: float = 0.0

    def update(self, bar: Bar) -> float:
        day = bar.timestamp.date()
        if day != self._day:
            self._day = day
            self._cum_pv = 0.0
            self._cum_volume = 0.0
        typical_price = (bar.high + bar.low + bar.close) / 3
        self._cum_pv += typical_price * bar.volume
        self._cum_volume += bar.volume
        return self._cum_pv / self._cum_volume if self._cum_volume > 0 else typical_price
