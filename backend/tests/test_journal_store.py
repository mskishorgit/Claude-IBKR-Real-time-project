from datetime import datetime, timezone

import pytest

from app.journal.db import JournalStore
from app.journal.models import JournalTrade, SignalLogEntry


@pytest.fixture()
def store(tmp_path):
    db_path = tmp_path / "journal.db"
    journal = JournalStore(str(db_path))
    yield journal
    journal.close()


def make_trade(
    id="t1",
    symbol="AAPL",
    sec_type="STK",
    direction="long",
    quantity=100.0,
    entry_time=datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc),
    entry_price=180.0,
    exit_time=datetime(2024, 3, 5, 14, 35, tzinfo=timezone.utc),
    exit_price=181.0,
    realized_pnl=100.0,
    source="execution",
    **kwargs,
):
    return JournalTrade(
        id=id,
        symbol=symbol,
        sec_type=sec_type,
        direction=direction,
        quantity=quantity,
        entry_time=entry_time,
        entry_price=entry_price,
        exit_time=exit_time,
        exit_price=exit_price,
        realized_pnl=realized_pnl,
        source=source,
        **kwargs,
    )


def test_insert_and_fetch_trade_for_day(store):
    store.insert_trade(make_trade())

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert len(trades) == 1
    assert trades[0].symbol == "AAPL"
    assert trades[0].realized_pnl == 100.0


def test_trades_for_day_excludes_other_days(store):
    store.insert_trade(make_trade(id="t1", exit_time=datetime(2024, 3, 5, 20, 0, tzinfo=timezone.utc)))
    store.insert_trade(make_trade(id="t2", exit_time=datetime(2024, 3, 6, 10, 0, tzinfo=timezone.utc)))

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert [t.id for t in trades] == ["t1"]


def test_insert_trade_is_idempotent_by_id(store):
    store.insert_trade(make_trade(id="t1", realized_pnl=100.0))
    store.insert_trade(make_trade(id="t1", realized_pnl=999.0))  # re-sync, same id

    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert len(trades) == 1
    assert trades[0].realized_pnl == 999.0


def test_day_pnl_for_month_aggregates_by_day(store):
    store.insert_trade(make_trade(id="t1", exit_time=datetime(2024, 3, 5, 14, 0, tzinfo=timezone.utc), realized_pnl=50.0))
    store.insert_trade(make_trade(id="t2", exit_time=datetime(2024, 3, 5, 15, 0, tzinfo=timezone.utc), realized_pnl=-20.0))
    store.insert_trade(make_trade(id="t3", exit_time=datetime(2024, 3, 6, 10, 0, tzinfo=timezone.utc), realized_pnl=10.0))
    # different month — must not leak into the March query
    store.insert_trade(make_trade(id="t4", exit_time=datetime(2024, 4, 1, 10, 0, tzinfo=timezone.utc), realized_pnl=999.0))

    days = store.day_pnl_for_month(2024, 3)
    by_date = {d.day.isoformat(): d for d in days}

    assert by_date["2024-03-05"].realized_pnl == 30.0
    assert by_date["2024-03-05"].trade_count == 2
    assert by_date["2024-03-06"].realized_pnl == 10.0
    assert "2024-04-01" not in by_date


def test_month_stats_win_loss_breakdown(store):
    store.insert_trade(make_trade(id="win1", exit_time=datetime(2024, 3, 4, tzinfo=timezone.utc), realized_pnl=100.0))
    store.insert_trade(make_trade(id="win2", exit_time=datetime(2024, 3, 5, tzinfo=timezone.utc), realized_pnl=50.0))
    store.insert_trade(make_trade(id="loss1", exit_time=datetime(2024, 3, 6, tzinfo=timezone.utc), realized_pnl=-30.0))
    store.insert_trade(make_trade(id="loss2", exit_time=datetime(2024, 3, 7, tzinfo=timezone.utc), realized_pnl=-70.0))

    stats = store.month_stats(2024, 3)

    assert stats.trade_count == 4
    assert stats.win_count == 2
    assert stats.loss_count == 2
    assert stats.win_rate == 0.5
    assert stats.avg_win == 75.0
    assert stats.avg_loss == -50.0
    assert stats.largest_win == 100.0
    assert stats.largest_loss == -70.0
    assert stats.total_pnl == 50.0


