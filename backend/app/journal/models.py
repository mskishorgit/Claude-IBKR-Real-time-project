"""Plain data types for the trading journal.

Kept free of ib_async and sqlite3 imports (mirrors app/signals/models.py
and app/options/models.py) so the P/L matching and stats logic can be unit
tested without a live IBKR connection or a database file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Optional

Direction = Literal["long", "short"]
TradeSource = Literal["execution", "options_panel"]


@dataclass(frozen=True, slots=True)
class SignalLogEntry:
    """A fired signal, persisted so a later trade's entry can be linked
    back to the rule (if any) that triggered it."""

    id: str
    ticker: str
    rule: str
    direction: Direction
    price: float
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class JournalTrade:
    """One closed round trip. Equities/ETFs are matched FIFO from IBKR's
    execution history (see fifo_matcher.py); options are taken directly
    from this app's own PositionManager close event, which already has
    the entry/exit price and realized P/L with the contract multiplier
    applied (see execution_sync.py)."""

    id: str
    symbol: str
    sec_type: str  # "STK", "OPT", ...
    direction: Direction
    quantity: float
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    realized_pnl: float
    source: TradeSource
    expiry: Optional[str] = None
    strike: Optional[float] = None
    right: Optional[str] = None
    signal_rule: Optional[str] = None
    signal_timestamp: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "sec_type": self.sec_type,
            "direction": self.direction,
            "quantity": self.quantity,
            "entry_time": self.entry_time.isoformat(),
            "entry_price": self.entry_price,
            "exit_time": self.exit_time.isoformat(),
            "exit_price": self.exit_price,
            "realized_pnl": self.realized_pnl,
            "source": self.source,
            "expiry": self.expiry,
            "strike": self.strike,
            "right": self.right,
            "signal_rule": self.signal_rule,
            "signal_timestamp": self.signal_timestamp.isoformat() if self.signal_timestamp else None,
        }


@dataclass(frozen=True, slots=True)
class DayPnl:
    day: date
    realized_pnl: float
    trade_count: int

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.day.isoformat(), "realized_pnl": self.realized_pnl, "trade_count": self.trade_count}


@dataclass(frozen=True, slots=True)
class MonthStats:
    year: int
    month: int
    total_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: Optional[float]
    avg_win: Optional[float]
    avg_loss: Optional[float]
    largest_win: Optional[float]
    largest_loss: Optional[float]
    # (ISO week's Monday date, that week's realized P/L), weeks touching
    # the requested month only — see README for the boundary-week caveat.
    weekly_pnl: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "total_pnl": self.total_pnl,
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": self.win_rate,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "largest_win": self.largest_win,
            "largest_loss": self.largest_loss,
            "weekly_pnl": [{"week_start": w, "realized_pnl": p} for w, p in self.weekly_pnl],
        }
