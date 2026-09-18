from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from .config import get_settings
from .ibkr.connection import ConnectionState, IBKRConnectionManager
from .ibkr.market_data import MarketDataManager, TickerAlreadyTracked
from .notifications.telegram import TelegramNotifier
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
