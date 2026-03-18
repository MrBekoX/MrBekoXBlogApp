"""Runtime lifecycle state for readiness and consumer health checks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.monitoring.metrics import (
    set_consumer_last_message,
    set_consumer_running,
)

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


@dataclass
class RuntimeState:
    """In-memory lifecycle/consumer status shared across API endpoints."""

    started_at: datetime | None = None
    shutdown_at: datetime | None = None
    consumer_started_at: datetime | None = None
    consumer_stopped_at: datetime | None = None
    consumer_last_message_at: datetime | None = None
    consumer_last_success_at: datetime | None = None
    consumer_last_failure_at: datetime | None = None
    consumer_last_reason: str | None = None
    consumer_last_error: str | None = None
    consumer_running: bool = False
    consumer_messages_total: int = 0
    consumer_success_total: int = 0
    consumer_failure_total: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def mark_startup(self) -> None:
        with self._lock:
            self.started_at = _utc_now()
            self.shutdown_at = None
            self.consumer_running = False
            self.consumer_last_error = None
            set_consumer_running(False)

    def mark_shutdown(self) -> None:
        with self._lock:
            self.shutdown_at = _utc_now()
            self.consumer_running = False
            self.consumer_stopped_at = self.shutdown_at
            set_consumer_running(False)

    def mark_consumer_started(self) -> None:
        with self._lock:
            self.consumer_running = True
            self.consumer_started_at = _utc_now()
            self.consumer_stopped_at = None
            self.consumer_last_error = None
            set_consumer_running(True)

    def mark_consumer_stopped(self, error: str | None = None) -> None:
        with self._lock:
            self.consumer_running = False
            self.consumer_stopped_at = _utc_now()
            if error:
                self.consumer_last_error = error
            set_consumer_running(False)

    def mark_consumer_message_started(self) -> None:
        with self._lock:
            self.consumer_messages_total += 1
            self.consumer_last_message_at = _utc_now()
            set_consumer_last_message(self.consumer_last_message_at.timestamp())

    def mark_consumer_message_finished(self, success: bool, reason: str) -> None:
        with self._lock:
            self.consumer_last_reason = reason
            if success:
                self.consumer_success_total += 1
                self.consumer_last_success_at = _utc_now()
                self.consumer_last_error = None
            else:
                self.consumer_failure_total += 1
                self.consumer_last_failure_at = _utc_now()

    def mark_consumer_error(self, error: Exception | str) -> None:
        with self._lock:
            self.consumer_last_error = str(error)
            self.consumer_last_failure_at = _utc_now()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            last_message_ts = (
                self.consumer_last_message_at.timestamp()
                if self.consumer_last_message_at
                else None
            )
            idle_seconds = (
                round(now - last_message_ts, 3)
                if last_message_ts is not None
                else None
            )
            return {
                "started_at": _iso(self.started_at),
                "shutdown_at": _iso(self.shutdown_at),
                "consumer_running": self.consumer_running,
                "consumer_started_at": _iso(self.consumer_started_at),
                "consumer_stopped_at": _iso(self.consumer_stopped_at),
                "consumer_last_message_at": _iso(self.consumer_last_message_at),
                "consumer_last_success_at": _iso(self.consumer_last_success_at),
                "consumer_last_failure_at": _iso(self.consumer_last_failure_at),
                "consumer_last_reason": self.consumer_last_reason,
                "consumer_last_error": self.consumer_last_error,
                "consumer_messages_total": self.consumer_messages_total,
                "consumer_success_total": self.consumer_success_total,
                "consumer_failure_total": self.consumer_failure_total,
                "consumer_idle_seconds": idle_seconds,
            }


runtime_state = RuntimeState()
