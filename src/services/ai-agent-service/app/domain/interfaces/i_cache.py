"""Cache interface for distributed cache, locks, and operation inbox state."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CacheLockLease:
    """Opaque distributed lock lease returned by acquire_lock."""

    resource_id: str
    token: str


class ICache(ABC):
    """Abstract interface for cache operations."""

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def get(self, key: str) -> str | None:
        pass

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        pass

    @abstractmethod
    async def get_json(self, key: str) -> Any | None:
        pass

    @abstractmethod
    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        pass

    @abstractmethod
    async def is_processed(self, message_id: str) -> bool:
        pass

    @abstractmethod
    async def mark_processed(self, message_id: str, ttl_seconds: int = 86400) -> None:
        pass

    @abstractmethod
    async def acquire_lock(self, resource_id: str, ttl_seconds: int = 300) -> CacheLockLease | None:
        """Try to acquire a distributed lock for a resource."""
        pass

    @abstractmethod
    async def release_lock(self, lease: CacheLockLease) -> bool:
        """Release the distributed lock only when the lock token still matches."""
        pass

    @abstractmethod
    async def claim_operation(
        self,
        consumer_name: str,
        operation_id: str,
        message_id: str,
        correlation_id: str | None = None,
        lock_ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_operation(self, consumer_name: str, operation_id: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    async def store_operation_response(
        self,
        consumer_name: str,
        operation_id: str,
        response_payload: dict[str, Any],
        routing_key: str,
    ) -> None:
        pass

    @abstractmethod
    async def mark_operation_completed(self, consumer_name: str, operation_id: str) -> None:
        pass

    @abstractmethod
    async def mark_operation_retryable(
        self,
        consumer_name: str,
        operation_id: str,
        error: str,
    ) -> None:
        pass

    @abstractmethod
    async def mark_operation_failed(self, consumer_name: str, operation_id: str, error: str) -> None:
        pass