def test_month_stats_handles_no_trades(store):
    stats = store.month_stats(2024, 3)
    assert stats.trade_count == 0
    assert stats.win_rate is None
    assert stats.avg_win is None
    assert stats.avg_loss is None
    assert stats.largest_win is None
    assert stats.largest_loss is None
    assert stats.total_pnl == 0


def test_month_stats_weekly_breakdown(store):
    # March 4-10, 2024 is one ISO week (Mon Mar 4 - Sun Mar 10)
    store.insert_trade(make_trade(id="t1", exit_time=datetime(2024, 3, 4, tzinfo=timezone.utc), realized_pnl=100.0))
    store.insert_trade(make_trade(id="t2", exit_time=datetime(2024, 3, 10, tzinfo=timezone.utc), realized_pnl=-40.0))
    # the following ISO week
    store.insert_trade(make_trade(id="t3", exit_time=datetime(2024, 3, 11, tzinfo=timezone.utc), realized_pnl=25.0))

    stats = store.month_stats(2024, 3)
    weekly = dict(stats.weekly_pnl)

    assert weekly["2024-03-04"] == 60.0
    assert weekly["2024-03-11"] == 25.0


def test_find_signal_before_matches_ticker_direction_and_window(store):
    store.record_signal(
        SignalLogEntry(
            id="s1",
            ticker="AAPL",
            rule="vwap_reclaim",
            direction="long",
            price=179.5,
            timestamp=datetime(2024, 3, 5, 14, 28, tzinfo=timezone.utc),
        )
    )

    found = store.find_signal_before(
        "AAPL", "long", datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc), window_seconds=300
    )
    assert found is not None
    assert found.rule == "vwap_reclaim"


def test_find_signal_before_respects_window(store):
    store.record_signal(
        SignalLogEntry(
            id="s1",
            ticker="AAPL",
            rule="vwap_reclaim",
            direction="long",
            price=179.5,
            timestamp=datetime(2024, 3, 5, 14, 0, tzinfo=timezone.utc),
        )
    )

    # entry is 30 minutes after the signal — outside a 5-minute window
    found = store.find_signal_before(
        "AAPL", "long", datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc), window_seconds=300
    )
    assert found is None


def test_find_signal_before_ignores_wrong_direction(store):
    store.record_signal(
        SignalLogEntry(
            id="s1",
            ticker="AAPL",
            rule="ema_cross",
            direction="short",
            price=179.5,
            timestamp=datetime(2024, 3, 5, 14, 28, tzinfo=timezone.utc),
        )
    )

    found = store.find_signal_before(
        "AAPL", "long", datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc), window_seconds=300
    )
    assert found is None


def test_execution_sync_dedup(store):
    assert store.is_execution_synced("exec-1") is False
    store.mark_execution_synced("exec-1")
    assert store.is_execution_synced("exec-1") is True


def test_trade_signal_linkage_round_trips_through_storage(store):
    store.insert_trade(
        make_trade(
            signal_rule="vwap_reclaim",
            signal_timestamp=datetime(2024, 3, 5, 14, 28, tzinfo=timezone.utc),
        )
    )
    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert trades[0].signal_rule == "vwap_reclaim"
    assert trades[0].signal_timestamp == datetime(2024, 3, 5, 14, 28, tzinfo=timezone.utc)


def test_option_trade_fields_round_trip(store):
    store.insert_trade(
        make_trade(
            id="opt1",
            sec_type="OPT",
            source="options_panel",
            expiry="20240315",
            strike=185.0,
            right="C",
        )
    )
    trades = store.trades_for_day(datetime(2024, 3, 5).date())
    assert trades[0].sec_type == "OPT"
    assert trades[0].expiry == "20240315"
    assert trades[0].strike == 185.0
    assert trades[0].right == "C"
