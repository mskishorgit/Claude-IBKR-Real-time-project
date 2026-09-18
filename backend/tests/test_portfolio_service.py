"""PortfolioService: account-update subscription lifecycle, splitting
equity vs. option positions, greeks enrichment via reqMktData, and the
account-summary currency-picking logic (a real bug was caught and fixed
here during development — a naive "prefer BASE" filter froze the summary
forever for accounts that never report a BASE-currency tag).
"""

from __future__ import annotations

from types import SimpleNamespace

from eventkit import Event
from ib_async import Option, Stock

from app.account.models import AccountOptionPosition, AccountPosition
from app.account.portfolio import PortfolioService


class FakePortfolioItem(SimpleNamespace):
    """Duck-types ib_async's PortfolioItem NamedTuple closely enough for
    PortfolioService, which only reads named attributes off it."""


def make_portfolio_item(contract, position=10, market_price=100.0, avg_cost=95.0, account="DU12345"):
    market_value = position * market_price
    return FakePortfolioItem(
        contract=contract,
        position=position,
        marketPrice=market_price,
        marketValue=market_value,
        averageCost=avg_cost,
        unrealizedPNL=(market_price - avg_cost) * position,
        realizedPNL=0.0,
        account=account,
    )


class FakeIB:
    def __init__(self):
        self.updatePortfolioEvent = Event("updatePortfolioEvent")
        self.accountValueEvent = Event("accountValueEvent")
        self.pendingTickersEvent = Event("pendingTickersEvent")
        self._managed_accounts: list[str] = []
        self._portfolio_items: list = []
        self.req_account_updates_calls: list[str] = []
        self.req_mkt_data_calls: list = []

    def managedAccounts(self):
        return self._managed_accounts

    def reqAccountUpdates(self, account):
        self.req_account_updates_calls.append(account)

    def portfolio(self, account=""):
        if account:
            return [i for i in self._portfolio_items if i.account == account]
        return list(self._portfolio_items)

    def reqMktData(self, contract, *args, **kwargs):
        self.req_mkt_data_calls.append(contract)


def make_account_value(account="DU12345", tag="NetLiquidation", value="10000.0", currency="USD"):
    return SimpleNamespace(account=account, tag=tag, value=value, currency=currency)


def test_start_without_managed_accounts_does_not_crash():
    ib = FakeIB()
    service = PortfolioService(ib)
    service.start()
    assert service.account is None
    assert ib.req_account_updates_calls == []


def test_start_subscribes_to_first_managed_account():
    ib = FakeIB()
    ib._managed_accounts = ["DU12345", "DU99999"]
    service = PortfolioService(ib)
    service.start()
    assert service.account == "DU12345"
    assert ib.req_account_updates_calls == ["DU12345"]


def test_stock_portfolio_item_notifies_equity_position():
    ib = FakeIB()
    service = PortfolioService(ib)
    seen = []
    service.add_position_listener(seen.append)

    contract = Stock("AAPL", "SMART", "USD")
    contract.conId = 111
    item = make_portfolio_item(contract, position=10, market_price=190.0, avg_cost=180.0)

    ib.updatePortfolioEvent.emit(item)

    assert len(seen) == 1
    position = seen[0]
    assert isinstance(position, AccountPosition)
    assert position.symbol == "AAPL"
    assert position.sec_type == "STK"
    assert position.market_value == 1900.0
    assert position.unrealized_pnl == 100.0
    assert ib.req_mkt_data_calls == []  # no greeks subscription for equities


def test_option_portfolio_item_subscribes_market_data_once():
    ib = FakeIB()
    service = PortfolioService(ib)
    seen = []
    service.add_position_listener(seen.append)

    contract = Option("AAPL", "20240119", 190.0, "C", "SMART", currency="USD")
    contract.conId = 222
    item = make_portfolio_item(contract, position=2, market_price=3.0, avg_cost=2.5)

    ib.updatePortfolioEvent.emit(item)
    ib.updatePortfolioEvent.emit(item)  # a second update for the same contract

    assert len(seen) == 2
    position = seen[0]
    assert isinstance(position, AccountOptionPosition)
    assert position.expiry == "20240119"
    assert position.strike == 190.0
    assert position.right == "C"
    assert position.delta is None  # no greeks yet
    assert len(ib.req_mkt_data_calls) == 1  # subscribed once, not twice


