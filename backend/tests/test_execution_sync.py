"""ExecutionSyncService: folding IBKR equity/ETF fills (via reqExecutions
backfill and live execDetailsEvent) into journal round trips, folding in
options closes from PositionManager directly, linking a trade's entry to
the signal (if any) that triggered it, and execId-based dedup so repeated
reconciliation runs don't double-record a trade.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from eventkit import Event

from app.journal.db import JournalStore
from app.journal.execution_sync import ExecutionSyncService
from app.journal.models import SignalLogEntry
from app.options.models import OptionContractKey, OptionPosition


class FakeIB:
    def __init__(self):
        self.execDetailsEvent = Event("execDetailsEvent")
        self._executions: list = []

    async def reqExecutionsAsync(self):
        return list(self._executions)


def make_fill(exec_id, symbol="AAPL", sec_type="STK", side="BOT", shares=100, price=180.0, minute=30):
    contract = SimpleNamespace(symbol=symbol, secType=sec_type)
    execution = SimpleNamespace(
        execId=exec_id,
        side=side,
        shares=shares,
        price=price,
        time=datetime(2024, 3, 5, 14, minute, tzinfo=timezone.utc),
    )
    return SimpleNamespace(contract=contract, execution=execution)


def make_option_position(
    position_id="pos1",
    symbol="AAPL",
    direction="long",
    quantity=1,
    entry_price=2.5,
    close_price=3.5,
    realized_pnl=100.0,
):
    return OptionPosition(
        id=position_id,
        contract=OptionContractKey(symbol=symbol, expiry="20240315", strike=185.0, right="C"),
        direction=direction,
        quantity=quantity,
        entry_price=entry_price,
        entry_time=datetime(2024, 3, 5, 14, 0, tzinfo=timezone.utc),
        order_id=1,
        status="closed",
        close_price=close_price,
        close_time=datetime(2024, 3, 5, 14, 10, tzinfo=timezone.utc),
        realized_pnl=realized_pnl,
    )


@pytest.fixture()
def store(tmp_path):
    db_path = tmp_path / "journal.db"
    journal = JournalStore(str(db_path))
    yield journal
    journal.close()


@pytest.fixture()
def ib():
    return FakeIB()


@pytest.fixture()
def service(ib, store):
    return ExecutionSyncService(ib, store, sync_interval_seconds=999)


@pytest.mark.anyio
async def test_sync_once_matches_equity_round_trip(ib, store, service):
    ib._executions = [
        make_fill("e1", side="BOT", shares=100, price=180.0, minute=30),
        make_fill("e2", side="SLD", shares=100, price=181.0, minute=35),
    ]

    await service.sync_once()

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert len(trades) == 1
    assert trades[0].symbol == "AAPL"
    assert trades[0].realized_pnl == 100.0
    assert trades[0].source == "execution"


@pytest.mark.anyio
async def test_sync_once_is_idempotent_across_repeated_calls(ib, store, service):
    ib._executions = [
        make_fill("e1", side="BOT", shares=100, price=180.0, minute=30),
        make_fill("e2", side="SLD", shares=100, price=181.0, minute=35),
    ]

    await service.sync_once()
    await service.sync_once()  # simulates the periodic reconciliation re-running

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert len(trades) == 1


@pytest.mark.anyio
async def test_option_executions_are_ignored_by_sync(ib, store, service):
    ib._executions = [make_fill("e1", symbol="AAPL", sec_type="OPT", side="BOT", shares=1, price=2.5)]

    await service.sync_once()

    assert store.trades_for_day(datetime(2024, 3, 5).date()) == []


def test_live_exec_details_event_ingests_fill(ib, store, service):
    ib.execDetailsEvent.emit(None, make_fill("e1", side="BOT", shares=100, price=180.0, minute=30))
    ib.execDetailsEvent.emit(None, make_fill("e2", side="SLD", shares=100, price=182.0, minute=32))

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert len(trades) == 1
    assert trades[0].realized_pnl == 200.0


def test_record_option_close_persists_trade_as_is(store, service):
    service.record_option_close(make_option_position())

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert len(trades) == 1
    trade = trades[0]
    assert trade.sec_type == "OPT"
    assert trade.source == "options_panel"
    assert trade.entry_price == 2.5
    assert trade.exit_price == 3.5
    assert trade.realized_pnl == 100.0
    assert trade.expiry == "20240315"
    assert trade.strike == 185.0
    assert trade.right == "C"


def test_record_option_close_ignores_non_closed_positions(store, service):
    open_position = make_option_position()
    open_position.status = "open"
    open_position.close_time = None
    open_position.realized_pnl = None

    service.record_option_close(open_position)

    assert store.trades_for_day(datetime(2024, 3, 5).date()) == []


def test_entry_gets_linked_to_a_recent_matching_signal(store, service):
    store.record_signal(
        SignalLogEntry(
            id="s1",
            ticker="AAPL",
            rule="vwap_reclaim",
            direction="long",
            price=2.4,
            timestamp=datetime(2024, 3, 5, 13, 58, tzinfo=timezone.utc),  # 2 min before entry
        )
    )

    service.record_option_close(make_option_position())

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert trades[0].signal_rule == "vwap_reclaim"


def test_entry_not_linked_when_no_signal_in_window(store, service):
    store.record_signal(
        SignalLogEntry(
            id="s1",
            ticker="AAPL",
            rule="vwap_reclaim",
            direction="long",
            price=2.4,
            timestamp=datetime(2024, 3, 5, 12, 0, tzinfo=timezone.utc),  # 2 hours before entry
        )
    )

    service.record_option_close(make_option_position())

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert trades[0].signal_rule is None


def test_trade_listener_notified_on_persist(store, service):
    received = []
    service.add_trade_listener(received.append)

    service.record_option_close(make_option_position())

    assert len(received) == 1
    assert received[0].symbol == "AAPL"


def test_trade_listener_exception_does_not_prevent_other_listeners(store, service):
    calls = []

    def raising_listener(trade):
        raise RuntimeError("boom")

    service.add_trade_listener(raising_listener)
    service.add_trade_listener(calls.append)

    service.record_option_close(make_option_position())

    assert len(calls) == 1
