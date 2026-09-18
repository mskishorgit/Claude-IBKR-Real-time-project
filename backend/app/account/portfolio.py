"""Live IBKR account positions + account summary.

Uses `ib.reqAccountUpdates(account)` — the single, always-on subscription
that gives both `updatePortfolioEvent` (positions, with live market price
and unrealized/realized P/L already computed by IBKR) and
`accountValueEvent` (net liquidation, buying power, day P/L, ...) for one
account, rather than combining reqPositions + reqAccountSummary
separately. Simpler to keep in sync, and it's what the prompt names
first (reqPositions/reqAccountUpdates).

Options positions additionally get their own reqMktData subscription so
greeks (delta, IV) can be shown — reuses options/quotes.py so IBKR's
"no data" sentinels are interpreted identically everywhere in this project.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional, Union

from ..options.models import OptionContractKey, OptionQuote
from ..options.quotes import quote_from_ticker
from .models import AccountOptionPosition, AccountPosition, AccountSummary

if TYPE_CHECKING:
    from ib_async import IB, PortfolioItem, Ticker
    from ib_async.objects import AccountValue

logger = logging.getLogger(__name__)

# Account-value tags we surface in the summary strip. IB reports ~200 tags
# per reqAccountUpdates; everything else is ignored.
SUMMARY_TAGS = {
    "NetLiquidation": "net_liquidation",
    "BuyingPower": "buying_power",
    "TotalCashValue": "total_cash_value",
    "RealizedPnL": "realized_pnl",
    "UnrealizedPnL": "unrealized_pnl",
}

AnyPosition = Union[AccountPosition, AccountOptionPosition]
PositionListener = Callable[[AnyPosition], None]
SummaryListener = Callable[[AccountSummary], None]


class PortfolioService:
    def __init__(self, ib: "IB") -> None:
        self.ib = ib
        self.account: Optional[str] = None
        self._summary_values: dict[str, float] = {}
        self._summary_currency: dict[str, str] = {}
        self._option_quotes: dict[int, OptionQuote] = {}
        self._greek_watch: set[int] = set()
        self._position_listeners: list[PositionListener] = []
        self._summary_listeners: list[SummaryListener] = []

        self.ib.updatePortfolioEvent += self._on_portfolio_item
        self.ib.accountValueEvent += self._on_account_value
        self.ib.pendingTickersEvent += self._on_pending_tickers

    # -- public API ---------------------------------------------------

    def add_position_listener(self, callback: PositionListener) -> None:
        self._position_listeners.append(callback)

    def add_summary_listener(self, callback: SummaryListener) -> None:
        self._summary_listeners.append(callback)

    def start(self) -> None:
        """(Re)subscribes to account updates for the session's managed
        account. Safe to call again after a reconnect — a fresh ib_async
        session has no memory of the previous subscription."""
        accounts = self.ib.managedAccounts()
        if not accounts:
            logger.warning("No managed accounts reported by IBKR yet; portfolio tracking not started")
            return
        self.account = accounts[0]
        self.ib.reqAccountUpdates(self.account)
        logger.info("Started account updates for %s", self.account)

    def list_positions(self) -> list[AnyPosition]:
        return [self._to_position(item) for item in self.ib.portfolio(self.account or "")]

    def summary(self) -> AccountSummary:
        return AccountSummary(account=self.account or "", **self._summary_values)

    # -- internals ------------------------------------------------------

    def _to_position(self, item: "PortfolioItem") -> AnyPosition:
        contract = item.contract
        base = {
            "con_id": contract.conId,
            "symbol": contract.symbol,
            "sec_type": contract.secType,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "quantity": item.position,
            "avg_cost": item.averageCost,
            "market_price": item.marketPrice,
            "market_value": item.marketValue,
            "unrealized_pnl": item.unrealizedPNL,
            "realized_pnl": item.realizedPNL,
        }
        if contract.secType == "OPT":
            quote = self._option_quotes.get(contract.conId)
            return AccountOptionPosition(
                **base,
                expiry=contract.lastTradeDateOrContractMonth,
                strike=contract.strike,
                right=contract.right,
                delta=quote.delta if quote else None,
                implied_vol=quote.implied_vol if quote else None,
                underlying_price=quote.underlying_price if quote else None,
            )
        return AccountPosition(**base)

    def _on_portfolio_item(self, item: "PortfolioItem") -> None:
        if self.account and item.account != self.account:
            return
        contract = item.contract
        if contract.secType == "OPT" and contract.conId not in self._greek_watch:
            self._greek_watch.add(contract.conId)
            # Not rate-limited (see app/ibkr/rate_limiter.py for what is):
            # this only ever fires once per *distinct* option conId, ever,
            # for the life of the process — no realistic trading pace opens
            # enough distinct option positions per second for this to be the
            # thing that trips an IBKR pacing violation.
            self.ib.reqMktData(contract, "", False, False)
        self._notify_position(self._to_position(item))

    def _on_account_value(self, value: "AccountValue") -> None:
        if self.account and value.account != self.account:
            return
        field = SUMMARY_TAGS.get(value.tag)
        if field is None:
            return
        # IB reports each tag once per currency (e.g. "USD" and "BASE" for a
        # single-currency account, or one entry per currency held in a
        # multi-currency one). Once a field has picked a currency to display
        # from, later updates in a *different* currency are ignored (so a
        # multi-currency account doesn't flap between them) — but "BASE"
        # always takes over, and repeat updates in the same currency always
        # keep flowing, which is what makes this "refreshing live".
        current_currency = self._summary_currency.get(field)
        if current_currency is not None and value.currency != current_currency and value.currency != "BASE":
            return
        try:
            self._summary_values[field] = float(value.value)
        except (TypeError, ValueError):
            return
        self._summary_currency[field] = value.currency
        self._notify_summary()

    def _on_pending_tickers(self, tickers: list["Ticker"]) -> None:
        for ticker in tickers:
            con_id = ticker.contract.conId
            if con_id not in self._greek_watch:
                continue
            key = OptionContractKey(
                symbol=ticker.contract.symbol,
                expiry=ticker.contract.lastTradeDateOrContractMonth,
                strike=ticker.contract.strike,
                right=ticker.contract.right,
            )
            quote = quote_from_ticker(ticker, key)
            if quote is None:
                continue
            self._option_quotes[con_id] = quote
            for item in self.ib.portfolio(self.account or ""):
                if item.contract.conId == con_id:
                    self._notify_position(self._to_position(item))
                    break

    def _notify_position(self, position: AnyPosition) -> None:
        for callback in list(self._position_listeners):
            try:
                callback(position)
            except Exception:
                logger.exception("portfolio position listener raised")

    def _notify_summary(self) -> None:
        summary = self.summary()
        for callback in list(self._summary_listeners):
            try:
                callback(summary)
            except Exception:
                logger.exception("portfolio summary listener raised")
