"""Real-time 1-minute bar streaming for a runtime-configurable ticker list.

Uses reqHistoricalData(..., keepUpToDate=True) rather than reqRealTimeBars,
because reqRealTimeBars only ever delivers 5-second bars — keepUpToDate
historical bars are the documented way to get a live-updating 1-minute bar
from ib_async/ib_insync.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from ib_async import IB, Stock

from ..signals.models import Bar
from .rate_limiter import AsyncRateLimiter

logger = logging.getLogger(__name__)

# IBKR's own documented historical-data pacing rule: no more than 6
# requests in any rolling 2-second window. See rate_limiter.py.
HISTORICAL_RATE_LIMIT_MAX_CALLS = 6
HISTORICAL_RATE_LIMIT_PER_SECONDS = 2.0

# IB API error codes that mean "no live market data subscription for this
# contract" (delayed data may still work) rather than a connectivity problem.
MARKET_DATA_SUBSCRIPTION_CODES = {354, 10167, 10197, 10225}
# "No security definition has been found for the request"
NO_CONTRACT_FOUND_CODE = 200


class TickerAlreadyTracked(Exception):
    pass


class MarketDataManager:
    def __init__(self, ib: IB, historical_rate_limiter: Optional[AsyncRateLimiter] = None) -> None:
        self.ib = ib
        self._bars: dict[str, "object"] = {}
        self._lock = asyncio.Lock()
        self._subscriber_queues: list[asyncio.Queue] = []
        self._bar_closed_listeners: list[Callable[[Bar], None]] = []
        self._ticker_removed_listeners: list[Callable[[str], None]] = []
        self._historical_rate_limiter = historical_rate_limiter or AsyncRateLimiter(
            max_calls=HISTORICAL_RATE_LIMIT_MAX_CALLS, per_seconds=HISTORICAL_RATE_LIMIT_PER_SECONDS
        )

        self.ib.errorEvent += self._on_error

    # -- public API ---------------------------------------------------

    def list_tickers(self) -> list[str]:
        return sorted(self._bars.keys())

    def get_last_price(self, symbol: str) -> Optional[float]:
        """Last known close for a tracked symbol, from its bar history —
        used by the options chain to pick strikes near the money without
        needing a separate stock market-data subscription."""
        bars = self._bars.get(symbol.strip().upper())
        if not bars:
            return None
        return bars[-1].close

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscriber_queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscriber_queues:
            self._subscriber_queues.remove(queue)

    def add_bar_closed_listener(self, callback: Callable[[Bar], None]) -> None:
        """Register a callback invoked once per *finalized* bar per symbol —
        never a still-forming bar. Used by the signal engine so it always
        evaluates rules against complete OHLCV, not a bar mid-formation."""
        self._bar_closed_listeners.append(callback)

    def add_ticker_removed_listener(self, callback: Callable[[str], None]) -> None:
        self._ticker_removed_listeners.append(callback)

    async def add_ticker(self, symbol: str) -> None:
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("Ticker symbol cannot be empty")

        async with self._lock:
            if symbol in self._bars:
                raise TickerAlreadyTracked(f"{symbol} is already tracked")
            if not self.ib.isConnected():
                raise RuntimeError("Not connected to IBKR TWS/Gateway")

            contract = Stock(symbol, "SMART", "USD")
            qualified = await self.ib.qualifyContractsAsync(contract)
            if not qualified:
                raise ValueError(f"IBKR could not resolve a contract for '{symbol}'")

            await self._historical_rate_limiter.acquire()
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr="1800 S",
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=2,
                keepUpToDate=True,
            )
            bars.updateEvent += self._make_bar_handler(symbol)
            self._bars[symbol] = bars

            for ib_bar in bars:
                self._broadcast(self._bar_payload(symbol, ib_bar))
            # Everything except the last bar is already finalized history from
            # the initial fetch (the last one is still the live/forming bar at
            # subscribe time) — feed it to bar-closed listeners so indicators
            # like EMA20/rolling volume don't start from nothing.
            for ib_bar in bars[:-1]:
                self._emit_bar_closed(symbol, ib_bar)

            logger.info("Subscribed to 1-min bars for %s", symbol)

        self._broadcast_tickers()

    async def remove_ticker(self, symbol: str) -> None:
        symbol = symbol.strip().upper()
        async with self._lock:
            bars = self._bars.pop(symbol, None)
            if bars is not None:
                self.ib.cancelHistoricalData(bars)
                logger.info("Unsubscribed from 1-min bars for %s", symbol)
        if bars is not None:
            for callback in list(self._ticker_removed_listeners):
                try:
                    callback(symbol)
                except Exception:
                    logger.exception("ticker-removed listener raised for %s", symbol)
        self._broadcast_tickers()

    # -- internals ------------------------------------------------------

    def _make_bar_handler(self, symbol: str):
        def handler(bars, has_new_bar: bool) -> None:
            if not bars:
                return
            # ib_async semantics: hasNewBar=False means bars[-1] (the current,
            # still-forming bar) was just updated in place — stream that to
            # the raw bar WebSocket channel so the frontend chart's current
            # candle updates live. hasNewBar=True means a *new* bar was just
            # appended, which means bars[-2] (not bars[-1], which is the
            # brand-new, barely-started next bar) just finalized — that's
            # what the signal engine must evaluate, never a partial bar.
            self._broadcast(self._bar_payload(symbol, bars[-1]))
            if has_new_bar and len(bars) >= 2:
                self._emit_bar_closed(symbol, bars[-2])

        return handler

    @staticmethod
    def _bar_payload(symbol: str, bar) -> dict:
        timestamp = bar.date.isoformat() if hasattr(bar.date, "isoformat") else str(bar.date)
        return {
            "type": "bar",
            "symbol": symbol,
            "timestamp": timestamp,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }

    def _emit_bar_closed(self, symbol: str, ib_bar) -> None:
        bar = Bar(
            symbol=symbol,
            timestamp=ib_bar.date,
            open=ib_bar.open,
            high=ib_bar.high,
            low=ib_bar.low,
            close=ib_bar.close,
            volume=ib_bar.volume,
        )
        for callback in list(self._bar_closed_listeners):
            try:
                callback(bar)
            except Exception:
                logger.exception("bar-closed listener raised for %s", symbol)

    def _broadcast_tickers(self) -> None:
        self._broadcast({"type": "tickers", "tickers": self.list_tickers()})

    def _broadcast(self, payload: dict) -> None:
        for queue in list(self._subscriber_queues):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Dropping message for slow WebSocket subscriber")

    def _on_error(self, reqId, errorCode, errorString, contract=None) -> None:  # noqa: N803
        symbol: Optional[str] = getattr(contract, "symbol", None)

        if errorCode in MARKET_DATA_SUBSCRIPTION_CODES:
            self._broadcast(
                {
                    "type": "ticker_error",
                    "symbol": symbol,
                    "code": errorCode,
                    "message": (
                        f"No live market data subscription for {symbol or 'this contract'} "
                        f"(IB error {errorCode}: {errorString}). Bars may be delayed or "
                        "missing until a market data subscription is added in IBKR "
                        "Account Management."
                    ),
                }
            )
        elif errorCode == NO_CONTRACT_FOUND_CODE:
            self._broadcast(
                {
                    "type": "ticker_error",
                    "symbol": symbol,
                    "code": errorCode,
                    "message": f"IBKR could not find a contract for {symbol or reqId}: {errorString}",
                }
            )
