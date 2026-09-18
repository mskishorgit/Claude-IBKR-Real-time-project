"""Plain data types for the options trading panel.

Kept free of ib_async imports (mirrors app/signals/models.py) so the pure
logic here — stop/target price computation, P/L math — can be unit tested
without a running IBKR connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

Right = Literal["C", "P"]
Action = Literal["BUY", "SELL"]
OrderType = Literal["MKT", "LMT"]
Direction = Literal["long", "short"]
PositionStatus = Literal["open", "closing", "closed"]
StopTargetKind = Literal["pct", "abs"]

# Standard US equity option contract multiplier (shares per contract).
OPTION_MULTIPLIER = 100


@dataclass(frozen=True, slots=True)
class OptionContractKey:
    """Identifies one option contract without needing a live ib_async
    Contract/conId — used everywhere outside the ib_async-touching modules
    (chain.py, orders.py) so the rest of the code stays broker-agnostic."""

    symbol: str
    expiry: str  # "YYYYMMDD"
    strike: float
    right: Right

    def label(self) -> str:
        return f"{self.symbol} {self.expiry} {self.strike:g}{self.right}"


@dataclass
class OptionQuote:
    contract: OptionContractKey
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    delta: Optional[float]
    implied_vol: Optional[float]
    underlying_price: Optional[float]
    timestamp: datetime

    def mid(self) -> Optional[float]:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.last

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.contract.symbol,
            "expiry": self.contract.expiry,
            "strike": self.contract.strike,
            "right": self.contract.right,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "delta": self.delta,
            "implied_vol": self.implied_vol,
            "underlying_price": self.underlying_price,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class StopTargetConfig:
    """A stop-loss or profit-target the user sets when entering a position.

    `kind="abs"`: `value` is dollars of option premium *per contract*
    (e.g. 50 = stop out at a $50/contract loss, i.e. a $0.50/share move).
    `kind="pct"`: `value` is a percent of the entry premium (e.g. 25 = 25%).
    """

    kind: StopTargetKind
    value: float


@dataclass
class PendingOrder:
    """A previewed-but-not-yet-submitted order. Single-use and short-lived —
    see OptionsOrderService.confirm_order: it's popped (never reused) the
    moment confirm is called, successful or not, so a retry always requires
    a fresh preview against a fresh quote."""

    id: str
    contract: OptionContractKey
    action: Action
    order_type: OrderType
    quantity: int
    limit_price: Optional[float]
    quote_at_preview: OptionQuote
    trading_mode: str
    stop_loss: Optional[StopTargetConfig]
    profit_target: Optional[StopTargetConfig]
    created_at: datetime
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_id": self.id,
            "symbol": self.contract.symbol,
            "expiry": self.contract.expiry,
            "strike": self.contract.strike,
            "right": self.contract.right,
            "action": self.action,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "quote": self.quote_at_preview.to_dict(),
            "trading_mode": self.trading_mode,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass
class OptionPosition:
    id: str
    contract: OptionContractKey
    direction: Direction
    quantity: int  # always positive; `direction` carries the sign
    entry_price: float
    entry_time: datetime
    order_id: int
    stop_loss: Optional[StopTargetConfig] = None
    profit_target: Optional[StopTargetConfig] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    status: PositionStatus = "open"
    stop_alert_fired: bool = False
    target_alert_fired: bool = False
    last_quote: Optional[OptionQuote] = None
    close_order_id: Optional[int] = None
    close_price: Optional[float] = None
    close_time: Optional[datetime] = None
    realized_pnl: Optional[float] = None

    def unrealized_pnl(self) -> Optional[float]:
        if self.status != "open" or self.last_quote is None:
            return None
        current = self.last_quote.mid()
        if current is None:
            return None
        sign = 1 if self.direction == "long" else -1
        return sign * (current - self.entry_price) * self.quantity * OPTION_MULTIPLIER

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.contract.symbol,
            "expiry": self.contract.expiry,
            "strike": self.contract.strike,
            "right": self.contract.right,
            "direction": self.direction,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "status": self.status,
            "stop_alert_fired": self.stop_alert_fired,
            "target_alert_fired": self.target_alert_fired,
            "last_quote": self.last_quote.to_dict() if self.last_quote else None,
            "unrealized_pnl": self.unrealized_pnl(),
            "close_price": self.close_price,
            "close_time": self.close_time.isoformat() if self.close_time else None,
            "realized_pnl": self.realized_pnl,
        }
