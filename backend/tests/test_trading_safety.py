from __future__ import annotations

from types import SimpleNamespace

import pytest
from eventkit import Event

from app.options.safety import (
    KillSwitchService,
    LiveTradingNotArmedError,
    TradingHaltedError,
    TradingSafety,
)


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
    assert paper.status() == {
        "trading_mode": "paper",
        "live_armed": False,
        "live_at_risk": False,
        "kill_switch_engaged": False,
        "account_id": None,
        "account_mode_mismatch": False,
    }

    live_unarmed = TradingSafety(trading_mode="live")
    assert live_unarmed.status()["live_at_risk"] is False

    live_armed = TradingSafety(trading_mode="live", live_armed=True)
    assert live_armed.status()["live_at_risk"] is True


# --- Account/mode mismatch -------------------------------------------------


def test_no_mismatch_reported_before_an_account_id_is_known():
    safety = TradingSafety(trading_mode="paper")
    assert safety.account_mode_mismatch() is False
    safety.check_order_allowed()  # must not raise


def test_paper_mode_with_paper_account_is_not_a_mismatch():
    safety = TradingSafety(trading_mode="paper")
    safety.set_account("DU12345")
    assert safety.account_mode_mismatch() is False
    safety.check_order_allowed()  # must not raise


def test_paper_mode_with_non_paper_account_blocks_orders():
    """The critical case: .env says paper, but IBKR handed us an account
    that isn't DU-prefixed — i.e. TWS/Gateway is actually pointed at a real
    account on the "paper" port. Paper mode's fast-path skip must not apply
    when this is true."""
    safety = TradingSafety(trading_mode="paper")
    safety.set_account("U7654321")
    assert safety.account_mode_mismatch() is True
    with pytest.raises(TradingHaltedError):
        safety.check_order_allowed()


def test_live_mode_with_paper_account_blocks_orders_even_when_armed():
    safety = TradingSafety(trading_mode="live")
    safety.set_account("DU12345")
    safety.set_armed(True)
    assert safety.account_mode_mismatch() is True
    with pytest.raises(TradingHaltedError):
        safety.check_order_allowed()


def test_live_mode_with_live_account_is_not_a_mismatch():
    safety = TradingSafety(trading_mode="live")
    safety.set_account("U7654321")
    safety.set_armed(True)
    assert safety.account_mode_mismatch() is False
    safety.check_order_allowed()  # must not raise


# --- Kill switch -------------------------------------------------------


def test_kill_switch_blocks_orders_in_paper_mode_too():
    safety = TradingSafety(trading_mode="paper")
    safety.trip_kill_switch()
    with pytest.raises(TradingHaltedError):
        safety.check_order_allowed()


def test_kill_switch_disarms_live_trading():
    safety = TradingSafety(trading_mode="live", live_armed=True)
    safety.trip_kill_switch()
    assert safety.live_armed is False


def test_kill_switch_reset_does_not_auto_rearm_live_trading():
    safety = TradingSafety(trading_mode="live", live_armed=True)
    safety.trip_kill_switch()
    safety.reset_kill_switch()
    assert safety.kill_switch_engaged is False
    assert safety.live_armed is False  # kill switch cleared, but live trading needs a separate re-arm
    with pytest.raises(LiveTradingNotArmedError):
        safety.check_order_allowed()


def test_kill_switch_takes_priority_over_mode_mismatch():
    safety = TradingSafety(trading_mode="paper")
    safety.set_account("U7654321")  # already a mismatch on its own
    safety.trip_kill_switch()
    with pytest.raises(TradingHaltedError, match="Kill switch"):
        safety.check_order_allowed()


class FakeOrder(SimpleNamespace):
    pass


class FakeTrade(SimpleNamespace):
    pass


class FakeIB:
    def __init__(self, connected=True, open_trades=None):
        self._connected = connected
        self._open_trades = open_trades or []
        self.cancel_calls = []
        self.global_cancel_calls = 0
        self.errorEvent = Event("errorEvent")

    def isConnected(self):
        return self._connected

    def openTrades(self):
        return list(self._open_trades)

    def cancelOrder(self, order):
        self.cancel_calls.append(order)

    def reqGlobalCancel(self):
        self.global_cancel_calls += 1


def test_kill_switch_service_cancels_open_orders_and_engages():
    order1 = FakeOrder(orderId=1)
    order2 = FakeOrder(orderId=2)
    ib = FakeIB(open_trades=[FakeTrade(order=order1), FakeTrade(order=order2)])
    safety = TradingSafety(trading_mode="paper")
    service = KillSwitchService(ib, safety)

    result = service.engage()

    assert result == {"cancelled_orders": 2, "ibkr_reachable": True}
    assert ib.cancel_calls == [order1, order2]
    assert ib.global_cancel_calls == 1
    assert safety.kill_switch_engaged is True
    with pytest.raises(TradingHaltedError):
        safety.check_order_allowed()


def test_kill_switch_service_still_engages_locally_when_ibkr_unreachable():
    ib = FakeIB(connected=False)
    safety = TradingSafety(trading_mode="paper")
    service = KillSwitchService(ib, safety)

    result = service.engage()

    assert result == {"cancelled_orders": 0, "ibkr_reachable": False}
    assert safety.kill_switch_engaged is True
    assert ib.global_cancel_calls == 0


def test_kill_switch_service_reset_clears_the_flag():
    ib = FakeIB()
    safety = TradingSafety(trading_mode="paper")
    service = KillSwitchService(ib, safety)
    service.engage()

    service.reset()

    assert safety.kill_switch_engaged is False
    safety.check_order_allowed()  # must not raise
