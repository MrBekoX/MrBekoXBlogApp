"""Idle standby controller for the AI agent service."""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Optional

logger = logging.getLogger(__name__)

QueueStatsProvider = Callable[[], Awaitable[dict[str, object]]]
LifecycleCallback = Callable[[], Awaitable[None]]


class IdleShutdownService:
    """Transitions the worker into in-process standby instead of terminating the container."""

    def __init__(
        self,
        idle_timeout_seconds: Optional[int] = None,
        check_interval_seconds: int = 30,
        enabled: Optional[bool] = None,
        enter_standby: LifecycleCallback | None = None,
        exit_standby: LifecycleCallback | None = None,
        queue_stats_provider: QueueStatsProvider | None = None,
    ):
        self.enabled = enabled if enabled is not None else self._get_bool_env(
            "IDLE_SHUTDOWN_ENABLED", True
        )
        self.idle_timeout_seconds = idle_timeout_seconds or int(
            os.getenv("IDLE_TIMEOUT_SECONDS", "1800")
        )
        self.check_interval_seconds = check_interval_seconds
        self._enter_standby = enter_standby
        self._exit_standby = exit_standby
        self._queue_stats_provider = queue_stats_provider
        self._last_activity_time = time.monotonic()
        self._lock = asyncio.Lock()
        self._shutdown_requested = False
        self._standby = False
        self._wake_requested = False

        logger.info(
            "Idle standby controller initialized: enabled=%s timeout=%ss interval=%ss",
            self.enabled,
            self.idle_timeout_seconds,
            self.check_interval_seconds,
        )

    @staticmethod
    def _get_bool_env(key: str, default: bool) -> bool:
        value = os.getenv(key, str(default)).lower()
        return value in ("true", "1", "yes", "on")

    async def record_activity(self):
        async with self._lock:
            self._last_activity_time = time.monotonic()
            if self._standby:
                self._wake_requested = True

    def record_activity_sync(self):
        self._last_activity_time = time.monotonic()
        if self._standby:
            self._wake_requested = True

    async def get_idle_time(self) -> float:
        async with self._lock:
            return time.monotonic() - self._last_activity_time

    @property
    def is_standby(self) -> bool:
        return self._standby

    async def run(self):
        if not self.enabled:
            logger.info("Idle standby controller disabled")
            return

        logger.info(
            "Idle standby monitor started: worker enters standby after %ss of inactivity",
            self.idle_timeout_seconds,
        )

        while not self._shutdown_requested:
            try:
                await asyncio.sleep(self.check_interval_seconds)
                if self._standby:
                    if await self._should_wake():
                        await self._resume_from_standby()
                    continue

                idle_time = await self.get_idle_time()
                if idle_time >= self.idle_timeout_seconds:
                    await self._enter_standby_mode()
            except asyncio.CancelledError:
                logger.info("Idle standby monitor cancelled")
                break
            except Exception as exc:
                logger.error("Error in idle standby monitor: %s", exc)

        logger.info("Idle standby monitor stopped")

    async def _should_wake(self) -> bool:
        if self._wake_requested:
            return True
        if not self._queue_stats_provider:
            return False
        try:
            stats = await self._queue_stats_provider()
            depth = int(stats.get("message_count") or 0)
            return depth > 0
        except Exception as exc:
            logger.warning("Queue depth probe failed during standby: %s", exc)
            return False

    async def _enter_standby_mode(self) -> None:
        if self._standby:
            return
        logger.info("Idle timeout reached; entering in-process standby")
        if self._enter_standby:
            await self._enter_standby()
        async with self._lock:
            self._standby = True
            self._wake_requested = False

    async def _resume_from_standby(self) -> None:
        logger.info("Standby wake signal detected; resuming worker")
        if self._exit_standby:
            await self._exit_standby()
        async with self._lock:
            self._standby = False
            self._wake_requested = False
            self._last_activity_time = time.monotonic()

    async def stop(self):
        self._shutdown_requested = True


_global_instance: Optional[IdleShutdownService] = None


def get_idle_shutdown_service() -> Optional[IdleShutdownService]:
    return _global_instance


def initialize_idle_shutdown_service(
    idle_timeout_seconds: Optional[int] = None,
    enabled: Optional[bool] = None,
    enter_standby: LifecycleCallback | None = None,
    exit_standby: LifecycleCallback | None = None,
    queue_stats_provider: QueueStatsProvider | None = None,
) -> IdleShutdownService:
    global _global_instance
    _global_instance = IdleShutdownService(
        idle_timeout_seconds=idle_timeout_seconds,
        enabled=enabled,
        enter_standby=enter_standby,
        exit_standby=exit_standby,
        queue_stats_provider=queue_stats_provider,
    )
    return _global_instance


async def record_idle_activity():
    if _global_instance:
        await _global_instance.record_activity()


def record_idle_activity_sync():
    if _global_instance:
        _global_instance.record_activity_sync()
