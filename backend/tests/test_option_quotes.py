"""quote_from_ticker only needs duck-typed objects with the same attributes
as ib_async's Ticker/OptionComputation — no real ib_async connection needed.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from app.options.models import OptionContractKey
from app.options.quotes import quote_from_ticker

KEY = OptionContractKey(symbol="AAPL", expiry="20240119", strike=190.0, right="C")


def make_ticker(bid=None, ask=None, last=None, delta=None, implied_vol=None, und_price=None):
    greeks = SimpleNamespace(delta=delta, impliedVol=implied_vol, undPrice=und_price)
    return SimpleNamespace(bid=bid, ask=ask, last=last, modelGreeks=greeks, contract=SimpleNamespace(conId=1))


def test_normal_quote_passes_through():
    ticker = make_ticker(bid=1.20, ask=1.30, last=1.25, delta=0.42, implied_vol=0.35, und_price=190.5)
    quote = quote_from_ticker(ticker, KEY)
    assert quote is not None
    assert quote.bid == 1.20
    assert quote.ask == 1.30
    assert quote.delta == 0.42
    assert quote.implied_vol == 0.35
    assert quote.underlying_price == 190.5


def test_ibkr_no_data_sentinel_minus_one_is_treated_as_missing():
    ticker = make_ticker(bid=-1, ask=-1, last=-1)
    quote = quote_from_ticker(ticker, KEY)
    assert quote is None  # nothing usable at all


def test_nan_price_fields_are_treated_as_missing():
    ticker = make_ticker(bid=math.nan, ask=math.nan, last=1.10)
    quote = quote_from_ticker(ticker, KEY)
    assert quote is not None
    assert quote.bid is None
    assert quote.ask is None
    assert quote.last == 1.10


def test_negative_delta_is_preserved_not_treated_as_missing():
    # Puts legitimately have negative delta — must not be scrubbed like a
    # price sentinel would be.
    ticker = make_ticker(bid=1.0, ask=1.1, delta=-0.37)
    quote = quote_from_ticker(ticker, KEY)
    assert quote is not None
    assert quote.delta == -0.37


def test_zero_delta_is_preserved():
    ticker = make_ticker(bid=1.0, ask=1.1, delta=0.0)
    quote = quote_from_ticker(ticker, KEY)
    assert quote is not None
    assert quote.delta == 0.0


def test_missing_model_greeks_object_entirely():
    ticker = SimpleNamespace(bid=1.0, ask=1.1, last=1.05, modelGreeks=None, contract=SimpleNamespace(conId=1))
    quote = quote_from_ticker(ticker, KEY)
    assert quote is not None
    assert quote.delta is None
    assert quote.implied_vol is None
    assert quote.underlying_price is None


def test_mid_prefers_bid_ask_midpoint_over_last():
    ticker = make_ticker(bid=1.0, ask=1.2, last=5.0)
    quote = quote_from_ticker(ticker, KEY)
    assert quote.mid() == 1.1


def test_mid_falls_back_to_last_when_no_bid_ask():
    ticker = make_ticker(last=1.05)
    quote = quote_from_ticker(ticker, KEY)
    assert quote.mid() == 1.05
