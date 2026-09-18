from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from .config import get_settings
from .ibkr.connection import ConnectionState, IBKRConnectionManager
from .ibkr.market_data import MarketDataManager, TickerAlreadyTracked
from .notifications.telegram import TelegramNotifier
from .options.chain import OptionsChainError, OptionsChainService
from .options.models import OptionContractKey, OptionPosition, StopTargetConfig
from .options.orders import (
    OptionsOrderService,
    OrderValidationError,
    PreviewNotFoundError,
)
from .options.positions import PositionManager
from .options.safety import LiveTradingNotArmedError, TradingSafety
from .signals.factory import build_default_engine
from .signals.models import Bar, Signal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

connection_manager = IBKRConnectionManager(
    host=settings.ibkr_host,
    port=settings.ibkr_port,
    client_id=settings.ibkr_client_id,
    reconnect_delay=settings.ibkr_reconnect_delay_seconds,
    heartbeat_interval=settings.ibkr_heartbeat_interval_seconds,
)
market_data_manager = MarketDataManager(connection_manager.ib)

signal_engine = build_default_engine(
    vwap_reclaim_enabled=settings.signals_vwap_reclaim_enabled,
    vwap_extension_pct=settings.signals_vwap_extension_pct,
    vwap_lookback_bars=settings.signals_vwap_lookback_bars,
    vwap_volume_window=settings.signals_vwap_volume_window,
    vwap_volume_multiplier=settings.signals_vwap_volume_multiplier,
    ema_cross_enabled=settings.signals_ema_cross_enabled,
    ema_fast_period=settings.signals_ema_fast_period,
    ema_slow_period=settings.signals_ema_slow_period,
    ema_volume_multiplier=settings.signals_ema_volume_multiplier,
    volume_spike_enabled=settings.signals_volume_spike_enabled,
    volume_spike_window=settings.signals_volume_spike_window,
    volume_spike_std_dev_threshold=settings.signals_volume_spike_std_dev_threshold,
    volume_spike_breakout_lookback_bars=settings.signals_volume_spike_breakout_lookback_bars,
    relative_volume_filter_enabled=settings.signals_relative_volume_filter_enabled,
    relative_volume_min_ratio=settings.signals_relative_volume_min_ratio,
    relative_volume_min_sessions=settings.signals_relative_volume_min_sessions,
)

telegram_notifier: TelegramNotifier | None = None
if settings.telegram_enabled:
    telegram_notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        enabled_rules=set(settings.telegram_enabled_rules_list) or None,
        cooldown_seconds=settings.telegram_cooldown_seconds,
    )
    logger.info("Telegram notifications enabled")
else:
    logger.info(
        "Telegram notifications disabled (set TELEGRAM_BOT_TOKEN and "
        "TELEGRAM_CHAT_ID in .env to enable)"
    )

_status_subscribers: list[asyncio.Queue] = []
_signal_subscribers: list[asyncio.Queue] = []


def _on_bar_closed(bar: Bar) -> None:
    try:
        signals = signal_engine.process_bar(bar)
    except Exception:
        logger.exception("Signal engine raised while processing a bar for %s", bar.symbol)
        return
    for signal in signals:
        logger.info("Signal fired: %s %s %s @ %s", signal.ticker, signal.rule, signal.direction, signal.price)
        _broadcast_signal(signal)
        _dispatch_telegram(signal)


def _broadcast_signal(signal: Signal) -> None:
    payload = {"type": "signal", **signal.to_dict()}
    for queue in list(_signal_subscribers):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Dropping signal for slow WebSocket subscriber")


def _dispatch_telegram(signal: Signal) -> None:
    if telegram_notifier is None:
        return
    task = asyncio.create_task(telegram_notifier.notify(signal))

    def _log_if_failed(finished: asyncio.Task) -> None:
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            logger.error("Telegram notify task raised", exc_info=exc)

    task.add_done_callback(_log_if_failed)


market_data_manager.add_bar_closed_listener(_on_bar_closed)
market_data_manager.add_ticker_removed_listener(signal_engine.reset_symbol)

# --- Options trading panel ---------------------------------------------
# trading_safety.trading_mode is fixed to whatever IBKR_TRADING_MODE the
# backend connected with; live_armed is the runtime, human-toggled gate
# that must also be true before a *live* order can go through. See
# app/options/safety.py for exactly what this does and doesn't protect.
trading_safety = TradingSafety(trading_mode=settings.ibkr_trading_mode)
options_chain_service = OptionsChainService(connection_manager.ib, market_data_manager.get_last_price)
position_manager = PositionManager(connection_manager.ib)
options_order_service = OptionsOrderService(
    connection_manager.ib, options_chain_service, position_manager, trading_safety
)

_option_chain_subscribers: list[asyncio.Queue] = []
_position_subscribers: list[asyncio.Queue] = []


def _broadcast_option_chain(payload: dict) -> None:
    for queue in list(_option_chain_subscribers):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Dropping option chain update for slow WebSocket subscriber")


def _broadcast_position(payload: dict) -> None:
    for queue in list(_position_subscribers):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Dropping position update for slow WebSocket subscriber")


