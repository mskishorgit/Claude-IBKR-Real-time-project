"""Connection lifecycle management for TWS / IB Gateway.

Wraps an ib_async.IB instance and takes care of:
 - initial connect with a clear, actionable error if TWS/Gateway isn't reachable
 - a heartbeat that detects a silently-dead socket
 - automatic reconnection with backoff-free periodic retries
 - broadcasting connection state changes to interested listeners (e.g. the
   FastAPI WebSocket layer) so the frontend can show connected / disconnected /
   reconnecting rather than failing silently
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Callable, Optional

from ib_async import IB

logger = logging.getLogger(__name__)

StateListener = Callable[["ConnectionState", Optional[str]], None]

# IB API error codes that indicate the socket itself dropped or never came up,
# as opposed to a per-request error (see market_data.py for data-subscription codes).
CONNECTIVITY_LOST_CODES = {1100, 1102, 2110}
CONNECTIVITY_RESTORED_CODES = {1101, 1102}
NOT_CONNECTED_CODES = {502, 504, 1100}
CLIENT_ID_IN_USE_CODE = 326


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class IBKRConnectionManager:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        reconnect_delay: int = 5,
        heartbeat_interval: int = 10,
    ) -> None:
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id
        self.reconnect_delay = reconnect_delay
        self.heartbeat_interval = heartbeat_interval

        self.state = ConnectionState.DISCONNECTED
        self.last_error: Optional[str] = None

        self._heartbeat_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._stopping = False
        self._listeners: list[StateListener] = []

        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error

    # -- public API ---------------------------------------------------

    def add_state_listener(self, callback: StateListener) -> None:
        self._listeners.append(callback)

    def status(self) -> dict:
        return {
            "state": self.state.value,
            "error": self.last_error,
            "host": self.host,
            "port": self.port,
        }

    async def connect(self) -> None:
        self._stopping = False
        await self._attempt_connect()

    async def disconnect(self) -> None:
        self._stopping = True
        for task in (self._heartbeat_task, self._reconnect_task):
            if task is not None:
                task.cancel()
        if self.ib.isConnected():
            self.ib.disconnect()
        self._set_state(ConnectionState.DISCONNECTED)

    # -- internals ------------------------------------------------------

    def _set_state(self, state: ConnectionState, error: Optional[str] = None) -> None:
        self.state = state
        if error is not None:
            self.last_error = error
        elif state == ConnectionState.CONNECTED:
            self.last_error = None
        for listener in list(self._listeners):
            try:
                listener(self.state, self.last_error)
            except Exception:
                logger.exception("state listener raised")

    async def _attempt_connect(self) -> None:
        self._set_state(ConnectionState.CONNECTING)
        try:
            await self.ib.connectAsync(
                self.host, self.port, clientId=self.client_id, timeout=10
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            message = self._friendly_connect_error(exc)
            logger.error("IBKR connection failed: %s", message)
            self._set_state(ConnectionState.DISCONNECTED, error=message)
            self._schedule_reconnect()
            return

        logger.info("Connected to IBKR at %s:%s", self.host, self.port)
        self._set_state(ConnectionState.CONNECTED)
        self._start_heartbeat()

    def _friendly_connect_error(self, exc: Exception) -> str:
        text = str(exc) or exc.__class__.__name__
        if isinstance(exc, ConnectionRefusedError) or "Connection refused" in text:
            return (
                f"Could not reach TWS/IB Gateway at {self.host}:{self.port}. "
                "Is it running, and is the API enabled under "
                "Configure > API > Settings > Enable ActiveX and Socket Clients?"
            )
        if isinstance(exc, asyncio.TimeoutError) or "timeout" in text.lower():
            return (
                f"Timed out connecting to TWS/IB Gateway at {self.host}:{self.port}. "
                "Check the host/port and that the API port matches your trading mode "
                "(paper=7497, live=7496 by default)."
            )
        return f"Failed to connect to TWS/IB Gateway: {text}"

    def _on_disconnected(self) -> None:
        if self._stopping:
            return
        logger.warning("Lost connection to TWS/IB Gateway")
        self._set_state(
            ConnectionState.DISCONNECTED, error="Lost connection to TWS/IB Gateway"
        )
        self._schedule_reconnect()

    def _on_error(self, reqId, errorCode, errorString, contract=None) -> None:  # noqa: N803
        if errorCode == CLIENT_ID_IN_USE_CODE:
            self._set_state(
                ConnectionState.DISCONNECTED,
                error=(
                    f"clientId {self.client_id} is already in use by another API "
                    "client connected to this TWS/Gateway instance. Set a different "
                    "IBKR_CLIENT_ID in .env."
                ),
            )
            return
        if errorCode in CONNECTIVITY_LOST_CODES:
            self._set_state(
                ConnectionState.RECONNECTING,
                error=f"IBKR connectivity issue (code {errorCode}): {errorString}",
            )
            self._schedule_reconnect()
        elif errorCode in NOT_CONNECTED_CODES and not self.ib.isConnected():
            self._set_state(
                ConnectionState.DISCONNECTED,
                error=f"Not connected to TWS/IB Gateway (code {errorCode}): {errorString}",
            )
            self._schedule_reconnect()
        # Other error codes (per-request, market-data related, etc.) are handled
        # by MarketDataManager, which also subscribes to ib.errorEvent.

    def _schedule_reconnect(self) -> None:
        if self._stopping:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        if self.state != ConnectionState.CONNECTED:
            self._set_state(ConnectionState.RECONNECTING, error=self.last_error)
        while not self._stopping and not self.ib.isConnected():
            await asyncio.sleep(self.reconnect_delay)
            if self._stopping:
                return
            await self._attempt_connect()

    def _start_heartbeat(self) -> None:
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while not self._stopping and self.ib.isConnected():
            try:
                await asyncio.wait_for(self.ib.reqCurrentTimeAsync(), timeout=5)
            except Exception:
                logger.warning("Heartbeat to TWS/IB Gateway failed; connection looks stale")
                break
            await asyncio.sleep(self.heartbeat_interval)
        if not self._stopping and not self.ib.isConnected():
            self._on_disconnected()
