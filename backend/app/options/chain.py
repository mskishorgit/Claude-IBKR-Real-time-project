"""Live 0DTE/weekly options chain subscriptions, strikes near the money.

The underlying's current price is read from MarketDataManager's already-
tracked bar history (via the `get_underlying_price` callback) rather than
opening a second market-data subscription just for a stock quote — a
symbol must already be tracked on the dashboard (so it has bar history)
before its option chain can be browsed. Keeps this module decoupled from
MarketDataManager (constructor takes a plain callback, not that class).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from ib_async import IB, Option, Stock, Ticker

from .models import OptionContractKey, OptionQuote
from .quotes import quote_from_ticker

logger = logging.getLogger(__name__)

DEFAULT_STRIKES_EACH_SIDE = 5
DEFAULT_MAX_DAYS_AHEAD = 7
MAX_EXPIRIES_RETURNED = 6


class OptionsChainError(Exception):
    pass


class _ChainSubscription:
    def __init__(self, symbol: str, expiry: str) -> None:
        self.symbol = symbol
        self.expiry = expiry
        self.contracts: dict[OptionContractKey, Option] = {}


def _nearest_strikes(strikes: list[float], price: float, each_side: int) -> list[float]:
    ordered = sorted(strikes)
    if not ordered:
        return []
    closest_index = min(range(len(ordered)), key=lambda i: abs(ordered[i] - price))
    lo = max(0, closest_index - each_side)
    hi = min(len(ordered), closest_index + each_side + 1)
    return ordered[lo:hi]


class OptionsChainService:
    def __init__(self, ib: IB, get_underlying_price: Callable[[str], Optional[float]]) -> None:
        self.ib = ib
        self._get_underlying_price = get_underlying_price
        self._subscriptions: dict[str, _ChainSubscription] = {}
        self._key_by_conid: dict[int, OptionContractKey] = {}

    async def _get_smart_chain(self, symbol: str):
        if not self.ib.isConnected():
            raise OptionsChainError("Not connected to IBKR TWS/Gateway")
        stock = Stock(symbol, "SMART", "USD")
        qualified = await self.ib.qualifyContractsAsync(stock)
        if not qualified or qualified[0] is None:
            raise OptionsChainError(f"Could not resolve underlying contract for {symbol}")
        underlying = qualified[0]

        chains = await self.ib.reqSecDefOptParamsAsync(
            underlying.symbol, "", underlying.secType, underlying.conId
        )
        smart_chains = [c for c in chains if c.exchange == "SMART"] or list(chains)
        if not smart_chains:
            raise OptionsChainError(f"No option chain found for {symbol}")
        return smart_chains[0]

    async def list_near_term_expiries(
        self, symbol: str, max_days_ahead: int = DEFAULT_MAX_DAYS_AHEAD
    ) -> list[str]:
        chain = await self._get_smart_chain(symbol)
        today = datetime.now().date()
        cutoff = today + timedelta(days=max_days_ahead)
        near_term = sorted(
            e for e in chain.expirations if today <= _parse_expiry(e) <= cutoff
        )
        return near_term[:MAX_EXPIRIES_RETURNED]

    async def subscribe(
        self, symbol: str, expiry: str, strikes_each_side: int = DEFAULT_STRIKES_EACH_SIDE
    ) -> list[OptionQuote]:
        symbol = symbol.strip().upper()
        underlying_price = self._get_underlying_price(symbol)
        if underlying_price is None:
            raise OptionsChainError(
                f"No known price for {symbol} yet — track it on the dashboard first"
            )

        chain = await self._get_smart_chain(symbol)
        if expiry not in chain.expirations:
            raise OptionsChainError(f"{expiry} is not a valid expiry for {symbol}")

        strikes = _nearest_strikes(list(chain.strikes), underlying_price, strikes_each_side)
        if not strikes:
            raise OptionsChainError(f"No strikes found for {symbol} {expiry}")

        candidates = [
            Option(symbol, expiry, strike, right, "SMART", currency="USD")
            for strike in strikes
            for right in ("C", "P")
        ]
        qualified = await self.ib.qualifyContractsAsync(*candidates)
        qualified_contracts = [c for c in qualified if c is not None]
        if not qualified_contracts:
            raise OptionsChainError(f"IBKR could not qualify any contracts for {symbol} {expiry}")

        # Replace any existing chain subscription for this symbol only after
        # the new one is confirmed resolvable, so a bad request doesn't tear
        # down a working subscription for nothing.
        await self.unsubscribe(symbol)

        subscription = _ChainSubscription(symbol, expiry)
        quotes: list[OptionQuote] = []
        for contract in qualified_contracts:
            key = OptionContractKey(
                symbol=symbol, expiry=expiry, strike=contract.strike, right=contract.right
            )
            subscription.contracts[key] = contract
            self._key_by_conid[contract.conId] = key
            ticker = self.ib.reqMktData(contract, "", False, False)
            quote = quote_from_ticker(ticker, key)
            if quote is not None:
                quotes.append(quote)

        self._subscriptions[symbol] = subscription
        logger.info(
            "Subscribed to %d option contracts for %s %s", len(subscription.contracts), symbol, expiry
        )
        return quotes

    async def unsubscribe(self, symbol: str) -> None:
        subscription = self._subscriptions.pop(symbol.strip().upper(), None)
        if subscription is None:
            return
        for key, contract in subscription.contracts.items():
            self.ib.cancelMktData(contract)
            self._key_by_conid.pop(contract.conId, None)
        logger.info(
            "Unsubscribed option chain for %s %s (%d contracts)",
            subscription.symbol,
            subscription.expiry,
            len(subscription.contracts),
        )

    def contract_for_key(self, key: OptionContractKey) -> Optional[Option]:
        subscription = self._subscriptions.get(key.symbol)
        if subscription is None:
            return None
        return subscription.contracts.get(key)

    async def qualify_contract(self, key: OptionContractKey) -> Option:
        existing = self.contract_for_key(key)
        if existing is not None:
            return existing
        if not self.ib.isConnected():
            raise OptionsChainError("Not connected to IBKR TWS/Gateway")
        option = Option(key.symbol, key.expiry, key.strike, key.right, "SMART", currency="USD")
        qualified = await self.ib.qualifyContractsAsync(option)
        if not qualified or qualified[0] is None:
            raise OptionsChainError(f"Could not qualify option contract {key.label()}")
        return qualified[0]

    def build_quote_from_ticker(self, ticker: Ticker) -> Optional[OptionQuote]:
        key = self._key_by_conid.get(ticker.contract.conId)
        if key is None:
            return None
        return quote_from_ticker(ticker, key)


def _parse_expiry(expiry: str) -> date:
    return datetime.strptime(expiry, "%Y%m%d").date()
