"""FIFO round-trip matching for equity/ETF fills into closed trades.

IBKR reports fills one execution at a time — a scalp entry and its exit
are two separate Execution records with no link between them. This turns
a same-symbol stream of BOT/SLD fills into JournalTrade round trips the
way a FIFO trade blotter would, flip-aware: a fill that closes an
existing lot and then reverses into the opposite direction is split into
a close (returned as a trade) and a freshly opened lot in the new
direction (kept for the next fill to match against).

Options are NOT run through this — they're taken directly from
PositionManager's own entry/close tracking (see execution_sync.py),
which already has the round trip with no matching needed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

from .models import Direction, JournalTrade

# Equities/ETFs trade share-for-share; only option contracts (handled
# separately, see module docstring) carry a 100x multiplier.
SHARE_MULTIPLIER = 1
_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class RawFill:
    """One IBKR execution report for an equity/ETF, framework-agnostic
    (see execution_sync.py for the ib_async Fill -> RawFill conversion)."""

    exec_id: str
    symbol: str
    sec_type: str
    side: str  # "BOT" or "SLD"
    shares: float
    price: float
    time: datetime


@dataclass
class _Lot:
    direction: Direction
    remaining: float
    price: float
    time: datetime


class FifoTradeMatcher:
    """Stateful, per-symbol FIFO matcher. Feed fills in time order via
    `add_fill`; matched round trips are returned as they close."""

    def __init__(self) -> None:
        self._lots: dict[str, deque[_Lot]] = {}

    def add_fill(self, fill: RawFill) -> list[JournalTrade]:
        incoming_direction: Direction = "long" if fill.side == "BOT" else "short"
        lots = self._lots.setdefault(fill.symbol, deque())
        remaining = fill.shares
        trades: list[JournalTrade] = []

        while remaining > _EPSILON and lots and lots[0].direction != incoming_direction:
            lot = lots[0]
            close_qty = min(lot.remaining, remaining)
            sign = 1 if lot.direction == "long" else -1
            realized = sign * (fill.price - lot.price) * close_qty * SHARE_MULTIPLIER
            trades.append(
                JournalTrade(
                    id=f"{fill.symbol}:{lot.time.isoformat()}:{fill.exec_id}:{len(trades)}",
                    symbol=fill.symbol,
                    sec_type=fill.sec_type,
                    direction=lot.direction,
                    quantity=close_qty,
                    entry_time=lot.time,
                    entry_price=lot.price,
                    exit_time=fill.time,
                    exit_price=fill.price,
                    realized_pnl=realized,
                    source="execution",
                )
            )
            lot.remaining -= close_qty
            remaining -= close_qty
            if lot.remaining <= _EPSILON:
                lots.popleft()

        if remaining > _EPSILON:
            lots.append(_Lot(direction=incoming_direction, remaining=remaining, price=fill.price, time=fill.time))

        return trades
