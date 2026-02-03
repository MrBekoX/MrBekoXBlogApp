"""RabbitMQ adapter - Concrete implementation of IMessageBroker."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractQueue

from app.domain.interfaces.i_message_broker import IMessageBroker, MessageHandler
from app.core.config import settings

logger = logging.getLogger(__name__)

# Constants for RabbitMQ topology
EXCHANGE_NAME = "blog.events"
QUEUE_NAME = "q.ai.analysis"
DLX_EXCHANGE = "dlx.blog"
DLQ_NAME = "dlq.ai.analysis"

# Routing keys to listen to
ROUTING_KEYS = [
    "article.created",
    "article.published",
    "article.updated",
    "ai.analysis.requested",
    "ai.title.generation.requested",
    "ai.excerpt.generation.requested",
    "ai.tags.generation.requested",
    "ai.seo.generation.requested",
    "ai.content.improvement.requested",
    "chat.message.requested",
]


class RabbitMQAdapter(IMessageBroker):
    """
    RabbitMQ implementation of message broker.

    Features:
    - Robust connection with auto-reconnect
    - QoS prefetch for backpressure control
    - Manual acknowledgment for guaranteed delivery
    - Dead letter queue for failed messages
    """

    def __init__(self, rabbitmq_url: str | None = None):
        self._rabbitmq_url = rabbitmq_url or settings.rabbitmq_url
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._queue: AbstractQueue | None = None
        self._exchange: aio_pika.Exchange | None = None
        self._consuming = False
        self._max_retries = 5

    async def connect(self) -> None:
        """Establish connection to RabbitMQ."""
        logger.info(f"Connecting to RabbitMQ at {settings.rabbitmq_host}")

        # Use robust connection for auto-reconnect
        self._connection = await aio_pika.connect_robust(
            self._rabbitmq_url,
            client_properties={"connection_name": "ai-agent-service"},
        )

        # Create channel with QoS
        self._channel = await self._connection.channel()

        # Critical: Set prefetch_count to 1 for backpressure
        await self._channel.set_qos(prefetch_count=1)

        # Declare topology
        await self._declare_topology()

        logger.info("Connected to RabbitMQ and declared topology")

    async def _declare_topology(self) -> None:
        """Declare exchanges, queues, and bindings."""
        if not self._channel:
            raise RuntimeError("Channel not initialized")

        # Declare Dead Letter Exchange
        dlx_exchange = await self._channel.declare_exchange(
            DLX_EXCHANGE,
            ExchangeType.FANOUT,
            durable=True,
        )

        # Declare Dead Letter Queue
        dlq = await self._channel.declare_queue(
            DLQ_NAME,
            durable=True,
        )
        await dlq.bind(dlx_exchange)

        # Declare main exchange
        self._exchange = await self._channel.declare_exchange(
            EXCHANGE_NAME,
            ExchangeType.DIRECT,
            durable=True,
        )

        # Declare main queue with dead letter configuration
        self._queue = await self._channel.declare_queue(
            QUEUE_NAME,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_EXCHANGE,
                "x-queue-type": "quorum",
            },
        )

        # Bind queue to exchange for all routing keys
        for routing_key in ROUTING_KEYS:
            await self._queue.bind(self._exchange, routing_key=routing_key)
            logger.info(f"✅ Bound queue {QUEUE_NAME} to routing_key: {routing_key}")

        logger.info(f"Declared exchange={EXCHANGE_NAME}, queue={QUEUE_NAME}, bindings={len(ROUTING_KEYS)}")

    async def disconnect(self) -> None:
        """Close connection to RabbitMQ."""
        await self.stop_consuming()

        if self._connection:
            await self._connection.close()
            self._connection = None
            self._channel = None
            self._queue = None
            self._exchange = None

        logger.info("Disconnected from RabbitMQ")

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
        if self._exchange is None:
            logger.error("RabbitMQ exchange not initialized")
            return False

        try:
            # Ensure message has required fields
            if "messageId" not in message:
                message["messageId"] = str(uuid.uuid4())
            if "timestamp" not in message:
                message["timestamp"] = datetime.utcnow().isoformat()
            if "correlationId" not in message:
                message["correlationId"] = correlation_id or str(uuid.uuid4())

            await self._exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=message["messageId"],
                    correlation_id=message["correlationId"],
                ),
                routing_key=routing_key,
            )

            return True

        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            return False

    async def start_consuming(self, handler: MessageHandler) -> None:
        """
        Start consuming messages from the queue.

        Args:
            handler: Async function to handle each message
        """
        if not self._queue:
            raise RuntimeError("Not connected. Call connect() first.")

        self._consuming = True
        logger.info(f"Starting to consume from {QUEUE_NAME}")

        async with self._queue.iterator() as queue_iter:
            async for message in queue_iter:
                if not self._consuming:
                    break

                await self._handle_message(message, handler)

    async def _handle_message(
        self,
        message: aio_pika.IncomingMessage,
        handler: MessageHandler
    ) -> None:
        """Handle a single message with retry logic."""
        delivery_count = message.headers.get("x-delivery-count", 0) if message.headers else 0

        # Log incoming message
        logger.info(f"Received message: routing_key={message.routing_key}, message_id={message.message_id}")

        try:
            success, reason = await handler(message.body)

            if success:
                await message.ack()

            elif reason == "locked":
                import asyncio
                await asyncio.sleep(2.0)
                await message.nack(requeue=True)

            elif reason.startswith("malformed"):
                await message.nack(requeue=False)
                logger.warning(f"Message rejected (malformed): {reason}")

            elif reason.startswith("non_recoverable"):
                await message.nack(requeue=False)
                logger.error(f"Message sent to DLQ (non-recoverable): {reason}")

            else:
                if delivery_count >= self._max_retries:
                    await message.nack(requeue=False)
                    logger.error(f"Message sent to DLQ after {delivery_count} retries")
                else:
                    await message.nack(requeue=True)
                    logger.warning(f"Message requeued ({delivery_count}/{self._max_retries})")

        except Exception as e:
            logger.exception(f"Unexpected error handling message: {e}")
            await message.nack(requeue=True)

    async def stop_consuming(self) -> None:
        """Stop consuming messages."""
        self._consuming = False
        logger.info("Stopped consuming messages")

    def is_connected(self) -> bool:
        """Check if connected to the broker."""
        return (
            self._connection is not None and
            not self._connection.is_closed and
            self._channel is not None
        )
