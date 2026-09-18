"""Order preview/confirm flow for opening a position, and one-click close
for exiting one.

Deliberately conservative:
- Opening an order is always two calls: create_preview (fresh quote,
  validated inputs, safety check) then confirm_order (re-checks safety,
  re-qualifies the contract, then and only then calls ib.placeOrder). A
  preview is single-use — confirm_order pops it immediately, so a retry
  after a failure always means a brand new preview against a brand new
  quote, never a blind resubmission of stale state.
- close_position is one click per the spec (an explicit exception to the
  "always confirm" rule, for exiting fast) but still runs through the same
  TradingSafety.check_order_allowed() gate as an opening order.
- Nothing here retries automatically. If ib.placeOrder or a fill callback
  fails, it's logged and surfaced — never silently re-attempted.
- Every attempt and every IBKR status/fill event is logged.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from ib_async import IB, LimitOrder, MarketOrder, Trade

from .chain import OptionsChainService
from .models import Action, OptionContractKey, OrderType, PendingOrder, StopTargetConfig
from .positions import PositionManager
from .quotes import quote_from_ticker
from .safety import TradingSafety

logger = logging.getLogger(__name__)

PREVIEW_TTL_SECONDS = 90
# How long to wait for a fresh, on-demand quote to populate before giving up
# on a preview — chain-view subscriptions are usually already streaming, in
# which case this wait never happens at all (see create_preview).
QUOTE_WAIT_SECONDS = 1.0


class OrderValidationError(Exception):
    pass


class PreviewNotFoundError(Exception):
    pass


class OptionsOrderService:
    def __init__(
        self,
        ib: IB,
        chain_service: OptionsChainService,
        position_manager: PositionManager,
        safety: TradingSafety,
    ) -> None:
        self.ib = ib
        self.chain_service = chain_service
        self.position_manager = position_manager
        self.safety = safety
        self._pending_previews: dict[str, PendingOrder] = {}

    def get_preview(self, preview_id: str) -> Optional[PendingOrder]:
        return self._pending_previews.get(preview_id)

    def discard_preview(self, preview_id: str) -> None:
        self._pending_previews.pop(preview_id, None)

    async def create_preview(
        self,
        key: OptionContractKey,
        action: Action,
        order_type: OrderType,
        quantity: int,
        limit_price: Optional[float],
        stop_loss: Optional[StopTargetConfig],
        profit_target: Optional[StopTargetConfig],
    ) -> PendingOrder:
        if quantity <= 0 or int(quantity) != quantity:
            raise OrderValidationError("Quantity must be a positive whole number of contracts")
        if order_type == "LMT" and (limit_price is None or limit_price <= 0):
            raise OrderValidationError("A positive limit price is required for a limit order")

        # Checked here (before touching IBKR at all) *and* again in
        # confirm_order, since arming state can change in between.
        self.safety.check_order_allowed()

        contract = await self.chain_service.qualify_contract(key)
        quote = await self._get_quote_for_preview(contract, key)
        if quote is None:
            raise OrderValidationError(
                f"No live quote available yet for {key.label()} — try again in a moment"
            )

        preview = PendingOrder(
            id=str(uuid.uuid4()),
            contract=key,
            action=action,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            quote_at_preview=quote,
            trading_mode=self.safety.trading_mode,
            stop_loss=stop_loss,
            profit_target=profit_target,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=PREVIEW_TTL_SECONDS),
        )
        self._pending_previews[preview.id] = preview
        logger.info(
            "Order preview %s created: %s %s x%d %s%s (quote bid=%s ask=%s, trading_mode=%s)",
            preview.id,
            action,
            key.label(),
            quantity,
            order_type,
            f" @ {limit_price}" if limit_price else "",
            quote.bid,
            quote.ask,
            preview.trading_mode,
        )
        return preview

    async def _get_quote_for_preview(self, contract, key: OptionContractKey):
        # Reuse an already-streaming ticker (from an open chain view) rather
        # than opening a second, redundant market-data line for the same
        # contract.
        existing = self.ib.ticker(contract)
        if existing is not None:
            quote = quote_from_ticker(existing, key)
            if quote is not None:
                return quote

        ticker = self.ib.reqMktData(contract, "", False, False)
        try:
            await asyncio.sleep(QUOTE_WAIT_SECONDS)
            return quote_from_ticker(ticker, key)
        finally:
            # Only cancel if the chain view isn't also using this contract —
            # otherwise this would kill the chain's live feed out from under it.
            if self.chain_service.contract_for_key(key) is None:
                self.ib.cancelMktData(contract)

    async def confirm_order(self, preview_id: str) -> Trade:
        preview = self._pending_previews.pop(preview_id, None)
        if preview is None:
            raise PreviewNotFoundError(
                "This order preview was not found, already used, or has expired"
            )
        if datetime.now(timezone.utc) > preview.expires_at:
            raise PreviewNotFoundError(
                "This order preview has expired — please re-quote and try again"
            )

        self.safety.check_order_allowed()

        contract = await self.chain_service.qualify_contract(preview.contract)
        order = (
            MarketOrder(preview.action, preview.quantity)
            if preview.order_type == "MKT"
            else LimitOrder(preview.action, preview.quantity, preview.limit_price)
        )

        logger.info(
            "Submitting order (preview %s): %s %s x%d %s%s [trading_mode=%s]",
            preview.id,
            preview.action,
            preview.contract.label(),
            preview.quantity,
            preview.order_type,
            f" @ {preview.limit_price}" if preview.limit_price else "",
            preview.trading_mode,
        )
        try:
            trade = self.ib.placeOrder(contract, order)
        except Exception:
            logger.exception("placeOrder call raised for preview %s — order NOT submitted", preview.id)
            raise
        logger.info(
            "IBKR accepted order id=%s initial status=%s",
            trade.order.orderId,
            trade.orderStatus.status,
        )

        direction: Literal["long", "short"] = "long" if preview.action == "BUY" else "short"

        def on_status(t: Trade) -> None:
            logger.info(
                "Order %s status: %s filled=%s remaining=%s avgFillPrice=%s",
                t.order.orderId,
                t.orderStatus.status,
                t.orderStatus.filled,
                t.orderStatus.remaining,
                t.orderStatus.avgFillPrice,
            )

        def on_filled(t: Trade) -> None:
            avg_price = t.orderStatus.avgFillPrice
            if not avg_price:
                logger.error(
                    "Order %s reported Filled but avgFillPrice is missing/zero — "
                    "not opening a position from this fill",
                    t.order.orderId,
                )
                return
            self.position_manager.open_position(
                contract=contract,
                key=preview.contract,
                direction=direction,
                quantity=preview.quantity,
                entry_price=avg_price,
                order_id=t.order.orderId,
                stop_loss=preview.stop_loss,
                profit_target=preview.profit_target,
            )

        trade.statusEvent += on_status
        trade.filledEvent += on_filled
        return trade

    async def close_position(self, position_id: str) -> Trade:
        position = self.position_manager.get(position_id)
        if position is None:
            raise OrderValidationError("Position not found")
        if position.status != "open":
            raise OrderValidationError(f"Position is already {position.status}")

        self.safety.check_order_allowed()

        contract = self.position_manager.contract_for(position_id)
        if contract is None:
            raise OrderValidationError("No live contract tracked for this position")

        close_action: Action = "SELL" if position.direction == "long" else "BUY"
        order = MarketOrder(close_action, position.quantity)

        logger.info(
            "Submitting CLOSE order for position %s: %s %s x%d MKT [trading_mode=%s]",
            position_id,
            close_action,
            position.contract.label(),
            position.quantity,
            self.safety.trading_mode,
        )
        try:
            trade = self.ib.placeOrder(contract, order)
        except Exception:
            logger.exception(
                "placeOrder call raised for close of position %s — order NOT submitted", position_id
            )
            raise
        logger.info(
            "IBKR accepted close order id=%s initial status=%s",
            trade.order.orderId,
            trade.orderStatus.status,
        )
        self.position_manager.mark_closing(position_id, trade.order.orderId)

        def on_status(t: Trade) -> None:
            logger.info(
                "Close order %s status: %s filled=%s remaining=%s avgFillPrice=%s",
                t.order.orderId,
                t.orderStatus.status,
                t.orderStatus.filled,
                t.orderStatus.remaining,
                t.orderStatus.avgFillPrice,
            )

        def on_filled(t: Trade) -> None:
            avg_price = t.orderStatus.avgFillPrice
            if not avg_price:
                logger.error(
                    "Close order %s reported Filled but avgFillPrice is missing/zero",
                    t.order.orderId,
                )
                return
            self.position_manager.mark_closed(position_id, avg_price)

        trade.statusEvent += on_status
        trade.filledEvent += on_filled
        return trade
