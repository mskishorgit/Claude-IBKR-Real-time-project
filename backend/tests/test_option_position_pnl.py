from __future__ import annotations

from datetime import datetime, timezone

from app.options.models import OPTION_MULTIPLIER, OptionContractKey, OptionPosition, OptionQuote

KEY = OptionContractKey(symbol="AAPL", expiry="20240119", strike=190.0, right="C")


def make_position(direction, entry_price=2.00, quantity=3, status="open"):
    return OptionPosition(
        id="pos-1",
        contract=KEY,
        direction=direction,
        quantity=quantity,
        entry_price=entry_price,
        entry_time=datetime.now(timezone.utc),
        order_id=1,
        status=status,
    )


def make_quote(bid, ask):
    return OptionQuote(
        contract=KEY, bid=bid, ask=ask, last=None, delta=None, implied_vol=None,
        underlying_price=None, timestamp=datetime.now(timezone.utc),
    )


def test_long_unrealized_pnl_positive_when_price_rose():
    position = make_position("long", entry_price=2.00, quantity=2)
    position.last_quote = make_quote(bid=2.90, ask=3.10)  # mid = 3.00
    assert position.unrealized_pnl() == (3.00 - 2.00) * 2 * OPTION_MULTIPLIER  # 200.0


def test_long_unrealized_pnl_negative_when_price_fell():
    position = make_position("long", entry_price=2.00, quantity=1)
    position.last_quote = make_quote(bid=1.40, ask=1.60)  # mid = 1.50
    assert position.unrealized_pnl() == (1.50 - 2.00) * 1 * OPTION_MULTIPLIER  # -50.0


def test_short_unrealized_pnl_positive_when_price_fell():
    position = make_position("short", entry_price=2.00, quantity=1)
    position.last_quote = make_quote(bid=1.40, ask=1.60)  # mid = 1.50
    assert position.unrealized_pnl() == (2.00 - 1.50) * 1 * OPTION_MULTIPLIER  # 50.0


def test_short_unrealized_pnl_negative_when_price_rose():
    position = make_position("short", entry_price=2.00, quantity=1)
    position.last_quote = make_quote(bid=2.90, ask=3.10)  # mid = 3.00
    assert position.unrealized_pnl() == (2.00 - 3.00) * 1 * OPTION_MULTIPLIER  # -100.0


def test_unrealized_pnl_is_none_without_a_quote_yet():
    position = make_position("long")
    assert position.last_quote is None
    assert position.unrealized_pnl() is None


def test_unrealized_pnl_is_none_once_closed():
    position = make_position("long", status="closed")
    position.last_quote = make_quote(bid=2.90, ask=3.10)
    assert position.unrealized_pnl() is None
