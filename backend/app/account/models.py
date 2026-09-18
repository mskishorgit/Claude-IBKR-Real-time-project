"""Plain data types for the account/portfolio view.

Mirrors the rest of the project's style (app/signals/models.py,
app/options/models.py): no ib_async imports here, so this stays trivially
testable. `AccountPosition` covers equities/ETFs/anything that isn't an
option; `AccountOptionPosition` is a separate (not inheriting) type for
options, which need strike/expiry/right/greeks the other positions don't
have — kept separate rather than bolting optional fields onto one shape,
since the two are genuinely different things to render.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True, slots=True)
class AccountPosition:
    con_id: int
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    quantity: float
    avg_cost: float
    market_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "con_id": self.con_id,
            "symbol": self.symbol,
            "sec_type": self.sec_type,
            "exchange": self.exchange,
            "currency": self.currency,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "market_price": self.market_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
        }


@dataclass(frozen=True, slots=True)
class AccountOptionPosition:
    con_id: int
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    quantity: float
    avg_cost: float
    market_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    expiry: str
    strike: float
    right: str
    delta: Optional[float] = None
    implied_vol: Optional[float] = None
    underlying_price: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "con_id": self.con_id,
            "symbol": self.symbol,
            "sec_type": self.sec_type,
            "exchange": self.exchange,
            "currency": self.currency,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "market_price": self.market_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "expiry": self.expiry,
            "strike": self.strike,
            "right": self.right,
            "delta": self.delta,
            "implied_vol": self.implied_vol,
            "underlying_price": self.underlying_price,
        }


@dataclass(frozen=True, slots=True)
class AccountSummary:
    account: str
    net_liquidation: Optional[float] = None
    buying_power: Optional[float] = None
    total_cash_value: Optional[float] = None
    realized_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "net_liquidation": self.net_liquidation,
            "buying_power": self.buying_power,
            "total_cash_value": self.total_cash_value,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
        }
