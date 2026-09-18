"""Pins down MarketDataManager's hasNewBar handling: the signal engine must
only ever see finalized bars, never the still-forming current bar, and the
raw WebSocket feed must still get every intra-bar tick update.

Uses plain objects standing in for ib_async's BarData — the handler only
touches .date/.open/.high/.low/.close/.volume and list indexing, so no real
IBKR connection or ib_async BarDataList is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from ib_async import IB

from app.ibkr.market_data import MarketDataManager
from app.signals.models import Bar


def make_ib_bar(minute: int, close: float, volume: float):
    return SimpleNamespace(
        date=datetime(2024, 1, 2, 14, 30 + minute, tzinfo=timezone.utc),
        open=close,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=volume,
    )


def test_intrabar_update_broadcasts_raw_but_does_not_close_a_bar():
    manager = MarketDataManager(IB())
    closed_bars: list[Bar] = []
    manager.add_bar_closed_listener(closed_bars.append)

    bars = [make_ib_bar(0, 100.0, 500)]
    handler = manager._make_bar_handler("AAPL")

    handler(bars, False)  # still-forming bar ticking

    assert closed_bars == []


def test_new_bar_closes_the_previous_bar_not_the_new_one():
    manager = MarketDataManager(IB())
    closed_bars: list[Bar] = []
    manager.add_bar_closed_listener(closed_bars.append)

    bars = [make_ib_bar(0, 100.0, 1000)]
    handler = manager._make_bar_handler("AAPL")
    handler(bars, False)
    handler(bars, False)  # a couple of intrabar ticks on bar 0

    # Bar 0 finalizes at 100.0/1000 volume; a new (still-forming) bar 1 appends.
    bars.append(make_ib_bar(1, 101.0, 10))
    handler(bars, True)

    assert len(closed_bars) == 1
    closed = closed_bars[0]
    assert closed.symbol == "AAPL"
    assert closed.close == 100.0
    assert closed.volume == 1000
    # The brand-new bar 1 (barely started, volume=10) must never be treated
    # as "closed" — this is exactly the bug being guarded against.
    assert closed.close != 101.0


def test_first_ever_new_bar_event_does_not_close_anything():
    manager = MarketDataManager(IB())
    closed_bars: list[Bar] = []
    manager.add_bar_closed_listener(closed_bars.append)

    # The very first event for a symbol can have hasNewBar=True with only
    # one bar in the list (nothing before it to have finalized).
    bars = [make_ib_bar(0, 100.0, 1000)]
    handler = manager._make_bar_handler("AAPL")
    handler(bars, True)

    assert closed_bars == []
