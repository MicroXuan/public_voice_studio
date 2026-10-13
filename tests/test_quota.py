from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.quota import (
    DailyCharacterLimitError,
    HourlyLimitError,
    InMemoryQuotaStore,
)


NOW = datetime(2026, 10, 13, 10, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_exactly_ten_hourly_requests_are_accepted():
    store = InMemoryQuotaStore(hourly_limit=10, daily_character_limit=30_000)

    snapshots = [await store.reserve("client", 10, NOW) for _ in range(10)]

    assert snapshots[-1].hourly_remaining == 0
    with pytest.raises(HourlyLimitError) as caught:
        await store.reserve("client", 10, NOW)
    assert 1 <= caught.value.retry_after_seconds <= 3_600


@pytest.mark.asyncio
async def test_daily_character_limit_and_utc_day_reset():
    store = InMemoryQuotaStore(hourly_limit=100, daily_character_limit=30_000)
    snapshot = await store.reserve("client", 30_000, NOW)
    assert snapshot.daily_characters_remaining == 0

    with pytest.raises(DailyCharacterLimitError) as caught:
        await store.reserve("client", 1, NOW)
    assert caught.value.retry_after_seconds > 0

    next_day = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
    reset = await store.reserve("client", 123, next_day)
    assert reset.daily_characters_remaining == 29_877


@pytest.mark.asyncio
async def test_hour_bucket_resets_at_next_utc_hour():
    store = InMemoryQuotaStore(hourly_limit=1, daily_character_limit=30_000)
    await store.reserve("client", 10, NOW)

    reset = await store.reserve("client", 10, NOW.replace(hour=11, minute=0))

    assert reset.hourly_remaining == 0


@pytest.mark.asyncio
async def test_refund_restores_request_and_character_capacity_once():
    store = InMemoryQuotaStore(hourly_limit=1, daily_character_limit=100)
    snapshot = await store.reserve("client", 80, NOW)

    await store.refund(snapshot.reservation)
    await store.refund(snapshot.reservation)

    replacement = await store.reserve("client", 100, NOW)
    assert replacement.hourly_remaining == 0
    assert replacement.daily_characters_remaining == 0


@pytest.mark.asyncio
async def test_concurrent_reservations_are_atomic():
    store = InMemoryQuotaStore(hourly_limit=10, daily_character_limit=30_000)

    results = await asyncio.gather(
        *(store.reserve("client", 1, NOW) for _ in range(20)),
        return_exceptions=True,
    )

    accepted = [result for result in results if not isinstance(result, Exception)]
    rejected = [result for result in results if isinstance(result, HourlyLimitError)]
    assert len(accepted) == 10
    assert len(rejected) == 10


@pytest.mark.asyncio
async def test_stale_client_records_are_cleaned_and_memory_is_bounded():
    store = InMemoryQuotaStore(
        hourly_limit=10,
        daily_character_limit=30_000,
        max_clients=2,
        stale_after=timedelta(days=1),
    )
    await store.reserve("old-a", 1, NOW)
    await store.reserve("old-b", 1, NOW)
    await store.reserve("new", 1, NOW + timedelta(days=2))

    assert store.tracked_clients == 1
