from __future__ import annotations

import asyncio

import pytest

from app.ibkr.rate_limiter import AsyncRateLimiter


@pytest.mark.anyio
async def test_calls_within_the_limit_do_not_wait():
    limiter = AsyncRateLimiter(max_calls=3, per_seconds=10)

    start = asyncio.get_event_loop().time()
    for _ in range(3):
        await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start

    assert elapsed < 0.05


@pytest.mark.anyio
async def test_call_over_the_limit_waits_for_the_window_to_clear(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr("app.ibkr.rate_limiter.time.monotonic", lambda: fake_now[0])

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        fake_now[0] += seconds

    monkeypatch.setattr("app.ibkr.rate_limiter.asyncio.sleep", fake_sleep)

    limiter = AsyncRateLimiter(max_calls=2, per_seconds=2.0)
    await limiter.acquire()
    fake_now[0] += 0.5
    await limiter.acquire()  # 2nd call within the window, still allowed
    fake_now[0] += 0.1
    await limiter.acquire()  # 3rd call must wait for the 1st to age out

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(2.0 - 0.6, abs=1e-9)


@pytest.mark.anyio
async def test_historical_data_style_limit_of_six_per_two_seconds(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr("app.ibkr.rate_limiter.time.monotonic", lambda: fake_now[0])

    async def fake_sleep(seconds):
        fake_now[0] += seconds

    monkeypatch.setattr("app.ibkr.rate_limiter.asyncio.sleep", fake_sleep)

    limiter = AsyncRateLimiter(max_calls=6, per_seconds=2.0)
    for _ in range(6):
        await limiter.acquire()
    assert fake_now[0] == 0.0  # first 6 are free

    await limiter.acquire()  # 7th must wait out the window
    assert fake_now[0] == pytest.approx(2.0)


def test_rejects_non_positive_config():
    with pytest.raises(ValueError):
        AsyncRateLimiter(max_calls=0, per_seconds=1)
    with pytest.raises(ValueError):
        AsyncRateLimiter(max_calls=5, per_seconds=0)


@pytest.mark.anyio
async def test_concurrent_callers_are_serialized_through_the_same_window():
    limiter = AsyncRateLimiter(max_calls=1, per_seconds=0.05)
    order: list[int] = []

    async def call(n):
        await limiter.acquire()
        order.append(n)

    await asyncio.gather(call(1), call(2), call(3))

    assert sorted(order) == [1, 2, 3]
