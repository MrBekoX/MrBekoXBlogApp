"""RabbitMQ consumer for article events."""

import asyncio
import logging
from typing import Optional
import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractQueue

from app.core.config import settings
from app.messaging.processor import MessageProcessor

logger = logging.getLogger(__name__)

# Constants for RabbitMQ topology
EXCHANGE_NAME = "blog.events"
QUEUE_NAME = "q.ai.analysis"
# Listen to both article events and explicit analysis requests
ROUTING_KEYS = [
    "article.created",
    "article.published",
    "article.updated",
    "ai.analysis.requested",  # New: explicit analysis request from Backend
    "ai.title.generation.requested",    # New: title generation requests
    "ai.excerpt.generation.requested",  # New: excerpt generation requests
    "ai.tags.generation.requested",     # New: tags generation requests
    "ai.seo.generation.requested",      # New: SEO description generation requests
    "ai.content.improvement.requested", # New: content improvement requests
    "chat.message.requested",           # New: chat message requests
]
DLX_EXCHANGE = "dlx.blog"
DLQ_NAME = "dlq.ai.analysis"


class RabbitMQConsumer:
    """
    RabbitMQ consumer for processing article events.

    Features:
    - Robust connection with auto-reconnect
    - QoS prefetch for backpressure control
    - Manual acknowledgment for guaranteed delivery
    - Dead letter queue for failed messages
    """

    def __init__(self):
        self._connection: Optional[AbstractRobustConnection] = None
        self._channel: Optional[AbstractChannel] = None
        self._queue: Optional[AbstractQueue] = None
        self._processor = MessageProcessor()
        self._consuming = False
        self._max_retries = 5

    async def connect(self) -> None:
        """Establish connection to RabbitMQ."""
        logger.info(f"Connecting to RabbitMQ at {settings.rabbitmq_host}")

        # Use robust connection for auto-reconnect
        self._connection = await aio_pika.connect_robust(
            settings.rabbitmq_url,
            client_properties={"connection_name": "ai-agent-service"},
        )

        # Create channel with QoS
        self._channel = await self._connection.channel()

        # Critical: Set prefetch_count to 1 for backpressure
        await self._channel.set_qos(prefetch_count=1)

        # Declare topology
        await self._declare_topology()

        # Initialize processor
        await self._processor.initialize()

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
        exchange = await self._channel.declare_exchange(
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
                "x-queue-type": "quorum",  # Quorum queue for better durability
            },
        )

        # Bind queue to exchange for all routing keys
        for routing_key in ROUTING_KEYS:
            await self._queue.bind(exchange, routing_key=routing_key)

        logger.info(f"Declared exchange={EXCHANGE_NAME}, queue={QUEUE_NAME}, routing_keys={ROUTING_KEYS}")

    async def start_consuming(self) -> None:
        """Start consuming messages from the queue."""
        if not self._queue:
            raise RuntimeError("Not connected. Call connect() first.")

        self._consuming = True
        logger.info(f"Starting to consume from {QUEUE_NAME}")

        async with self._queue.iterator() as queue_iter:
            async for message in queue_iter:
                if not self._consuming:
                    break

                await self._handle_message(message)

    async def _handle_message(self, message: aio_pika.IncomingMessage) -> None:
        """
        Handle a single message with retry logic.

        Args:
            message: Incoming RabbitMQ message
        """
        # Get delivery count for retry tracking
        delivery_count = message.headers.get("x-delivery-count", 0) if message.headers else 0

        try:
            # Process message
            success, reason = await self._processor.process_message(message.body)

            if success:
                # Acknowledge successful processing
                await message.ack()
                logger.debug(f"Message ACKed: {reason}")

            elif reason == "locked":
                # Delay before requeuing to prevent tight retry loop
                await asyncio.sleep(2.0)
                await message.nack(requeue=True)
                logger.debug("Message NACKed and requeued after delay (locked)")

            elif reason.startswith("malformed"):
                # Don't requeue malformed messages
                await message.nack(requeue=False)
                logger.warning(f"Message rejected (malformed): {reason}")

            elif reason.startswith("non_recoverable"):
                # Non-recoverable errors (HTTP 404, 400, 401, 403) go directly to DLQ
                await message.nack(requeue=False)
                logger.error(f"Message sent to DLQ (non-recoverable): {reason}")

            else:
                # Error - check retry count
                if delivery_count >= self._max_retries:
                    # Too many retries, send to DLQ
                    await message.nack(requeue=False)
                    logger.error(f"Message sent to DLQ after {delivery_count} retries")
                else:
                    # Requeue for retry
                    await message.nack(requeue=True)
                    logger.warning(f"Message requeued for retry ({delivery_count}/{self._max_retries})")

        except Exception as e:
            logger.exception(f"Unexpected error handling message: {e}")
            # Requeue on unexpected errors
            await message.nack(requeue=True)

    async def stop_consuming(self) -> None:
        """Stop consuming messages."""
        self._consuming = False
        logger.info("Stopped consuming messages")

    async def disconnect(self) -> None:
        """Close connection to RabbitMQ."""
        await self.stop_consuming()

        if self._processor:
            await self._processor.shutdown()

        if self._connection:
            await self._connection.close()
            self._connection = None
            self._channel = None
            self._queue = None

        logger.info("Disconnected from RabbitMQ")


# Global consumer instance
consumer = RabbitMQConsumer()
