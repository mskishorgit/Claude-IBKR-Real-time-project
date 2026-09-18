"""Tests for TelegramNotifier's rule filter, cooldown, and message posting —
using httpx.MockTransport so nothing hits the real network.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.notifications.telegram import TelegramNotifier
from app.signals.models import Signal


def make_signal(ticker: str = "AAPL", rule: str = "ema_cross", direction: str = "long") -> Signal:
    return Signal(
        ticker=ticker,
        rule=rule,
        direction=direction,
        price=101.5,
        volume=5000,
        timestamp=datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc),
        details={"ema_fast": 101.2, "ema_slow": 100.9},
    )


class RecordingTransport(httpx.MockTransport):
    def __init__(self):
        self.requests: list[httpx.Request] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})


def make_notifier(**overrides) -> tuple[TelegramNotifier, RecordingTransport]:
    transport = RecordingTransport()
    notifier = TelegramNotifier(bot_token="TESTTOKEN", chat_id="12345", **overrides)
    notifier._client = httpx.AsyncClient(transport=transport)
    return notifier, transport


@pytest.mark.anyio
async def test_notify_posts_expected_payload():
    notifier, transport = make_notifier()

    await notifier.notify(make_signal())

    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url.path == "/botTESTTOKEN/sendMessage"
    body = json.loads(request.content)
    assert body["chat_id"] == "12345"
    assert "AAPL" in body["text"]
    assert "LONG" in body["text"]

    await notifier.aclose()


@pytest.mark.anyio
async def test_notify_respects_cooldown_per_ticker_and_rule():
    notifier, transport = make_notifier(cooldown_seconds=120)

    await notifier.notify(make_signal(ticker="AAPL", rule="ema_cross"))
    await notifier.notify(make_signal(ticker="AAPL", rule="ema_cross"))  # within cooldown -> suppressed
    await notifier.notify(make_signal(ticker="MSFT", rule="ema_cross"))  # different ticker -> not suppressed

    assert len(transport.requests) == 2
    await notifier.aclose()


@pytest.mark.anyio
async def test_notify_filters_by_enabled_rules():
    notifier, transport = make_notifier(enabled_rules={"vwap_reclaim"})

    await notifier.notify(make_signal(rule="ema_cross"))  # not in enabled_rules -> suppressed
    await notifier.notify(make_signal(rule="vwap_reclaim"))

    assert len(transport.requests) == 1
    await notifier.aclose()


@pytest.mark.anyio
async def test_notify_swallows_http_error_status_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "bad request"})

    notifier = TelegramNotifier(bot_token="TESTTOKEN", chat_id="12345")
    notifier._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await notifier.notify(make_signal())  # must not raise

    await notifier.aclose()
