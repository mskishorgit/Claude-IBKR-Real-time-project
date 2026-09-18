"""Turns an ib_async Ticker into our own OptionQuote — shared by chain.py
(chain browsing) and positions.py (open-position P/L), so both interpret
IBKR's "no data" sentinels (-1, NaN) the same way exactly once.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from .models import OptionContractKey, OptionQuote

if TYPE_CHECKING:
    from ib_async import Ticker


def _is_missing(value: Optional[float]) -> bool:
    if value is None:
        return True
    try:
        return math.isnan(value)
    except TypeError:
        return True


def _clean_price(value: Optional[float]) -> Optional[float]:
    """For fields that are always positive when present: bid/ask/last,
    implied vol, underlying price. IBKR sends -1 (or NaN) as "no data"."""
    if _is_missing(value) or value <= 0:
        return None
    return value


def _clean_delta(value: Optional[float]) -> Optional[float]:
    """Delta is legitimately negative (puts) or exactly 0 — only NaN/None
    means "no data", unlike the price-like fields above."""
    if _is_missing(value):
        return None
    return value


def quote_from_ticker(ticker: "Ticker", key: OptionContractKey) -> Optional[OptionQuote]:
    """None if the ticker has no usable price data at all yet (e.g. the
    very first callback right after subscribing, before IBKR has sent
    anything back)."""
    bid = _clean_price(ticker.bid)
    ask = _clean_price(ticker.ask)
    last = _clean_price(ticker.last)
    if bid is None and ask is None and last is None:
        return None

    greeks = ticker.modelGreeks
    delta = _clean_delta(greeks.delta) if greeks else None
    implied_vol = _clean_price(greeks.impliedVol) if greeks else None
    underlying_price = _clean_price(greeks.undPrice) if greeks else None

    return OptionQuote(
        contract=key,
        bid=bid,
        ask=ask,
        last=last,
        delta=delta,
        implied_vol=implied_vol,
        underlying_price=underlying_price,
        timestamp=datetime.now(timezone.utc),
    )