def test_pending_ticker_enriches_option_position_with_greeks():
    ib = FakeIB()
    service = PortfolioService(ib)
    seen = []
    service.add_position_listener(seen.append)

    contract = Option("AAPL", "20240119", 190.0, "C", "SMART", currency="USD")
    contract.conId = 222
    item = make_portfolio_item(contract, position=2, market_price=3.0, avg_cost=2.5)
    ib._portfolio_items.append(item)
    ib.updatePortfolioEvent.emit(item)  # registers the greek watch + reqMktData

    ticker = SimpleNamespace(
        contract=contract,
        bid=2.9,
        ask=3.1,
        last=3.0,
        modelGreeks=SimpleNamespace(delta=0.55, impliedVol=0.4, undPrice=190.5),
    )
    ib.pendingTickersEvent.emit([ticker])

    enriched = seen[-1]
    assert isinstance(enriched, AccountOptionPosition)
    assert enriched.delta == 0.55
    assert enriched.implied_vol == 0.4
    assert enriched.underlying_price == 190.5


def test_pending_ticker_for_unwatched_conid_is_ignored():
    ib = FakeIB()
    service = PortfolioService(ib)
    seen = []
    service.add_position_listener(seen.append)

    ticker = SimpleNamespace(
        contract=SimpleNamespace(conId=999),
        bid=1.0,
        ask=1.1,
        last=1.05,
        modelGreeks=None,
    )
    ib.pendingTickersEvent.emit([ticker])  # must not raise

    assert seen == []


def test_account_value_updates_summary_and_ignores_unknown_tags():
    ib = FakeIB()
    service = PortfolioService(ib)
    summaries = []
    service.add_summary_listener(summaries.append)

    ib.accountValueEvent.emit(make_account_value(tag="NetLiquidation", value="50000.0", currency="USD"))
    ib.accountValueEvent.emit(make_account_value(tag="SomeIrrelevantTag", value="1", currency="USD"))

    assert len(summaries) == 1
    assert summaries[0].net_liquidation == 50000.0


def test_account_value_for_other_account_is_ignored():
    ib = FakeIB()
    ib._managed_accounts = ["DU12345"]
    service = PortfolioService(ib)
    service.start()
    summaries = []
    service.add_summary_listener(summaries.append)

    ib.accountValueEvent.emit(make_account_value(account="DU99999", tag="NetLiquidation", value="1.0"))

    assert summaries == []


def test_base_currency_locks_in_and_wins_over_other_currencies():
    ib = FakeIB()
    service = PortfolioService(ib)

    ib.accountValueEvent.emit(make_account_value(tag="NetLiquidation", value="50000.0", currency="USD"))
    ib.accountValueEvent.emit(make_account_value(tag="NetLiquidation", value="50000.0", currency="BASE"))
    # A later, different-currency duplicate must not knock BASE back out.
    ib.accountValueEvent.emit(make_account_value(tag="NetLiquidation", value="45000.0", currency="EUR"))

    assert service.summary().net_liquidation == 50000.0


def test_repeated_updates_in_the_same_non_base_currency_keep_refreshing():
    # Regression test: an earlier version of this filter permanently froze
    # the summary after the first non-BASE update, which broke "refreshing
    # live" for any account that never reports a BASE-currency tag at all.
    ib = FakeIB()
    service = PortfolioService(ib)

    ib.accountValueEvent.emit(make_account_value(tag="NetLiquidation", value="10000.0", currency="USD"))
    ib.accountValueEvent.emit(make_account_value(tag="NetLiquidation", value="11000.0", currency="USD"))
    ib.accountValueEvent.emit(make_account_value(tag="NetLiquidation", value="12000.0", currency="USD"))

    assert service.summary().net_liquidation == 12000.0


def test_summary_to_dict_shape():
    ib = FakeIB()
    ib._managed_accounts = ["DU12345"]
    service = PortfolioService(ib)
    service.start()

    ib.accountValueEvent.emit(make_account_value(tag="NetLiquidation", value="50000.0", currency="BASE"))
    ib.accountValueEvent.emit(make_account_value(tag="BuyingPower", value="20000.0", currency="BASE"))
    ib.accountValueEvent.emit(make_account_value(tag="RealizedPnL", value="123.45", currency="BASE"))
    ib.accountValueEvent.emit(make_account_value(tag="UnrealizedPnL", value="-67.89", currency="BASE"))

    summary = service.summary().to_dict()
    assert summary == {
        "account": "DU12345",
        "net_liquidation": 50000.0,
        "buying_power": 20000.0,
        "total_cash_value": None,
        "realized_pnl": 123.45,
        "unrealized_pnl": -67.89,
    }


def test_list_positions_splits_by_sec_type():
    ib = FakeIB()
    stock = Stock("AAPL", "SMART", "USD")
    stock.conId = 1
    option = Option("AAPL", "20240119", 190.0, "C", "SMART", currency="USD")
    option.conId = 2
    ib._portfolio_items = [make_portfolio_item(stock), make_portfolio_item(option)]

    service = PortfolioService(ib)
    positions = service.list_positions()

    sec_types = {p.sec_type for p in positions}
    assert sec_types == {"STK", "OPT"}
