"""Framework-agnostic data types for the signal engine.

Deliberately free of any dependency on ib_async or FastAPI so the engine can
be constructed and unit-tested (or run against a CSV backtest) with plain
Python and no running IBKR connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Direction = Literal["long", "short"]


@dataclass(frozen=True, slots=True)
class Bar:
    """A single finalized OHLCV bar. Never a still-forming/partial bar —
    see MarketDataManager's bar-closed listener for why that distinction
    matters to the signal engine."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Signal:
    """A flagged potential entry raised by a rule."""

    ticker: str
    rule: str
    direction: Direction
    price: float
    volume: float
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "rule": self.rule,
            "direction": self.direction,
            "price": self.price,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }
