"""Throttles outbound IBKR API calls to stay under IBKR's pacing limits.

IBKR disconnects clients that request data too aggressively. Two documented
limits this app can realistically hit:

- **Historical data**: no more than 6 requests in any rolling 2-second
  window (IBKR's own stated pacing rule) — `reqHistoricalDataAsync`, called
  once per ticker add, is the only call site that matters here, but a user
  (or a script) adding several tickers back-to-back can burst past it.
- **Everything else** (`reqMktData`, `qualifyContractsAsync`,
  `reqSecDefOptParamsAsync`, `reqExecutionsAsync`, ...): IBKR's general
  guidance is to stay meaningfully under ~50 API messages/second on the
  socket. The riskiest burst in this app is subscribing an options chain —
  up to ~20+ `reqMktData` calls back-to-back for one `subscribe()` call,
  and again on every expiry/symbol switch.

This is a client-side courtesy limiter, not a guarantee IBKR won't ever
pace-violate for other reasons (e.g. too many concurrent market data lines
for the account's entitlement) — see the runbook for what to do if it
happens anyway.

Deliberately NOT applied to order placement or any cancellation call
(`placeOrder`, `cancelOrder`, `reqGlobalCancel`, `cancelMktData`,
`cancelHistoricalData`) — an emergency kill-switch cancel must never be
delayed by a data-request throttle.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class AsyncRateLimiter:
    """A simple async token-bucket / sliding-window limiter: at most
    `max_calls` calls may start within any rolling `per_seconds` window.
    `acquire()` blocks (never raises) until it's safe to proceed, so callers
    just `await limiter.acquire()` immediately before the IBKR call."""

    def __init__(self, max_calls: int, per_seconds: float) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if per_seconds <= 0:
            raise ValueError("per_seconds must be positive")
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        # Held for the whole check-and-maybe-sleep so concurrent callers are
        # serialized through the same window — that's what keeps the
        # *combined* call rate under the limit, not just each caller's own.
        async with self._lock:
            while True:
                now = time.monotonic()
                self._evict_stale(now)
                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return
                wait = self.per_seconds - (now - self._timestamps[0])
                if wait > 0:
                    await asyncio.sleep(wait)

    def _evict_stale(self, now: float) -> None:
        while self._timestamps and now - self._timestamps[0] >= self.per_seconds:
            self._timestamps.popleft()
