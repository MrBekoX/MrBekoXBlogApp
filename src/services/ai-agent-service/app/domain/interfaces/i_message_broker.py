"""Message Broker interface - Contract for messaging operations."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable


MessageHandler = Callable[[bytes], Awaitable[tuple[bool, str]]]


class IMessageBroker(ABC):
    """
    Abstract interface for message broker operations.

    Implementations can be RabbitMQ, Kafka, Redis Pub/Sub, etc.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the message broker."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the message broker connection."""
        pass

    @abstractmethod
    async def publish(
        self,
        routing_key: str,
        message: dict[str, Any],
        correlation_id: str | None = None
    ) -> bool:
        """
        Publish a message to the broker.

        Args:
            routing_key: The routing key for message delivery
            message: The message payload as dictionary
            correlation_id: Optional correlation ID for tracking

        Returns:
            True if published successfully
        """
        pass

    @abstractmethod
    async def start_consuming(
        self,
        handler: MessageHandler
    ) -> None:
        """
        Start consuming messages from the queue.

        Args:
            handler: Async function to handle each message
                    Returns tuple of (success: bool, reason: str)
        """
        pass

    @abstractmethod
    async def stop_consuming(self) -> None:
        """Stop consuming messages."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to the broker."""
        pass

    @abstractmethod
    async def start_consuming_multi(
        self,
        handlers: dict[str, "MessageHandler"],
    ) -> None:
        """Start consuming from multiple queues with separate handlers.

        Args:
            handlers: Dict mapping queue_name -> handler function
        """
        pass
