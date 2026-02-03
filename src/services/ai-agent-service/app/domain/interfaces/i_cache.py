"""Cache interface - Contract for caching and distributed locking."""

from abc import ABC, abstractmethod
from typing import Any


class ICache(ABC):
    """
    Abstract interface for cache operations.

    Implementations can be Redis, Memcached, In-Memory, etc.
    Supports both simple caching and distributed locking patterns.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the cache service."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the cache connection."""
        pass

    # ==================== Basic Cache Operations ====================

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Get a string value from cache."""
        pass

    @abstractmethod
    async def set(
        self,
        key: str,
        value: str,
        ttl_seconds: int | None = None
    ) -> None:
        """Set a string value in cache with optional TTL."""
        pass

    @abstractmethod
    async def get_json(self, key: str) -> Any | None:
        """Get a JSON value from cache (deserialized)."""
        pass

    @abstractmethod
    async def set_json(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None
    ) -> None:
        """Set a JSON value in cache (serialized)."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a key from cache."""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        pass

    # ==================== Idempotency Pattern ====================

    @abstractmethod
    async def is_processed(self, message_id: str) -> bool:
        """Check if a message has already been processed (idempotency)."""
        pass

    @abstractmethod
    async def mark_processed(
        self,
        message_id: str,
        ttl_seconds: int = 86400
    ) -> None:
        """Mark a message as processed with TTL (default: 24 hours)."""
        pass

    # ==================== Distributed Locking ====================

    @abstractmethod
    async def acquire_lock(
        self,
        resource_id: str,
        ttl_seconds: int = 300
    ) -> bool:
        """
        Try to acquire a distributed lock for a resource.

        Args:
            resource_id: The resource identifier to lock
            ttl_seconds: Lock timeout in seconds (default: 5 minutes)

        Returns:
            True if lock acquired, False if already locked
        """
        pass

    @abstractmethod
    async def release_lock(self, resource_id: str) -> None:
        """Release the distributed lock for a resource."""
        pass
