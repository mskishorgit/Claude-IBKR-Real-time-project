"""PositionManager: opening/closing bookkeeping, live P/L updates from
ticker callbacks, and stop/target alert latching (fires once, not every
tick after the level is crossed)."""

from __future__ import annotations

from types import SimpleNamespace

from ib_async import Option

from app.options.models import OptionContractKey, StopTargetConfig
from app.options.positions import PositionManager

KEY = OptionContractKey(symbol="AAPL", expiry="20240119", strike=190.0, right="C")


class FakeIB:
    def __init__(self):
        self.market_data_requests = []
        self.cancelled = []

    def reqMktData(self, contract, *args, **kwargs):
        self.market_data_requests.append(contract)

    def cancelMktData(self, contract):
        self.cancelled.append(contract)


def make_contract(conid=222) -> Option:
    contract = Option(KEY.symbol, KEY.expiry, KEY.strike, KEY.right, "SMART", currency="USD")
    contract.conId = conid
    return contract


def make_ticker(contract, bid=None, ask=None, last=None):
    return SimpleNamespace(contract=contract, bid=bid, ask=ask, last=last, modelGreeks=None)


def test_open_position_subscribes_market_data_and_notifies_listeners():
    ib = FakeIB()
    manager = PositionManager(ib)
    contract = make_contract()
    seen = []
    manager.add_position_listener(seen.append)

    position = manager.open_position(
        contract, KEY, "long", quantity=2, entry_price=2.00, order_id=1,
        stop_loss=None, profit_target=None,
    )

    assert position.status == "open"
    assert ib.market_data_requests == [contract]
    assert seen == [position]


def test_handle_ticker_updates_last_quote_and_pnl():
    ib = FakeIB()
    manager = PositionManager(ib)
    contract = make_contract()
    position = manager.open_position(
        contract, KEY, "long", quantity=1, entry_price=2.00, order_id=1,
        stop_loss=None, profit_target=None,
    )

    manager.handle_ticker(make_ticker(contract, bid=2.40, ask=2.60))

    assert position.last_quote is not None
    assert position.unrealized_pnl() == (2.50 - 2.00) * 1 * 100


def test_handle_ticker_for_unrelated_conid_is_ignored():
    ib = FakeIB()
    manager = PositionManager(ib)
    contract = make_contract(conid=222)
    manager.open_position(
        contract, KEY, "long", quantity=1, entry_price=2.00, order_id=1,
        stop_loss=None, profit_target=None,
    )
    unrelated = make_contract(conid=999)

    manager.handle_ticker(make_ticker(unrelated, bid=1.0, ask=1.1))  # must not raise

    position = manager.list_positions()[0]
    assert position.last_quote is None


def test_stop_alert_fires_once_when_crossed_and_not_again():
    ib = FakeIB()
    manager = PositionManager(ib)
    contract = make_contract()
    alerts = []
    manager.add_alert_listener(lambda position, level: alerts.append((position.id, level)))

    position = manager.open_position(
        contract, KEY, "long", quantity=1, entry_price=2.00, order_id=1,
        stop_loss=StopTargetConfig("pct", 25), profit_target=None,
    )
    assert position.stop_price == 1.50

    manager.handle_ticker(make_ticker(contract, bid=1.40, ask=1.50))  # mid 1.45 <= 1.50 -> stop hit
    manager.handle_ticker(make_ticker(contract, bid=1.30, ask=1.40))  # still below -> must not re-fire

    assert alerts == [(position.id, "stop")]
    assert position.stop_alert_fired is True


def test_target_alert_fires_once():
    ib = FakeIB()
    manager = PositionManager(ib)
    contract = make_contract()
    alerts = []
    manager.add_alert_listener(lambda position, level: alerts.append(level))

    position = manager.open_position(
        contract, KEY, "long", quantity=1, entry_price=2.00, order_id=1,
        stop_loss=None, profit_target=StopTargetConfig("pct", 50),
    )
    assert position.target_price == 3.00

    manager.handle_ticker(make_ticker(contract, bid=3.10, ask=3.20))
    manager.handle_ticker(make_ticker(contract, bid=3.30, ask=3.40))

    assert alerts == ["target"]


def test_no_alert_when_price_stays_between_stop_and_target():
    ib = FakeIB()
    manager = PositionManager(ib)
    contract = make_contract()
    alerts = []
    manager.add_alert_listener(lambda position, level: alerts.append(level))

    manager.open_position(
        contract, KEY, "long", quantity=1, entry_price=2.00, order_id=1,
        stop_loss=StopTargetConfig("pct", 25), profit_target=StopTargetConfig("pct", 50),
    )

    manager.handle_ticker(make_ticker(contract, bid=2.05, ask=2.15))

    assert alerts == []


def test_mark_closed_computes_realized_pnl_and_cancels_market_data():
    ib = FakeIB()
    manager = PositionManager(ib)
    contract = make_contract()
    position = manager.open_position(
        contract, KEY, "long", quantity=2, entry_price=2.00, order_id=1,
        stop_loss=None, profit_target=None,
    )

    manager.mark_closed(position.id, close_price=2.50)

    assert position.status == "closed"
    assert position.realized_pnl == (2.50 - 2.00) * 2 * 100
    assert ib.cancelled == [contract]
    # Closed positions stop receiving ticker-driven updates.
    manager.handle_ticker(make_ticker(contract, bid=10.0, ask=10.5))
    assert position.unrealized_pnl() is None


def test_short_position_stop_and_target_alerting():
    ib = FakeIB()
    manager = PositionManager(ib)
    contract = make_contract()
    alerts = []
    manager.add_alert_listener(lambda position, level: alerts.append(level))

    position = manager.open_position(
        contract, KEY, "short", quantity=1, entry_price=2.00, order_id=1,
        stop_loss=StopTargetConfig("pct", 25), profit_target=StopTargetConfig("pct", 50),
    )
    assert position.stop_price == 2.50
    assert position.target_price == 1.00

    manager.handle_ticker(make_ticker(contract, bid=2.55, ask=2.65))  # mid 2.60 >= 2.50 -> stop

    assert alerts == ["stop"]