def _on_position_update(position: OptionPosition) -> None:
    _broadcast_position({"type": "position_update", **position.to_dict()})


def _on_stop_target_alert(position: OptionPosition, level: str) -> None:
    logger.info("Stop/target alert: position %s hit its %s level", position.id, level)
    _broadcast_position({"type": "stop_target_alert", "level": level, **position.to_dict()})


position_manager.add_position_listener(_on_position_update)
position_manager.add_alert_listener(_on_stop_target_alert)


def _on_pending_tickers(tickers) -> None:
    for ticker in tickers:
        quote = options_chain_service.build_quote_from_ticker(ticker)
        if quote is not None:
            _broadcast_option_chain({"type": "option_quote", **quote.to_dict()})
        # A ticker can matter to both a chain view and an open position at
        # once (nothing stops handle_ticker from being a no-op when it isn't).
        position_manager.handle_ticker(ticker)


connection_manager.ib.pendingTickersEvent += _on_pending_tickers


def _broadcast_status(state: ConnectionState, error: str | None) -> None:
    payload = {"type": "status", "state": state.value, "error": error}
    for queue in list(_status_subscribers):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Dropping status update for slow WebSocket subscriber")


connection_manager.add_state_listener(_broadcast_status)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connection_manager.connect()
    if connection_manager.state == ConnectionState.CONNECTED:
        for symbol in settings.default_ticker_list:
            try:
                await market_data_manager.add_ticker(symbol)
            except Exception:
                logger.exception("Failed to subscribe default ticker %s", symbol)
    else:
        logger.warning(
            "Starting up without an IBKR connection (%s); reconnection will be "
            "retried in the background and default tickers will not be subscribed "
            "until it succeeds.",
            connection_manager.last_error,
        )
    try:
        yield
    finally:
        await connection_manager.disconnect()
        if telegram_notifier is not None:
            await telegram_notifier.aclose()


app = FastAPI(title="Scalp Dashboard Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TickerRequest(BaseModel):
    symbol: str

    @field_validator("symbol")
    @classmethod
    def symbol_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("symbol cannot be blank")
        return value.strip().upper()


@app.get("/api/status")
async def get_status():
    return {**connection_manager.status(), "tickers": market_data_manager.list_tickers()}


@app.get("/api/tickers")
async def list_tickers():
    return {"tickers": market_data_manager.list_tickers()}


@app.post("/api/tickers", status_code=201)
async def add_ticker(request: TickerRequest):
    if not connection_manager.ib.isConnected():
        raise HTTPException(status_code=503, detail="Not connected to IBKR TWS/Gateway")
    try:
        await market_data_manager.add_ticker(request.symbol)
    except TickerAlreadyTracked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tickers": market_data_manager.list_tickers()}


@app.delete("/api/tickers/{symbol}")
async def remove_ticker(symbol: str):
    await market_data_manager.remove_ticker(symbol)
    return {"tickers": market_data_manager.list_tickers()}


# --- Options trading panel ----------------------------------------------


class ArmLiveTradingRequest(BaseModel):
    armed: bool


@app.get("/api/trading-safety")
async def get_trading_safety():
    return trading_safety.status()


@app.post("/api/trading-safety/arm")
async def set_trading_safety_armed(request: ArmLiveTradingRequest):
    if request.armed and trading_safety.trading_mode != "live":
        raise HTTPException(
            status_code=400,
            detail="Nothing to arm — this backend is connected in paper mode",
        )
    trading_safety.set_armed(request.armed)
    if trading_safety.trading_mode == "live":
        logger.warning("LIVE TRADING armed=%s", request.armed)
    return trading_safety.status()


class StopTargetRequest(BaseModel):
    kind: Literal["pct", "abs"]
    value: float

    @field_validator("value")
    @classmethod
    def value_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("stop/target value must be positive")
        return value

    def to_config(self) -> StopTargetConfig:
        return StopTargetConfig(kind=self.kind, value=self.value)


class ChainSubscribeRequest(BaseModel):
    symbol: str
    expiry: str


class ChainUnsubscribeRequest(BaseModel):
    symbol: str


class OrderPreviewRequest(BaseModel):
    symbol: str
    expiry: str
    strike: float
    right: Literal["C", "P"]
    action: Literal["BUY", "SELL"]
    order_type: Literal["MKT", "LMT"]
    quantity: int
    limit_price: Optional[float] = None
    stop_loss: Optional[StopTargetRequest] = None
    profit_target: Optional[StopTargetRequest] = None

    def to_key(self) -> OptionContractKey:
        return OptionContractKey(
            symbol=self.symbol.strip().upper(), expiry=self.expiry, strike=self.strike, right=self.right
        )


def _require_ibkr_connected() -> None:
    if not connection_manager.ib.isConnected():
        raise HTTPException(status_code=503, detail="Not connected to IBKR TWS/Gateway")


@app.get("/api/options/expiries")
async def get_option_expiries(symbol: str):
    _require_ibkr_connected()
    try:
        expiries = await options_chain_service.list_near_term_expiries(
            symbol.strip().upper(), settings.options_chain_max_days_ahead
        )
    except OptionsChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"symbol": symbol.strip().upper(), "expiries": expiries}


