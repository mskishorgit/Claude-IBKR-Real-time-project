"""OptionsOrderService: the preview -> confirm -> (fill ->) position flow,
and one-click close. Uses a FakeIB that never touches a real socket, but
real ib_async Option/Order/Trade objects so trade.statusEvent/filledEvent
behave exactly like production (they're real eventkit Events).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from ib_async import Option
from ib_async.order import Order, OrderStatus, Trade

import app.options.orders as orders_module
from app.options.models import OptionContractKey, StopTargetConfig
from app.options.orders import OptionsOrderService, OrderValidationError, PreviewNotFoundError
from app.options.positions import PositionManager
from app.options.safety import LiveTradingNotArmedError, TradingSafety

KEY = OptionContractKey(symbol="AAPL", expiry="20240119", strike=190.0, right="C")


@pytest.fixture(autouse=True)
def _fast_quote_wait(monkeypatch):
    # create_preview's on-demand-subscription path does a real asyncio.sleep
    # to let a fresh quote populate; shrink it so these tests run quickly.
    monkeypatch.setattr(orders_module, "QUOTE_WAIT_SECONDS", 0.01)


def make_contract(conid: int = 111) -> Option:
    contract = Option(KEY.symbol, KEY.expiry, KEY.strike, KEY.right, "SMART", currency="USD")
    contract.conId = conid
    return contract


class FakeChainService:
    """Stands in for OptionsChainService: no chain view is open, so every
    preview has to open (and then clean up) its own on-demand subscription."""

    def __init__(self, contract: Option):
        self._contract = contract

    async def qualify_contract(self, key: OptionContractKey) -> Option:
        return self._contract

    def contract_for_key(self, key: OptionContractKey):
        return None  # never actively chain-subscribed in these tests


class FakeIB:
    """`_tickers` models what `ib.ticker()` already knows about — i.e. a
    contract some other subscription (like an open chain view) is actively
    streaming. `_quote_on_subscribe` is separate: what a *fresh* reqMktData
    call for a contract will populate, immediately rather than after a
    real wait, so tests don't need to sleep in real time. Keeping these
    two distinct is what lets a test actually exercise the "no existing
    subscription -> reqMktData then cancelMktData" path instead of always
    silently taking the "reuse existing ticker" shortcut.
    """

    def __init__(self):
        self.market_data_requests: list[Option] = []
        self.cancelled: list[Option] = []
        self.placed: list[Trade] = []
        self._next_order_id = 1000
        self._tickers: dict[int, SimpleNamespace] = {}
        self._quote_on_subscribe: dict[int, SimpleNamespace] = {}

    def set_existing_ticker(self, contract: Option, *, bid=None, ask=None, last=None):
        """Simulates a contract some other (e.g. chain-view) subscription
        already has live data for, findable via ib.ticker() with no new
        reqMktData call needed."""
        self._tickers[contract.conId] = SimpleNamespace(
            contract=contract, bid=bid, ask=ask, last=last, modelGreeks=None
        )

    def set_quote_on_subscribe(self, contract: Option, *, bid=None, ask=None, last=None):
        """Simulates what a *fresh* reqMktData call for this contract will
        populate — for tests exercising the on-demand-subscribe path."""
        self._quote_on_subscribe[contract.conId] = SimpleNamespace(
            contract=contract, bid=bid, ask=ask, last=last, modelGreeks=None
        )

    def ticker(self, contract: Option):
        return self._tickers.get(contract.conId)

    def reqMktData(self, contract, genericTickList="", snapshot=False, regulatorySnapshot=False, mktDataOptions=None):
        self.market_data_requests.append(contract)
        ticker = self._quote_on_subscribe.get(contract.conId) or SimpleNamespace(
            contract=contract, bid=None, ask=None, last=None, modelGreeks=None
        )
        self._tickers[contract.conId] = ticker
        return ticker

    def cancelMktData(self, contract):
        self.cancelled.append(contract)

    def placeOrder(self, contract, order: Order) -> Trade:
        order.orderId = self._next_order_id
        self._next_order_id += 1
        trade = Trade(contract=contract, order=order, orderStatus=OrderStatus(orderId=order.orderId, status="Submitted"))
        self.placed.append(trade)
        return trade


@pytest.fixture
def contract():
    return make_contract()


@pytest.fixture
def fake_ib(contract):
    ib = FakeIB()
    ib.set_quote_on_subscribe(contract, bid=1.20, ask=1.30)
    return ib


@pytest.fixture
def service(fake_ib, contract):
    chain = FakeChainService(contract)
    positions = PositionManager(fake_ib)
    safety = TradingSafety(trading_mode="paper")
    return OptionsOrderService(fake_ib, chain, positions, safety), positions, fake_ib, safety


@pytest.mark.anyio
async def test_create_preview_rejects_non_positive_quantity(service):
    order_service, _, _, _ = service
    with pytest.raises(OrderValidationError):
        await order_service.create_preview(KEY, "BUY", "MKT", 0, None, None, None)


@pytest.mark.anyio
async def test_create_preview_rejects_limit_order_without_price(service):
    order_service, _, _, _ = service
    with pytest.raises(OrderValidationError):
        await order_service.create_preview(KEY, "BUY", "LMT", 1, None, None, None)


@pytest.mark.anyio
async def test_create_preview_blocked_when_live_not_armed(fake_ib, contract):
    chain = FakeChainService(contract)
    positions = PositionManager(fake_ib)
    safety = TradingSafety(trading_mode="live")  # armed defaults False
    order_service = OptionsOrderService(fake_ib, chain, positions, safety)

    with pytest.raises(LiveTradingNotArmedError):
        await order_service.create_preview(KEY, "BUY", "MKT", 1, None, None, None)


@pytest.mark.anyio
async def test_create_preview_succeeds_with_fresh_quote_and_cleans_up_snapshot(service):
    order_service, _, fake_ib, _ = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 1, None, None, None)

    assert preview.quote_at_preview.bid == 1.20
    assert preview.quote_at_preview.ask == 1.30
    # Not actively chain-subscribed (FakeChainService.contract_for_key ->
    # None), so the on-demand subscription must be cancelled again.
    assert len(fake_ib.cancelled) == 1


@pytest.mark.anyio
async def test_confirm_order_is_single_use(service):
    order_service, _, _, _ = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 1, None, None, None)

    await order_service.confirm_order(preview.id)

    with pytest.raises(PreviewNotFoundError):
        await order_service.confirm_order(preview.id)


@pytest.mark.anyio
async def test_confirm_order_unknown_preview_id_raises(service):
    order_service, _, _, _ = service
    with pytest.raises(PreviewNotFoundError):
        await order_service.confirm_order("does-not-exist")


@pytest.mark.anyio
async def test_confirm_order_rechecks_safety_gate(service):
    order_service, _, _, safety = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 1, None, None, None)

    # Simulate trading mode having flipped to live-and-unarmed between
    # preview and confirm (can't happen via the real API mid-process, but
    # the check must still be defensive).
    safety.trading_mode = "live"
    safety.live_armed = False

    with pytest.raises(LiveTradingNotArmedError):
        await order_service.confirm_order(preview.id)


@pytest.mark.anyio
async def test_confirm_order_submits_market_order_with_correct_action_and_quantity(service):
    order_service, _, fake_ib, _ = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 3, None, None, None)

    await order_service.confirm_order(preview.id)

    assert len(fake_ib.placed) == 1
    submitted_order = fake_ib.placed[0].order
    assert submitted_order.action == "BUY"
    assert submitted_order.totalQuantity == 3
    assert submitted_order.orderType == "MKT"


@pytest.mark.anyio
async def test_confirm_order_submits_limit_order_with_price(service):
    order_service, _, fake_ib, _ = service
    preview = await order_service.create_preview(KEY, "BUY", "LMT", 1, 1.25, None, None)

    await order_service.confirm_order(preview.id)

    submitted_order = fake_ib.placed[0].order
    assert submitted_order.orderType == "LMT"
    assert submitted_order.lmtPrice == 1.25


@pytest.mark.anyio
async def test_fill_opens_a_position_with_avg_fill_price(service):
    order_service, positions, fake_ib, _ = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 2, None, None, None)
    trade = await order_service.confirm_order(preview.id)

    # Simulate IBKR reporting the fill.
    trade.orderStatus.status = "Filled"
    trade.orderStatus.avgFillPrice = 1.27
    trade.filledEvent.emit(trade)

    open_positions = positions.list_positions()
    assert len(open_positions) == 1
    position = open_positions[0]
    assert position.direction == "long"
    assert position.quantity == 2
    assert position.entry_price == 1.27
    assert position.status == "open"


@pytest.mark.anyio
async def test_fill_with_missing_avg_price_does_not_open_a_position(service):
    order_service, positions, _, _ = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 1, None, None, None)
    trade = await order_service.confirm_order(preview.id)

    trade.orderStatus.status = "Filled"
    trade.orderStatus.avgFillPrice = 0.0  # IBKR sometimes reports this transiently
    trade.filledEvent.emit(trade)

    assert positions.list_positions() == []


@pytest.mark.anyio
async def test_sell_action_opens_a_short_position(service):
    order_service, positions, _, _ = service
    preview = await order_service.create_preview(KEY, "SELL", "MKT", 1, None, None, None)
    trade = await order_service.confirm_order(preview.id)
    trade.orderStatus.avgFillPrice = 1.30
    trade.filledEvent.emit(trade)

    assert positions.list_positions()[0].direction == "short"


@pytest.mark.anyio
async def test_close_position_submits_opposite_action(service):
    order_service, positions, fake_ib, _ = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 1, None, None, None)
    trade = await order_service.confirm_order(preview.id)
    trade.orderStatus.avgFillPrice = 1.30
    trade.filledEvent.emit(trade)
    position_id = positions.list_positions()[0].id

    close_trade = await order_service.close_position(position_id)

    assert close_trade.order.action == "SELL"
    assert positions.get(position_id).status == "closing"


@pytest.mark.anyio
async def test_close_position_blocked_when_live_not_armed(service):
    order_service, positions, fake_ib, safety = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 1, None, None, None)
    trade = await order_service.confirm_order(preview.id)
    trade.orderStatus.avgFillPrice = 1.30
    trade.filledEvent.emit(trade)
    position_id = positions.list_positions()[0].id

    safety.trading_mode = "live"
    safety.live_armed = False
    with pytest.raises(LiveTradingNotArmedError):
        await order_service.close_position(position_id)


@pytest.mark.anyio
async def test_close_position_unknown_id_raises(service):
    order_service, _, _, _ = service
    with pytest.raises(OrderValidationError):
        await order_service.close_position("does-not-exist")


@pytest.mark.anyio
async def test_close_position_already_closed_raises(service):
    order_service, positions, _, _ = service
    preview = await order_service.create_preview(KEY, "BUY", "MKT", 1, None, None, None)
    trade = await order_service.confirm_order(preview.id)
    trade.orderStatus.avgFillPrice = 1.30
    trade.filledEvent.emit(trade)
    position_id = positions.list_positions()[0].id
    positions.mark_closed(position_id, 1.40)

    with pytest.raises(OrderValidationError):
        await order_service.close_position(position_id)


@pytest.mark.anyio
async def test_stop_loss_and_profit_target_carry_through_to_the_position(service):
    order_service, positions, _, _ = service
    preview = await order_service.create_preview(
        KEY, "BUY", "MKT", 1, None, StopTargetConfig("pct", 25), StopTargetConfig("pct", 50)
    )
    trade = await order_service.confirm_order(preview.id)
    trade.orderStatus.avgFillPrice = 2.00
    trade.filledEvent.emit(trade)

    position = positions.list_positions()[0]
    assert position.stop_price == 1.50
    assert position.target_price == 3.00
