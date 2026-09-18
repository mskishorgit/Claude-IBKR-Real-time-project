"""Optional Telegram bot notifications for fired signals.

Disabled unless both a bot token and chat id are configured (see
config.py/.env.example) — there is no default token and nothing is
hardcoded. This exists so you can get pinged on your phone even when the
dashboard's browser tab is closed, which browser Notifications can't do.

Has its own rule filter and per-(ticker, rule) cooldown, independent of the
frontend's notification settings (those live in browser localStorage, which
a backend process obviously can't read).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from ..signals.models import Signal

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


@dataclass
class TelegramNotifier:
    bot_token: str
    chat_id: str
    enabled_rules: set[str] | None = None  # None = all rules
    cooldown_seconds: float = 120.0
    _last_sent: dict[str, float] = field(default_factory=dict, repr=False)
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    def _passes_filters(self, signal: Signal) -> bool:
        if self.enabled_rules is not None and signal.rule not in self.enabled_rules:
            return False
        key = f"{signal.ticker}:{signal.rule}"
        now = time.monotonic()
        last = self._last_sent.get(key, 0.0)
        if now - last < self.cooldown_seconds:
            return False
        self._last_sent[key] = now
        return True

    @staticmethod
    def _format_message(signal: Signal) -> str:
        return (
            f"{signal.direction.upper()} — {signal.ticker}\n"
            f"Rule: {signal.rule}\n"
            f"Price: {signal.price}   Volume: {signal.volume}\n"
            f"Time: {signal.timestamp.isoformat()}"
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10)
        return self._client

    async def notify(self, signal: Signal) -> None:
        """Send a Telegram message for this signal, unless it's filtered out
        by rule or is still within its cooldown window. Never raises —
        delivery failures are logged, not propagated, since a notification
        failure must never affect signal detection/broadcast."""
        if not self._passes_filters(signal):
            return

        url = f"{TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        try:
            response = await self._get_client().post(
                url, json={"chat_id": self.chat_id, "text": self._format_message(signal)}
            )
            if response.status_code >= 400:
                logger.error(
                    "Telegram notify failed (HTTP %s) for %s %s: %s",
                    response.status_code,
                    signal.ticker,
                    signal.rule,
                    response.text,
                )
        except httpx.HTTPError:
            logger.exception(
                "Telegram notify request failed for %s %s", signal.ticker, signal.rule
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
