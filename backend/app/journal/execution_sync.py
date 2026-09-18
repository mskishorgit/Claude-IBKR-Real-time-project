"""Syncs IBKR trade executions into the journal DB, and folds in this
app's own options fills (already tracked by PositionManager) alongside
them.

Equities/ETFs: this app never places an equity order itself, so a user's
manual scalps placed directly in TWS have to come from IBKR's own
execution history — that's the source of truth here. Executions arrive
one fill at a time (`execDetailsEvent`, live) or as a backfill batch
(`reqExecutions`, on startup and periodically thereafter) and are turned
into round-trip trades with FifoTradeMatcher.

Options: rather than re-deriving a round trip from raw option
executions, each position PositionManager marks "closed" is taken as-is
— it already has the exact entry/exit price and realized P/L (with the
contract multiplier applied) this app itself used when it opened and
closed the position. See PositionManager.mark_closed and
record_option_close below.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional

from ..ibkr.rate_limiter import AsyncRateLimiter
from ..options.models import OptionPosition
from .db import JournalStore
from .fifo_matcher import FifoTradeMatcher, RawFill
from .models import JournalTrade

if TYPE_CHECKING:
    from ib_async import IB
    from ib_async.objects import Fill

logger = logging.getLogger(__name__)

# A signal only counts as "the trigger" for an entry if it fired within
# this many seconds before the entry fill — keeps a stale signal from an
# earlier, unrelated setup from getting credited for a much later trade.
SIGNAL_LINK_WINDOW_SECONDS = 5 * 60

TradeListener = Callable[[JournalTrade], None]


class ExecutionSyncService:
    def __init__(
        self,
        ib: "IB",
        store: JournalStore,
        sync_interval_seconds: float,
        rate_limiter: Optional[AsyncRateLimiter] = None,
    ) -> None:
        self.ib = ib
        self.store = store
        self.sync_interval_seconds = sync_interval_seconds
        self._matcher = FifoTradeMatcher()
        self._task: Optional[asyncio.Task] = None
        self._trade_listeners: list[TradeListener] = []
        # Guards against a user mashing the manual "Sync with IBKR" button —
        # the periodic loop alone would never come close to this limit.
        self._rate_limiter = rate_limiter or AsyncRateLimiter(max_calls=30, per_seconds=1.0)

        self.ib.execDetailsEvent += self._on_exec_details

    def add_trade_listener(self, callback: TradeListener) -> None:
        self._trade_listeners.append(callback)

    def start(self) -> None:
        """Starts the periodic reconciliation loop. Idempotent — safe to
        call again after a reconnect."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._sync_loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def sync_once(self) -> None:
        """Backfills/reconciles from IBKR's execution history. Safe to call
        repeatedly — `synced_executions` dedupes by execId, so a re-run
        only folds in fills this process hasn't already recorded (e.g. it
        wasn't running yet when they happened, or it just reconnected)."""
        await self._rate_limiter.acquire()
        fills = await self.ib.reqExecutionsAsync()
        for fill in sorted(fills, key=lambda f: f.execution.time):
            self._ingest_fill(fill)

    async def _sync_loop(self) -> None:
        while True:
            try:
                await self.sync_once()
            except Exception:
                logger.exception("Journal execution reconciliation failed")
            await asyncio.sleep(self.sync_interval_seconds)

    def _on_exec_details(self, trade, fill: "Fill") -> None:
        self._ingest_fill(fill)

    def _ingest_fill(self, fill: "Fill") -> None:
        contract = fill.contract
        if contract.secType == "OPT":
            # Options round trips come from record_option_close, not from
            # raw executions — see module docstring.
            return
        execution = fill.execution
        if self.store.is_execution_synced(execution.execId):
            return
        raw = RawFill(
            exec_id=execution.execId,
            symbol=contract.symbol,
            sec_type=contract.secType,
            side=execution.side,
            shares=execution.shares,
            price=execution.price,
            time=_as_utc(execution.time),
        )
        closed_trades = self._matcher.add_fill(raw)
        self.store.mark_execution_synced(execution.execId)
        for closed in closed_trades:
            self._persist(closed)

    def record_option_close(self, position: OptionPosition) -> None:
        """Wired as a PositionManager position listener — a no-op for any
        update that isn't a just-closed position."""
        if position.status != "closed" or position.close_time is None or position.realized_pnl is None:
            return
        close_price = position.close_price if position.close_price is not None else position.entry_price
        trade = JournalTrade(
            id=f"option:{position.id}",
            symbol=position.contract.symbol,
            sec_type="OPT",
            direction=position.direction,
            quantity=position.quantity,
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            exit_time=position.close_time,
            exit_price=close_price,
            realized_pnl=position.realized_pnl,
            source="options_panel",
            expiry=position.contract.expiry,
            strike=position.contract.strike,
            right=position.contract.right,
        )
        self._persist(trade)

    def _persist(self, trade: JournalTrade) -> None:
        signal = self.store.find_signal_before(
            trade.symbol, trade.direction, trade.entry_time, SIGNAL_LINK_WINDOW_SECONDS
        )
        if signal is not None:
            trade = replace(trade, signal_rule=signal.rule, signal_timestamp=signal.timestamp)
        self.store.insert_trade(trade)
        logger.info("Journal: recorded %s %s round trip, P/L=%.2f", trade.symbol, trade.source, trade.realized_pnl)
        for callback in list(self._trade_listeners):
            try:
                callback(trade)
            except Exception:
                logger.exception("journal trade listener raised for %s", trade.id)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
