"""Live P/L tracking for open option positions, plus stop/target alerting.

Alert-only, by design: crossing a stop/target level here only notifies
(see stop_target.py's module docstring) — it never places an order on its
own. Auto-closing on a level hit (a bracket order) is an explicit,
unimplemented stretch goal per the spec.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Literal, Optional

from .models import OPTION_MULTIPLIER, Direction, OptionContractKey, OptionPosition, StopTargetConfig
from .quotes import quote_from_ticker
from .stop_target import check_level_hit, compute_stop_target_prices

if TYPE_CHECKING:
    from ib_async import IB, Option, Ticker

logger = logging.getLogger(__name__)

PositionListener = Callable[[OptionPosition], None]
AlertListener = Callable[[OptionPosition, Literal["stop", "target"]], None]


class PositionManager:
    def __init__(self, ib: "IB") -> None:
        self.ib = ib
        self._positions: dict[str, OptionPosition] = {}
        self._contracts: dict[str, "Option"] = {}
        self._position_id_by_conid: dict[int, str] = {}
        self._position_listeners: list[PositionListener] = []
        self._alert_listeners: list[AlertListener] = []

    def add_position_listener(self, callback: PositionListener) -> None:
        self._position_listeners.append(callback)

    def add_alert_listener(self, callback: AlertListener) -> None:
        self._alert_listeners.append(callback)

    def list_positions(self) -> list[OptionPosition]:
        return list(self._positions.values())

    def get(self, position_id: str) -> Optional[OptionPosition]:
        return self._positions.get(position_id)

    def contract_for(self, position_id: str) -> Optional["Option"]:
        return self._contracts.get(position_id)

    def open_position(
        self,
        contract: "Option",
        key: OptionContractKey,
        direction: Direction,
        quantity: int,
        entry_price: float,
        order_id: int,
        stop_loss: Optional[StopTargetConfig],
        profit_target: Optional[StopTargetConfig],
    ) -> OptionPosition:
        stop_price, target_price = compute_stop_target_prices(
            entry_price, direction, stop_loss, profit_target
        )
        position = OptionPosition(
            id=str(uuid.uuid4()),
            contract=key,
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc),
            order_id=order_id,
            stop_loss=stop_loss,
            profit_target=profit_target,
            stop_price=stop_price,
            target_price=target_price,
        )
        self._positions[position.id] = position
        self._contracts[position.id] = contract
        self._position_id_by_conid[contract.conId] = position.id
        self.ib.reqMktData(contract, "", False, False)

        logger.info(
            "Opened position %s: %s %s x%d @ %.2f (stop=%s target=%s)",
            position.id,
            direction,
            key.label(),
            quantity,
            entry_price,
            stop_price,
            target_price,
        )
        self._notify_position(position)
        return position

    def mark_closing(self, position_id: str, close_order_id: int) -> None:
        position = self._positions.get(position_id)
        if position is None:
            return
        position.status = "closing"
        position.close_order_id = close_order_id
        self._notify_position(position)

    def mark_closed(self, position_id: str, close_price: float) -> None:
        position = self._positions.get(position_id)
        if position is None:
            return
        sign = 1 if position.direction == "long" else -1
        position.status = "closed"
        position.close_price = close_price
        position.close_time = datetime.now(timezone.utc)
        position.realized_pnl = (
            sign * (close_price - position.entry_price) * position.quantity * OPTION_MULTIPLIER
        )
        contract = self._contracts.pop(position_id, None)
        if contract is not None:
            self.ib.cancelMktData(contract)
            self._position_id_by_conid.pop(contract.conId, None)

        logger.info(
            "Closed position %s @ %.2f, realized P/L=%.2f",
            position_id,
            close_price,
            position.realized_pnl,
        )
        self._notify_position(position)

    def handle_ticker(self, ticker: "Ticker") -> None:
        position_id = self._position_id_by_conid.get(ticker.contract.conId)
        if position_id is None:
            return
        position = self._positions.get(position_id)
        if position is None:
            return

        quote = quote_from_ticker(ticker, position.contract)
        if quote is None:
            return
        position.last_quote = quote
        self._notify_position(position)
        self._check_stop_target(position)

    def _check_stop_target(self, position: OptionPosition) -> None:
        if position.status != "open" or position.last_quote is None:
            return
        current = position.last_quote.mid()
        if current is None:
            return

        hit = check_level_hit(position.direction, current, position.stop_price, position.target_price)
        if hit == "stop" and not position.stop_alert_fired:
            position.stop_alert_fired = True
            logger.info("Stop level hit for position %s at %.2f", position.id, current)
            self._notify_alert(position, "stop")
        elif hit == "target" and not position.target_alert_fired:
            position.target_alert_fired = True
            logger.info("Target level hit for position %s at %.2f", position.id, current)
            self._notify_alert(position, "target")

    def _notify_position(self, position: OptionPosition) -> None:
        for callback in list(self._position_listeners):
            try:
                callback(position)
            except Exception:
                logger.exception("position listener raised for %s", position.id)

    def _notify_alert(self, position: OptionPosition, level: Literal["stop", "target"]) -> None:
        for callback in list(self._alert_listeners):
            try:
                callback(position, level)
            except Exception:
                logger.exception("stop/target alert listener raised for %s", position.id)
