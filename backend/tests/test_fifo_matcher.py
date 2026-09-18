from datetime import datetime, timedelta, timezone

from app.journal.fifo_matcher import FifoTradeMatcher, RawFill

T0 = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def fill(exec_id, side, shares, price, minutes_after_t0=0, symbol="AAPL", sec_type="STK"):
    return RawFill(
        exec_id=exec_id,
        symbol=symbol,
        sec_type=sec_type,
        side=side,
        shares=shares,
        price=price,
        time=T0 + timedelta(minutes=minutes_after_t0),
    )


def test_simple_long_round_trip():
    matcher = FifoTradeMatcher()

    opened = matcher.add_fill(fill("e1", "BOT", 100, 10.0, 0))
    assert opened == []

    closed = matcher.add_fill(fill("e2", "SLD", 100, 12.0, 5))
    assert len(closed) == 1
    trade = closed[0]
    assert trade.direction == "long"
    assert trade.quantity == 100
    assert trade.entry_price == 10.0
    assert trade.exit_price == 12.0
    assert trade.realized_pnl == 200.0
    assert trade.source == "execution"


def test_simple_short_round_trip():
    matcher = FifoTradeMatcher()

    matcher.add_fill(fill("e1", "SLD", 50, 20.0, 0))
    closed = matcher.add_fill(fill("e2", "BOT", 50, 18.0, 3))

    assert len(closed) == 1
    trade = closed[0]
    assert trade.direction == "short"
    assert trade.realized_pnl == 100.0  # profited from the price drop


def test_partial_close_leaves_remainder_open():
    matcher = FifoTradeMatcher()

    matcher.add_fill(fill("e1", "BOT", 100, 10.0, 0))
    closed = matcher.add_fill(fill("e2", "SLD", 40, 11.0, 1))

    assert len(closed) == 1
    assert closed[0].quantity == 40
    assert closed[0].realized_pnl == 40.0

    # the remaining 60 shares are still open; closing them should realize
    # against the original $10 entry, not a fresh lot
    closed_again = matcher.add_fill(fill("e3", "SLD", 60, 13.0, 2))
    assert len(closed_again) == 1
    assert closed_again[0].quantity == 60
    assert closed_again[0].entry_price == 10.0
    assert closed_again[0].realized_pnl == 180.0


def test_fifo_ordering_across_two_lots():
    matcher = FifoTradeMatcher()

    matcher.add_fill(fill("e1", "BOT", 50, 10.0, 0))
    matcher.add_fill(fill("e2", "BOT", 50, 12.0, 1))

    closed = matcher.add_fill(fill("e3", "SLD", 60, 15.0, 2))

    assert len(closed) == 2
    first, second = closed
    assert first.entry_price == 10.0
    assert first.quantity == 50
    assert first.realized_pnl == 250.0  # (15-10)*50
    assert second.entry_price == 12.0
    assert second.quantity == 10
    assert second.realized_pnl == 30.0  # (15-12)*10


def test_reversal_closes_existing_lot_and_opens_opposite_direction():
    matcher = FifoTradeMatcher()

    matcher.add_fill(fill("e1", "BOT", 100, 10.0, 0))
    closed = matcher.add_fill(fill("e2", "SLD", 150, 11.0, 1))

    assert len(closed) == 1
    assert closed[0].direction == "long"
    assert closed[0].quantity == 100
    assert closed[0].realized_pnl == 100.0

    # the extra 50 shares sold should have opened a new short lot at 11.0
    closed_short = matcher.add_fill(fill("e3", "BOT", 50, 9.0, 2))
    assert len(closed_short) == 1
    assert closed_short[0].direction == "short"
    assert closed_short[0].entry_price == 11.0
    assert closed_short[0].realized_pnl == 100.0  # (9 is 2 below 11) * 50


def test_different_symbols_tracked_independently():
    matcher = FifoTradeMatcher()

    matcher.add_fill(fill("e1", "BOT", 100, 10.0, 0, symbol="AAPL"))
    closed_msft = matcher.add_fill(fill("e2", "SLD", 100, 8.0, 1, symbol="MSFT"))

    # MSFT has no open lot, so this sell just opens a new short lot in MSFT
    assert closed_msft == []
