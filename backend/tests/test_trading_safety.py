from __future__ import annotations

import pytest

from app.options.safety import LiveTradingNotArmedError, TradingSafety


def test_paper_mode_always_allows_orders_regardless_of_armed_flag():
    safety = TradingSafety(trading_mode="paper")
    safety.check_order_allowed()  # must not raise
    safety.set_armed(True)
    safety.check_order_allowed()  # still must not raise


def test_live_mode_blocks_orders_by_default():
    safety = TradingSafety(trading_mode="live")
    with pytest.raises(LiveTradingNotArmedError):
        safety.check_order_allowed()


def test_live_mode_allows_orders_once_armed():
    safety = TradingSafety(trading_mode="live")
    safety.set_armed(True)
    safety.check_order_allowed()  # must not raise


def test_live_mode_reblocks_after_disarming():
    safety = TradingSafety(trading_mode="live")
    safety.set_armed(True)
    safety.check_order_allowed()
    safety.set_armed(False)
    with pytest.raises(LiveTradingNotArmedError):
        safety.check_order_allowed()


def test_status_reflects_live_at_risk_only_when_live_and_armed():
    paper = TradingSafety(trading_mode="paper")
    assert paper.status() == {"trading_mode": "paper", "live_armed": False, "live_at_risk": False}

    live_unarmed = TradingSafety(trading_mode="live")
    assert live_unarmed.status()["live_at_risk"] is False

    live_armed = TradingSafety(trading_mode="live", live_armed=True)
    assert live_armed.status()["live_at_risk"] is True
