"""Atomic in-memory quotas for the single-process free-tier service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


class QuotaLimitError(RuntimeError):
    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = max(1, retry_after_seconds)


class HourlyLimitError(QuotaLimitError):
    pass


class DailyCharacterLimitError(QuotaLimitError):
    pass


@dataclass(slots=True)
class QuotaReservation:
    client_key: str
    hour_bucket: datetime
    day_bucket: date
    characters: int
    refunded: bool = False


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    hourly_remaining: int
    daily_characters_remaining: int
    reservation: QuotaReservation


@dataclass(slots=True)
class _ClientUsage:
    hour_bucket: datetime
    hourly_requests: int
    day_bucket: date
    daily_characters: int
    last_seen: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Quota timestamps must be timezone-aware")
    return value.astimezone(UTC)


class InMemoryQuotaStore:
    def __init__(
        self,
        *,
        hourly_limit: int,
        daily_character_limit: int,
        max_clients: int = 10_000,
        stale_after: timedelta = timedelta(days=2),
    ) -> None:
        self._hourly_limit = hourly_limit
        self._daily_character_limit = daily_character_limit
        self._max_clients = max_clients
        self._stale_after = stale_after
        self._usage: dict[str, _ClientUsage] = {}
        self._lock = asyncio.Lock()

    @property
    def tracked_clients(self) -> int:
        return len(self._usage)

    async def reserve(
        self,
        client_key: str,
        characters: int,
        now: datetime,
    ) -> QuotaSnapshot:
        if characters <= 0:
            raise ValueError("characters must be positive")
        current = _utc(now)
        hour_bucket = current.replace(minute=0, second=0, microsecond=0)
        day_bucket = current.date()

        async with self._lock:
            self._cleanup(current)
            usage = self._usage.get(client_key)
            if usage is None:
                self._make_room()
                usage = _ClientUsage(hour_bucket, 0, day_bucket, 0, current)
                self._usage[client_key] = usage

            if usage.hour_bucket != hour_bucket:
                usage.hour_bucket = hour_bucket
                usage.hourly_requests = 0
            if usage.day_bucket != day_bucket:
                usage.day_bucket = day_bucket
                usage.daily_characters = 0
            usage.last_seen = current

            if usage.hourly_requests >= self._hourly_limit:
                retry_at = hour_bucket + timedelta(hours=1)
                raise HourlyLimitError(
                    "本小时生成次数已用完",
                    retry_after_seconds=int((retry_at - current).total_seconds()),
                )
            if usage.daily_characters + characters > self._daily_character_limit:
                retry_at = datetime.combine(
                    day_bucket + timedelta(days=1), datetime.min.time(), tzinfo=UTC
                )
                raise DailyCharacterLimitError(
                    "今日字符额度已用完",
                    retry_after_seconds=int((retry_at - current).total_seconds()),
                )

            usage.hourly_requests += 1
            usage.daily_characters += characters
            reservation = QuotaReservation(
                client_key=client_key,
                hour_bucket=hour_bucket,
                day_bucket=day_bucket,
                characters=characters,
            )
            return QuotaSnapshot(
                hourly_remaining=self._hourly_limit - usage.hourly_requests,
                daily_characters_remaining=(
                    self._daily_character_limit - usage.daily_characters
                ),
                reservation=reservation,
            )

    async def refund(self, reservation: QuotaReservation) -> None:
        async with self._lock:
            if reservation.refunded:
                return
            reservation.refunded = True
            usage = self._usage.get(reservation.client_key)
            if usage is None:
                return
            if usage.hour_bucket == reservation.hour_bucket:
                usage.hourly_requests = max(0, usage.hourly_requests - 1)
            if usage.day_bucket == reservation.day_bucket:
                usage.daily_characters = max(
                    0, usage.daily_characters - reservation.characters
                )

    def _cleanup(self, now: datetime) -> None:
        cutoff = now - self._stale_after
        stale = [key for key, usage in self._usage.items() if usage.last_seen < cutoff]
        for key in stale:
            self._usage.pop(key, None)

    def _make_room(self) -> None:
        if len(self._usage) < self._max_clients:
            return
        oldest = min(self._usage, key=lambda key: self._usage[key].last_seen)
        self._usage.pop(oldest, None)