@app.post("/api/options/chain/subscribe")
async def subscribe_option_chain(request: ChainSubscribeRequest):
    _require_ibkr_connected()
    try:
        quotes = await options_chain_service.subscribe(
            request.symbol, request.expiry, settings.options_strikes_each_side
        )
    except OptionsChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"quotes": [q.to_dict() for q in quotes]}


@app.post("/api/options/chain/unsubscribe")
async def unsubscribe_option_chain(request: ChainUnsubscribeRequest):
    await options_chain_service.unsubscribe(request.symbol)
    return {"status": "ok"}


@app.post("/api/options/orders/preview", status_code=201)
async def create_order_preview(request: OrderPreviewRequest):
    _require_ibkr_connected()
    try:
        preview = await options_order_service.create_preview(
            request.to_key(),
            request.action,
            request.order_type,
            request.quantity,
            request.limit_price,
            request.stop_loss.to_config() if request.stop_loss else None,
            request.profit_target.to_config() if request.profit_target else None,
        )
    except LiveTradingNotArmedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return preview.to_dict()


@app.post("/api/options/orders/{preview_id}/confirm")
async def confirm_order(preview_id: str):
    _require_ibkr_connected()
    try:
        trade = await options_order_service.confirm_order(preview_id)
    except PreviewNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except LiveTradingNotArmedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"order_id": trade.order.orderId, "status": trade.orderStatus.status}


@app.delete("/api/options/orders/preview/{preview_id}")
async def discard_order_preview(preview_id: str):
    options_order_service.discard_preview(preview_id)
    return {"status": "ok"}


@app.get("/api/options/positions")
async def list_option_positions():
    return {"positions": [p.to_dict() for p in position_manager.list_positions()]}


@app.post("/api/options/positions/{position_id}/close")
async def close_option_position(position_id: str):
    """One-click by design (per spec) — no confirmation step, unlike
    opening an order — but still gated by the same trading-safety check."""
    _require_ibkr_connected()
    try:
        trade = await options_order_service.close_position(position_id)
    except LiveTradingNotArmedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"order_id": trade.order.orderId, "status": trade.orderStatus.status}


@app.websocket("/ws/bars")
async def stream_bars(websocket: WebSocket):
    await websocket.accept()

    status_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    bar_queue = market_data_manager.subscribe()
    _status_subscribers.append(status_queue)

    await websocket.send_json(
        {
            "type": "status",
            "state": connection_manager.state.value,
            "error": connection_manager.last_error,
        }
    )
    await websocket.send_json({"type": "tickers", "tickers": market_data_manager.list_tickers()})

    async def pump(queue: asyncio.Queue) -> None:
        while True:
            message = await queue.get()
            await websocket.send_json(message)

    pump_tasks = [
        asyncio.create_task(pump(status_queue)),
        asyncio.create_task(pump(bar_queue)),
    ]
    try:
        while True:
            # We don't expect client messages, but reading keeps the receive
            # buffer drained and lets us detect a disconnect promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        for task in pump_tasks:
            task.cancel()
        if status_queue in _status_subscribers:
            _status_subscribers.remove(status_queue)
        market_data_manager.unsubscribe(bar_queue)


@app.websocket("/ws/signals")
async def stream_signals(websocket: WebSocket):
    """Dedicated channel for flagged entries from the signal engine — kept
    separate from /ws/bars so a client can subscribe to just one."""
    await websocket.accept()

    signal_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _signal_subscribers.append(signal_queue)

    async def pump() -> None:
        while True:
            message = await signal_queue.get()
            await websocket.send_json(message)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            # No client messages expected; reading keeps the receive buffer
            # drained and lets us detect a disconnect promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        if signal_queue in _signal_subscribers:
            _signal_subscribers.remove(signal_queue)


@app.websocket("/ws/options")
async def stream_option_chain(websocket: WebSocket):
    """Live quotes (bid/ask/delta/IV) for whatever option chain(s) are
    currently subscribed via POST /api/options/chain/subscribe. Separate
    from /ws/positions so a client can watch one without the other."""
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    _option_chain_subscribers.append(queue)

    async def pump() -> None:
        while True:
            message = await queue.get()
            await websocket.send_json(message)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        if queue in _option_chain_subscribers:
            _option_chain_subscribers.remove(queue)


@app.websocket("/ws/positions")
async def stream_positions(websocket: WebSocket):
    """Live P/L for open option positions, and stop/target alerts. Stays
    relevant regardless of what's being browsed in the options chain, so
    it's deliberately a separate channel from /ws/options."""
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    _position_subscribers.append(queue)

    await websocket.send_json(
        {
            "type": "positions_snapshot",
            "positions": [p.to_dict() for p in position_manager.list_positions()],
        }
    )

    async def pump() -> None:
        while True:
            message = await queue.get()
            await websocket.send_json(message)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        if queue in _position_subscribers:
            _position_subscribers.remove(queue)
