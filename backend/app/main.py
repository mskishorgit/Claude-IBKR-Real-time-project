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

_status_subscribers: list[asyncio.Queue] = []


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
