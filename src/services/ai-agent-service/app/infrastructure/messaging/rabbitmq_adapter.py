"""RabbitMQ adapter - Concrete implementation of IMessageBroker."""

import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractQueue

from app.domain.interfaces.i_message_broker import IMessageBroker, MessageHandler
from app.core.config import settings
from app.core.logging_utils import (
    set_request_id,
    clear_request_id,
    trace_span,
    get_request_id,
)
from app.monitoring.metrics import (
    record_poison_message,
    set_broker_queue_depth,
    set_broker_backlog_over_threshold,
)

logger = logging.getLogger(__name__)

# Constants for RabbitMQ topology
EXCHANGE_NAME = "blog.events"
DLX_EXCHANGE = "dlx.blog"
QUARANTINE_EXCHANGE = "quarantine.blog"
QUARANTINE_ROUTING_KEY = "poison.message"

# Legacy queue (kept during migration)
LEGACY_QUEUE_NAME = "q.ai.analysis"
LEGACY_DLQ_NAME = "dlq.ai.analysis"
LEGACY_QUARANTINE_QUEUE = "q.ai.analysis.quarantine"

# Priority queues
QUEUE_CHAT = "q.chat.requests"
QUEUE_AUTHORING = "q.ai.authoring"
QUEUE_BACKGROUND = "q.ai.background"

DLQ_CHAT = "dlq.chat.requests"
DLQ_AUTHORING = "dlq.ai.authoring"
DLQ_BACKGROUND = "dlq.ai.background"
QUARANTINE_QUEUE = "q.ai.analysis.quarantine"  # shared quarantine

ROUTING_KEYS_CHAT = ["chat.message.requested"]
ROUTING_KEYS_AUTHORING = [
    "ai.title.generation.requested",
    "ai.excerpt.generation.requested",
    "ai.tags.generation.requested",
    "ai.seo.generation.requested",
    "ai.content.improvement.requested",
]
ROUTING_KEYS_BACKGROUND = [
    "article.created",
    "article.published",
    "article.updated",
    "ai.analysis.requested",
    "ai.summarize.requested",
    "ai.keywords.requested",
    "ai.sentiment.requested",
    "ai.reading-time.requested",
    "ai.geo-optimize.requested",
    "ai.collect-sources.requested",
]

# Combined for backward compat
ROUTING_KEYS = ROUTING_KEYS_CHAT + ROUTING_KEYS_AUTHORING + ROUTING_KEYS_BACKGROUND


class RabbitMQAdapter(IMessageBroker):
    """
    RabbitMQ implementation of message broker.

    Features:
    - Robust connection with auto-reconnect
    - QoS prefetch for backpressure control
    - Manual acknowledgment for guaranteed delivery
    - Dead letter queue for failed messages
    """

    def __init__(self, rabbitmq_url: str | None = None, stats_publisher=None):
        self._rabbitmq_url = rabbitmq_url or settings.rabbitmq_url
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._queue: AbstractQueue | None = None
        self._exchange: aio_pika.Exchange | None = None
        self._quarantine_exchange: aio_pika.Exchange | None = None
        self._quarantine_queue: AbstractQueue | None = None
        self._consuming = False
        self._max_retries = max(1, settings.broker_message_max_retries)
        self._queue_max_retries: dict[str, int] = {
            QUEUE_CHAT: settings.chat_max_retries,
            QUEUE_AUTHORING: settings.authoring_max_retries,
            QUEUE_BACKGROUND: settings.background_max_retries,
        }
        self._lock_retry_delay_seconds = max(0.1, settings.broker_lock_retry_delay_seconds)
        self._quarantine_preview_bytes = max(256, settings.broker_quarantine_preview_bytes)
        self._quarantine_store_body_max_bytes = max(
            1024, settings.broker_quarantine_store_body_max_bytes
        )
        self._enable_poison_runbook_hook = settings.enable_poison_runbook_hook
        self._publish_timeout_seconds = max(1, settings.broker_publish_timeout_seconds)
        self._publish_retry_attempts = max(1, settings.worker_retry_attempts)
        self._publish_retry_base_delay_seconds = max(0.05, settings.worker_retry_base_delay_seconds)
        self._publish_retry_max_backoff_seconds = max(
            self._publish_retry_base_delay_seconds,
            settings.worker_retry_max_backoff_seconds,
        )
        self._consumer_prefetch_count = max(1, settings.broker_consumer_prefetch_count)
        self._consumer_concurrency = max(1, settings.broker_consumer_concurrency)
        self._queue_backlog_warn_threshold = max(0, settings.broker_backlog_warn_threshold)
        self._handler_timeout_seconds = max(1, settings.worker_operation_timeout_seconds)
        self._inflight_tasks: set[asyncio.Task] = set()
        self._queue_stats_lock = asyncio.Lock()
        self._queue_depth: int | None = None
        self._queue_consumer_count: int | None = None
        self._queue_backlog_over_threshold = False
        self._queue_stats_last_observed_at: str | None = None
        self._stats_refresh_every_messages = 20
        self._processed_since_stats_refresh = 0
        self._stats_publisher = stats_publisher
        self._priority_queues: dict[str, AbstractQueue] = {}
        self._priority_channels: dict[str, AbstractChannel] = {}
        self._priority_consumer_tags: list[str] = []
        self._multi_handlers: dict[str, MessageHandler] = {}

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

        # Configure QoS using environment-driven throughput settings
        await self._channel.set_qos(prefetch_count=self._consumer_prefetch_count)

        # Declare topology
        await self._declare_topology()
        await self.refresh_queue_stats()

        logger.info("Connected to RabbitMQ and declared topology")

    async def _declare_topology(self) -> None:
        """Declare exchanges, queues, and bindings for priority queue topology."""
        if not self._channel:
            raise RuntimeError("Channel not initialized")

        # Declare Dead Letter Exchange
        dlx_exchange = await self._channel.declare_exchange(
            DLX_EXCHANGE, ExchangeType.FANOUT, durable=True,
        )

        # Declare quarantine exchange and queue
        self._quarantine_exchange = await self._channel.declare_exchange(
            QUARANTINE_EXCHANGE, ExchangeType.DIRECT, durable=True,
        )
        self._quarantine_queue = await self._channel.declare_queue(
            QUARANTINE_QUEUE, durable=True,
        )
        await self._quarantine_queue.bind(
            self._quarantine_exchange, routing_key=QUARANTINE_ROUTING_KEY
        )

        # Declare main exchange
        self._exchange = await self._channel.declare_exchange(
            EXCHANGE_NAME, ExchangeType.DIRECT, durable=True,
        )

        # Priority queues with per-queue TTL and DLQ
        queue_configs = [
            (QUEUE_CHAT, DLQ_CHAT, ROUTING_KEYS_CHAT, settings.queue_chat_ttl_ms),
            (QUEUE_AUTHORING, DLQ_AUTHORING, ROUTING_KEYS_AUTHORING, settings.queue_authoring_ttl_ms),
            (QUEUE_BACKGROUND, DLQ_BACKGROUND, ROUTING_KEYS_BACKGROUND, settings.queue_background_ttl_ms),
        ]

        for queue_name, dlq_name, routing_keys, ttl_ms in queue_configs:
            # DLQ for this priority
            dlq = await self._channel.declare_queue(dlq_name, durable=True)
            await dlq.bind(dlx_exchange)

            # Main queue with TTL and DLX
            queue = await self._channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": DLX_EXCHANGE,
                    "x-queue-type": "quorum",
                    "x-message-ttl": ttl_ms,
                },
            )

            for routing_key in routing_keys:
                await queue.bind(self._exchange, routing_key=routing_key)
                logger.info(f"Bound queue {queue_name} to routing_key: {routing_key}")

            self._priority_queues[queue_name] = queue

        # Legacy queue (migration: keep for draining old messages)
        legacy_dlq = await self._channel.declare_queue(LEGACY_DLQ_NAME, durable=True)
        await legacy_dlq.bind(dlx_exchange)

        self._queue = await self._channel.declare_queue(
            LEGACY_QUEUE_NAME,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_EXCHANGE,
                "x-queue-type": "quorum",
            },
        )

        logger.info(
            f"Declared priority topology: "
            f"{QUEUE_CHAT}, {QUEUE_AUTHORING}, {QUEUE_BACKGROUND} "
            f"+ legacy {LEGACY_QUEUE_NAME}"
        )

    async def disconnect(self) -> None:
        """Close connection to RabbitMQ."""
        await self.stop_consuming()

        if self._connection:
            await self._connection.close()
            self._connection = None
            self._channel = None
            self._queue = None
            self._exchange = None
            self._quarantine_exchange = None
            self._quarantine_queue = None

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

        # Ensure message has required fields
        if "messageId" not in message:
            message["messageId"] = str(uuid.uuid4())
        if "timestamp" not in message:
            message["timestamp"] = datetime.now(timezone.utc).isoformat()
        if "correlationId" not in message:
            message["correlationId"] = (
                correlation_id
                or get_request_id()
                or message["messageId"]
            )

        encoded_message = json.dumps(message).encode()
        attempts = self._publish_retry_attempts

        for attempt in range(1, attempts + 1):
            try:
                set_request_id(message["correlationId"])
                with trace_span(
                    "mq.publish",
                    routing_key=routing_key,
                    attempt=attempt,
                ):
                    await asyncio.wait_for(
                        self._exchange.publish(
                            aio_pika.Message(
                                body=encoded_message,
                                content_type="application/json",
                                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                                message_id=message["messageId"],
                                correlation_id=message["correlationId"],
                                headers={
                                    "operationId": message.get("operationId"),
                                    "causationId": message.get("causationId"),
                                },
                            ),
                            routing_key=routing_key,
                        ),
                        timeout=self._publish_timeout_seconds,
                    )
                return True
            except Exception as e:
                is_last_attempt = attempt >= attempts
                if is_last_attempt:
                    logger.error(
                        f"Failed to publish message after {attempts} attempts: {e} "
                        f"(routing_key={routing_key}, correlationId={message['correlationId']})"
                    )
                    return False

                backoff_seconds = min(
                    self._publish_retry_base_delay_seconds * (2 ** (attempt - 1)),
                    self._publish_retry_max_backoff_seconds,
                )
                logger.warning(
                    f"Publish transient failure attempt {attempt}/{attempts}: {e}. "
                    f"Retrying in {backoff_seconds:.2f}s "
                    f"(routing_key={routing_key}, correlationId={message['correlationId']})"
                )
                await asyncio.sleep(backoff_seconds)
            finally:
                clear_request_id()

        return False

    async def publish_response(
        self,
        routing_key: str,
        message: bytes,
        correlation_id: str | None = None
    ) -> bool:
        """
        Publish a raw bytes message response to the broker.

        Args:
            routing_key: The routing key for message delivery
            message: The raw message bytes
            correlation_id: Optional correlation ID for tracking

        Returns:
            True if published successfully
        """
        if self._exchange is None:
            logger.error("RabbitMQ exchange not initialized")
            return False

        message_id = str(uuid.uuid4())
        correlation_id = correlation_id or get_request_id() or message_id

        try:
            set_request_id(correlation_id)
            with trace_span(
                "mq.publish_response",
                routing_key=routing_key,
            ):
                await asyncio.wait_for(
                    self._exchange.publish(
                        aio_pika.Message(
                            body=message,
                            content_type="application/json",
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            message_id=message_id,
                            correlation_id=correlation_id,
                        ),
                        routing_key=routing_key,
                    ),
                    timeout=self._publish_timeout_seconds,
                )
            return True
        except Exception as e:
            logger.error(
                f"Failed to publish response: {e} "
                f"(routing_key={routing_key}, correlationId={correlation_id})"
            )
            return False
        finally:
            clear_request_id()

    async def start_consuming(self, handler: MessageHandler) -> None:
        """
        Start consuming messages from the queue using callback-based consumption.

        This pattern is more reliable than iterator-based consumption for
        detecting new messages that arrive after the consumer starts.

        Args:
            handler: Async function to handle each message
        """
        if not self._queue:
            raise RuntimeError("Not connected. Call connect() first.")

        self._consuming = True
        self._semaphore = asyncio.Semaphore(self._consumer_concurrency)
        self._handler = handler

        logger.info(
            f"Starting to consume from {LEGACY_QUEUE_NAME} "
            f"(prefetch={self._consumer_prefetch_count}, "
            f"concurrency={self._consumer_concurrency})"
        )
        await self.refresh_queue_stats()

        # Use callback-based consumption for reliable message delivery
        self._consumer_tag = await self._queue.consume(self._on_message_callback)
        logger.info(f"Consumer registered with tag: {self._consumer_tag}")

        # Keep the consumer running until stopped
        heartbeat_counter = 0
        while self._consuming:
            await asyncio.sleep(0.5)
            heartbeat_counter += 1
            # Log heartbeat every 30 seconds (60 iterations * 0.5s)
            if heartbeat_counter % 60 == 0:
                queue_stats = self.get_cached_queue_stats()
                logger.info(
                    f"Consumer heartbeat: consuming={self._consuming}, "
                    f"queue_depth={queue_stats.get('message_count')}, "
                    f"inflight_tasks={len(self._inflight_tasks)}, "
                    f"connection_ok={self.is_connected()}"
                )

        # Wait for in-flight tasks to complete.
        # asyncio.shield() ile gather'ı koruyoruz: _consumer_task iptal edildiğinde
        # (standby modu) CancelledError, uçuştaki görevlere yayılmaz.
        # CancelledError yakalanırsa görevler açıkça beklenir — hiçbir görev kaybolmaz.
        if self._inflight_tasks:
            try:
                await asyncio.shield(
                    asyncio.gather(*self._inflight_tasks, return_exceptions=True)
                )
            except asyncio.CancelledError:
                logger.warning("Consumer shutdown: waiting for in-flight tasks to complete...")
                await asyncio.gather(*self._inflight_tasks, return_exceptions=True)
            finally:
                self._inflight_tasks.clear()

    async def start_consuming_multi(
        self,
        handlers: dict[str, MessageHandler],
    ) -> None:
        """Start consuming from multiple priority queues.

        Args:
            handlers: Dict mapping queue_name -> handler function.
        """
        if not self._priority_queues:
            raise RuntimeError("Priority queues not declared. Call connect() first.")

        self._consuming = True
        self._multi_handlers = handlers

        # Per-queue channels with separate prefetch
        prefetch_map = {
            QUEUE_CHAT: settings.queue_chat_prefetch,
            QUEUE_AUTHORING: settings.queue_authoring_prefetch,
            QUEUE_BACKGROUND: settings.queue_background_prefetch,
        }

        for queue_name, handler in handlers.items():
            if queue_name not in self._priority_queues:
                logger.warning(f"Queue {queue_name} not declared, skipping")
                continue

            # Create dedicated channel per queue for independent prefetch
            channel = await self._connection.channel()
            prefetch = prefetch_map.get(queue_name, 1)
            await channel.set_qos(prefetch_count=prefetch)
            self._priority_channels[queue_name] = channel

            # Re-declare queue passively on the new channel to get a reference
            queue = await channel.declare_queue(queue_name, passive=True)

            tag = await queue.consume(
                lambda msg, qn=queue_name: self._on_priority_message(msg, qn)
            )
            self._priority_consumer_tags.append(tag)

            logger.info(
                f"Started consuming from {queue_name} "
                f"(prefetch={prefetch}, tag={tag})"
            )

        # Also consume legacy queue if it has messages
        if self._queue:
            legacy_handler = handlers.get(LEGACY_QUEUE_NAME) or handlers.get(QUEUE_BACKGROUND)
            if legacy_handler:
                self._multi_handlers[LEGACY_QUEUE_NAME] = legacy_handler
                tag = await self._queue.consume(
                    lambda msg: self._on_priority_message(msg, LEGACY_QUEUE_NAME)
                )
                self._priority_consumer_tags.append(tag)
                logger.info(f"Started consuming legacy queue {LEGACY_QUEUE_NAME}")

        # Keep running
        heartbeat_counter = 0
        while self._consuming:
            await asyncio.sleep(0.5)
            heartbeat_counter += 1
            if heartbeat_counter % 60 == 0:
                all_stats = await self.refresh_queue_stats()
                logger.info(
                    f"Multi-consumer heartbeat: consuming={self._consuming}, "
                    f"inflight_tasks={len(self._inflight_tasks)}, "
                    f"connection_ok={self.is_connected()}"
                )

        # Drain in-flight
        if self._inflight_tasks:
            try:
                await asyncio.shield(
                    asyncio.gather(*self._inflight_tasks, return_exceptions=True)
                )
            except asyncio.CancelledError:
                await asyncio.gather(*self._inflight_tasks, return_exceptions=True)
            finally:
                self._inflight_tasks.clear()

    async def _on_priority_message(
        self, message: aio_pika.IncomingMessage, queue_name: str
    ) -> None:
        """Callback for priority queue messages. Injects queue_name into headers."""
        if not self._consuming:
            await message.nack(requeue=True)
            return

        # Tag message with source queue for downstream priority decisions
        if not hasattr(message, 'headers') or message.headers is None:
            message.headers = {}
        message.headers["x-source-queue"] = queue_name

        handler = self._multi_handlers.get(queue_name)
        if not handler:
            logger.error(f"No handler for queue {queue_name}, nacking")
            await message.nack(requeue=True)
            return

        task = asyncio.create_task(
            self._handle_message(message, handler)
        )
        self._inflight_tasks.add(task)
        task.add_done_callback(self._inflight_tasks.discard)

    async def _on_message_callback(self, message: aio_pika.IncomingMessage) -> None:
        """Callback invoked for each incoming message."""
        logger.debug(
            f"Callback received message: routing_key={message.routing_key}, "
            f"message_id={message.message_id}"
        )

        if not self._consuming:
            logger.warning(f"Received message but consuming=False, requeueing")
            await message.nack(requeue=True)
            return

        # Acquire semaphore to limit concurrency
        await self._semaphore.acquire()

        task = asyncio.create_task(
            self._process_message_callback(message)
        )
        self._inflight_tasks.add(task)
        task.add_done_callback(self._inflight_tasks.discard)

    async def _process_message_callback(self, message: aio_pika.IncomingMessage) -> None:
        """Process a message from callback and release semaphore."""
        try:
            await self._handle_message(message, self._handler)
        finally:
            self._processed_since_stats_refresh += 1
            if self._processed_since_stats_refresh >= self._stats_refresh_every_messages:
                self._processed_since_stats_refresh = 0
                await self.refresh_queue_stats()
            self._semaphore.release()

    async def _process_message_task(
        self,
        message: aio_pika.IncomingMessage,
        handler: MessageHandler,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Process one message under bounded concurrency and refresh queue stats periodically."""
        try:
            await self._handle_message(message, handler)
        finally:
            self._processed_since_stats_refresh += 1
            if self._processed_since_stats_refresh >= self._stats_refresh_every_messages:
                self._processed_since_stats_refresh = 0
                await self.refresh_queue_stats()
            semaphore.release()

    @staticmethod
    def _classify_reason_taxonomy(reason: str | None) -> str:
        """Map handler reason to stable poison-message taxonomy."""
        normalized = (reason or "").strip().lower()
        allowed_nonrecoverable = {
            "validation_error",
            "permission_denied",
            "not_found",
            "unknown_error",
        }
        allowed_transient = {
            "timeout",
            "connection_error",
            "rate_limited",
            "circuit_open",
            "unknown_error",
        }
        if not normalized:
            return "unknown.no_reason"
        if normalized == "locked":
            return "transient.lock_contention"
        if normalized == "duplicate":
            return "idempotent.duplicate"
        if normalized == "success":
            return "success"
        if normalized.startswith("malformed:json"):
            return "poison.malformed.json"
        if normalized.startswith("malformed:schema"):
            return "poison.malformed.schema"
        if normalized.startswith("malformed"):
            return "poison.malformed.unknown"
        if normalized.startswith("non_recoverable:"):
            detail = normalized.split(":", 1)[1].strip().replace(" ", "_")
            if detail not in allowed_nonrecoverable:
                detail = "unknown_error"
            return f"poison.non_recoverable.{detail}"
        if normalized.startswith("transient:"):
            detail = normalized.split(":", 1)[1].strip().replace(" ", "_")
            if detail not in allowed_transient:
                detail = "unknown_error"
            return f"transient.{detail}"
        if normalized.startswith("error:"):
            return "error.unclassified"
        return "unknown.unclassified"

    @staticmethod
    def _is_poison_reason(reason: str | None) -> bool:
        """Identify immediate poison reasons that should not be retried."""
        normalized = (reason or "").strip().lower()
        return normalized.startswith("malformed") or normalized.startswith("non_recoverable")

    def _extract_delivery_attempt(self, message: aio_pika.IncomingMessage) -> int:
        """
        Determine delivery attempt count.

        For quorum queues, x-delivery-count starts at 0 for first delivery.
        """
        headers = message.headers or {}
        count = headers.get("x-delivery-count")
        if count is not None:
            try:
                return int(count) + 1
            except (TypeError, ValueError):
                pass

        x_death = headers.get("x-death")
        if isinstance(x_death, list) and x_death:
            first = x_death[0]
            if isinstance(first, dict):
                dead_count = first.get("count")
                try:
                    return int(dead_count) + 1
                except (TypeError, ValueError):
                    pass

        return 1

    def _decode_body_preview(self, body: bytes) -> str:
        """Decode and truncate message body preview for quarantine payload."""
        truncated = body[: self._quarantine_preview_bytes]
        text = truncated.decode("utf-8", errors="replace")
        if len(body) > self._quarantine_preview_bytes:
            text += "...<truncated>"
        return text

    async def _invoke_poison_runbook(
        self,
        taxonomy: str,
        reason: str,
        message: aio_pika.IncomingMessage,
        delivery_attempt: int,
    ) -> str | None:
        """Invoke poison-message runbook hook; never raises."""
        if not self._enable_poison_runbook_hook:
            return None

        try:
            from app.security.runbook import trigger_poison_message_runbook

            return await trigger_poison_message_runbook(
                taxonomy=taxonomy,
                reason=reason,
                message_id=message.message_id or "",
                correlation_id=message.correlation_id,
                routing_key=message.routing_key,
                delivery_attempt=delivery_attempt,
            )
        except Exception as e:
            logger.error(f"Poison runbook hook invocation failed: {e}")
            return None

    async def _publish_quarantine_message(
        self,
        payload: dict[str, Any],
        correlation_id: str | None,
    ) -> bool:
        """Publish structured quarantine event for poison message triage."""
        if not self._quarantine_exchange:
            logger.error("Quarantine exchange not initialized")
            return False

        encoded = json.dumps(payload).encode("utf-8")
        try:
            await asyncio.wait_for(
                self._quarantine_exchange.publish(
                    aio_pika.Message(
                        body=encoded,
                        content_type="application/json",
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        message_id=payload.get("quarantineId"),
                        correlation_id=correlation_id or payload.get("correlationId"),
                        timestamp=datetime.now(timezone.utc),
                    ),
                    routing_key=QUARANTINE_ROUTING_KEY,
                ),
                timeout=self._publish_timeout_seconds,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to publish quarantine message: {e}")
            return False

    def _build_quarantine_payload(
        self,
        message: aio_pika.IncomingMessage,
        reason: str,
        taxonomy: str,
        delivery_attempt: int,
        incident_id: str | None = None,
    ) -> dict[str, Any]:
        """Create poison-message quarantine envelope."""
        body_size = len(message.body)
        original_body_stored = body_size <= self._quarantine_store_body_max_bytes
        original_body_base64 = (
            base64.b64encode(message.body).decode("ascii")
            if original_body_stored
            else None
        )
        return {
            "quarantineId": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sourceQueue": (message.headers or {}).get("x-source-queue", LEGACY_QUEUE_NAME),
            "routingKey": message.routing_key,
            "messageId": message.message_id,
            "correlationId": message.correlation_id,
            "deliveryAttempt": delivery_attempt,
            "reason": reason,
            "taxonomy": taxonomy,
            "incidentId": incident_id,
            "headers": message.headers or {},
            "bodyPreview": self._decode_body_preview(message.body),
            "bodySizeBytes": body_size,
            "originalBodyStored": original_body_stored,
            "originalBodyBase64": original_body_base64,
            "originalContentType": message.content_type,
        }

    async def get_quarantine_stats(self) -> dict[str, Any]:
        """Return quarantine queue stats for ops visibility."""
        if not self._quarantine_queue:
            return {
                "ready": False,
                "queue": QUARANTINE_QUEUE,
                "message_count": None,
                "consumer_count": None,
            }
        try:
            declaration = await self._quarantine_queue.declare(passive=True)
            msg_count = getattr(declaration, 'message_count', None)
            cons_count = getattr(declaration, 'consumer_count', None)
            if msg_count is None:
                try:
                    msg_count = declaration.declaration_result.message_count
                except (AttributeError, TypeError):
                    msg_count = None
            if cons_count is None:
                try:
                    cons_count = declaration.declaration_result.consumer_count
                except (AttributeError, TypeError):
                    cons_count = None
            return {
                "ready": True,
                "queue": QUARANTINE_QUEUE,
                "routing_key": QUARANTINE_ROUTING_KEY,
                "message_count": msg_count,
                "consumer_count": cons_count,
            }
        except Exception as e:
            logger.error(f"Failed to read quarantine stats: {e}")
            return {
                "ready": False,
                "queue": QUARANTINE_QUEUE,
                "message_count": None,
                "consumer_count": None,
                "error": str(e),
            }

    async def refresh_queue_stats(self) -> dict[str, Any]:
        """Refresh cached stats for all priority queues."""
        all_stats = {}

        # Priority queues
        for queue_name in [QUEUE_CHAT, QUEUE_AUTHORING, QUEUE_BACKGROUND]:
            stats = await self._refresh_single_queue_stats(queue_name)
            all_stats[queue_name] = stats

            # Publish to Redis for backend consumption
            if self._stats_publisher and stats.get("message_count") is not None:
                await self._stats_publisher.publish_queue_depth(
                    queue_name,
                    stats["message_count"],
                    stats.get("consumer_count"),
                )

        # Legacy queue
        if self._queue:
            stats = await self._refresh_single_queue_stats(LEGACY_QUEUE_NAME)
            all_stats[LEGACY_QUEUE_NAME] = stats

        # Aggregate for backward compat
        total_depth = sum(
            s.get("message_count", 0) or 0 for s in all_stats.values()
        )
        self._queue_depth = total_depth
        self._queue_backlog_over_threshold = total_depth > self._queue_backlog_warn_threshold
        self._queue_stats_last_observed_at = datetime.now(timezone.utc).isoformat()

        set_broker_backlog_over_threshold("all", self._queue_backlog_over_threshold)

        return all_stats

    async def _refresh_single_queue_stats(self, queue_name: str) -> dict[str, Any]:
        """Refresh stats for a single queue."""
        if not self._channel:
            return {"queue": queue_name, "message_count": None, "consumer_count": None}

        try:
            declaration = await self._channel.declare_queue(queue_name, passive=True)
            msg_count = getattr(declaration, 'message_count', None)
            cons_count = getattr(declaration, 'consumer_count', None)
            if msg_count is None:
                try:
                    msg_count = declaration.declaration_result.message_count
                except (AttributeError, TypeError):
                    msg_count = None
            if cons_count is None:
                try:
                    cons_count = declaration.declaration_result.consumer_count
                except (AttributeError, TypeError):
                    cons_count = None

            set_broker_queue_depth(queue_name, msg_count, cons_count)

            return {
                "queue": queue_name,
                "message_count": msg_count,
                "consumer_count": cons_count,
            }
        except Exception as e:
            logger.warning(f"Failed to refresh stats for {queue_name}: {e}")
            return {"queue": queue_name, "message_count": None, "consumer_count": None}

    def get_cached_queue_stats(self) -> dict[str, Any]:
        """Get latest cached queue stats without broker I/O."""
        return {
            "queue": LEGACY_QUEUE_NAME,
            "message_count": self._queue_depth,
            "consumer_count": self._queue_consumer_count,
            "backlog_over_threshold": self._queue_backlog_over_threshold,
            "warn_threshold": self._queue_backlog_warn_threshold,
            "observed_at": self._queue_stats_last_observed_at,
            "prefetch_count": self._consumer_prefetch_count,
            "consumer_concurrency": self._consumer_concurrency,
        }

    @staticmethod
    def _decode_quarantine_original_body(payload: dict[str, Any]) -> bytes:
        """Decode original message body bytes from quarantine payload."""
        encoded = payload.get("originalBodyBase64")
        if not encoded:
            raise ValueError("missing_original_body_base64")
        try:
            return base64.b64decode(encoded)
        except Exception as e:
            raise ValueError(f"invalid_original_body_base64: {e}") from e

    @staticmethod
    def _normalize_taxonomy_filters(taxonomy_prefixes: list[str] | None) -> list[str]:
        """Normalize taxonomy prefix filters."""
        if not taxonomy_prefixes:
            return []
        return [p.strip().lower() for p in taxonomy_prefixes if p and p.strip()]

    @staticmethod
    def _matches_taxonomy_filters(taxonomy: str, taxonomy_filters: list[str]) -> bool:
        """Return True when taxonomy passes prefix-based filtering."""
        if not taxonomy_filters:
            return True
        taxonomy_norm = (taxonomy or "").strip().lower()
        return any(taxonomy_norm.startswith(prefix) for prefix in taxonomy_filters)

    @staticmethod
    def _parse_quarantine_timestamp(timestamp_value: Any) -> datetime | None:
        """Parse quarantine timestamp to UTC datetime."""
        if not timestamp_value or not isinstance(timestamp_value, str):
            return None
        try:
            parsed = datetime.fromisoformat(timestamp_value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    @staticmethod
    def _is_within_max_age(timestamp_utc: datetime | None, max_age_seconds: int | None) -> bool:
        """Check whether payload age is within max-age policy."""
        if max_age_seconds is None:
            return True
        if max_age_seconds <= 0:
            return True
        if timestamp_utc is None:
            return False
        age_seconds = (datetime.now(timezone.utc) - timestamp_utc).total_seconds()
        return age_seconds <= max_age_seconds

    async def replay_quarantine_messages(
        self,
        max_messages: int = 10,
        dry_run: bool = False,
        taxonomy_prefixes: list[str] | None = None,
        max_age_seconds: int | None = None,
    ) -> dict[str, Any]:
        """
        Replay quarantined messages back to main exchange.

        - `dry_run=True`: validates and keeps messages in quarantine queue.
        - `dry_run=False`: publishes original message and ACKs quarantine record.
        """
        if not self._quarantine_queue or not self._exchange:
            raise RuntimeError("Broker is not initialized for quarantine replay")

        limit = max(1, min(max_messages, 500))
        taxonomy_filters = self._normalize_taxonomy_filters(taxonomy_prefixes)
        age_limit = max_age_seconds if max_age_seconds is None else max(1, max_age_seconds)
        replayed = 0
        failed = 0
        inspected = 0
        skipped = 0
        skipped_taxonomy = 0
        skipped_age = 0
        errors: list[dict[str, str]] = []

        for _ in range(limit):
            quarantine_message = await self._quarantine_queue.get(fail=False)
            if quarantine_message is None:
                break

            inspected += 1
            correlation_id = quarantine_message.correlation_id or f"req_{uuid.uuid4().hex[:16]}"
            set_request_id(correlation_id)
            try:
                with trace_span(
                    "mq.quarantine.replay",
                    dry_run=dry_run,
                    message_id=quarantine_message.message_id,
                ):
                    try:
                        payload = json.loads(quarantine_message.body.decode("utf-8"))
                    except Exception as e:
                        failed += 1
                        errors.append({"message_id": quarantine_message.message_id or "", "error": f"invalid_quarantine_payload:{e}"})
                        await quarantine_message.nack(requeue=True)
                        record_poison_message("poison.quarantine_payload_invalid", "replay_failed_requeue")
                        continue

                    taxonomy = payload.get("taxonomy", "unknown.unclassified")
                    routing_key = payload.get("routingKey")
                    if not routing_key:
                        failed += 1
                        errors.append({"message_id": payload.get("messageId", ""), "error": "missing_routing_key"})
                        await quarantine_message.nack(requeue=True)
                        record_poison_message(taxonomy, "replay_failed_requeue")
                        continue

                    if not self._matches_taxonomy_filters(taxonomy, taxonomy_filters):
                        skipped += 1
                        skipped_taxonomy += 1
                        await quarantine_message.nack(requeue=True)
                        record_poison_message(taxonomy, "replay_filtered_taxonomy")
                        continue

                    payload_timestamp = self._parse_quarantine_timestamp(payload.get("timestamp"))
                    if not self._is_within_max_age(payload_timestamp, age_limit):
                        skipped += 1
                        skipped_age += 1
                        await quarantine_message.nack(requeue=True)
                        record_poison_message(taxonomy, "replay_filtered_age")
                        continue

                    if dry_run:
                        skipped += 1
                        await quarantine_message.nack(requeue=True)
                        record_poison_message(taxonomy, "replay_dry_run")
                        continue

                    try:
                        original_body = self._decode_quarantine_original_body(payload)
                    except ValueError as e:
                        failed += 1
                        errors.append({"message_id": payload.get("messageId", ""), "error": str(e)})
                        await quarantine_message.nack(requeue=True)
                        record_poison_message(taxonomy, "replay_missing_body_requeue")
                        continue

                    replay_correlation = payload.get("correlationId") or correlation_id
                    replay_message_id = payload.get("messageId") or str(uuid.uuid4())
                    replay_headers = dict(payload.get("headers") or {})
                    replay_headers.update(
                        {
                            "x-replayed-from-quarantine": True,
                            "x-quarantine-id": payload.get("quarantineId"),
                            "x-quarantine-taxonomy": taxonomy,
                        }
                    )

                    await asyncio.wait_for(
                        self._exchange.publish(
                            aio_pika.Message(
                                body=original_body,
                                content_type=payload.get("originalContentType") or "application/json",
                                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                                message_id=replay_message_id,
                                correlation_id=replay_correlation,
                                headers=replay_headers,
                            ),
                            routing_key=routing_key,
                        ),
                        timeout=self._publish_timeout_seconds,
                    )

                    await quarantine_message.ack()
                    replayed += 1
                    record_poison_message(taxonomy, "replay_success")

            except Exception as e:
                failed += 1
                errors.append({"message_id": quarantine_message.message_id or "", "error": str(e)})
                await quarantine_message.nack(requeue=True)
                record_poison_message("transient.replay_handler_exception", "replay_failed_requeue")
            finally:
                clear_request_id()

        return {
            "queue": QUARANTINE_QUEUE,
            "dry_run": dry_run,
            "taxonomy_prefixes": taxonomy_filters,
            "max_age_seconds": age_limit,
            "requested": limit,
            "inspected": inspected,
            "replayed": replayed,
            "skipped": skipped,
            "skipped_taxonomy": skipped_taxonomy,
            "skipped_age": skipped_age,
            "failed": failed,
            "errors": errors[:20],
        }

    def _compute_backoff(self, delivery_attempt: int) -> float:
        """Compute exponential backoff delay for retry."""
        return min(
            settings.retry_backoff_base_seconds * (4 ** (delivery_attempt - 1)),
            settings.retry_backoff_max_seconds,
        )

    async def _handle_message(
        self,
        message: aio_pika.IncomingMessage,
        handler: MessageHandler
    ) -> None:
        """Handle a single message with retry logic."""
        delivery_attempt = self._extract_delivery_attempt(message)

        headers = message.headers or {}
        # Legacy single-queue path does not stamp x-source-queue; falls back to
        # LEGACY_QUEUE_NAME which maps to self._max_retries (not in _queue_max_retries).
        source_queue = headers.get("x-source-queue", LEGACY_QUEUE_NAME)

        # Per-queue max retries
        queue_max_retries = self._queue_max_retries.get(source_queue, self._max_retries)

        # Log incoming message
        logger.info(
            f"Received message: routing_key={message.routing_key}, "
            f"message_id={message.message_id}, correlation_id={message.correlation_id}, "
            f"attempt={delivery_attempt}/{queue_max_retries}"
        )

        try:
            if message.correlation_id:
                set_request_id(message.correlation_id)
            with trace_span(
                "mq.handle_message",
                routing_key=message.routing_key,
                message_id=message.message_id,
            ):
                # Wrap handler with timeout to prevent semaphore deadlock
                success, reason = await asyncio.wait_for(
                    handler(message.body),
                    timeout=self._handler_timeout_seconds
                )
            taxonomy = self._classify_reason_taxonomy(reason)

            if success:
                await message.ack()
                record_poison_message(taxonomy, "ack_success")

            elif reason == "locked":
                await asyncio.sleep(self._lock_retry_delay_seconds)
                await message.nack(requeue=True)
                record_poison_message(taxonomy, "requeue_locked")

            elif self._is_poison_reason(reason) or delivery_attempt >= queue_max_retries:
                if delivery_attempt >= queue_max_retries and not self._is_poison_reason(reason):
                    taxonomy = "poison.retry_budget_exhausted"
                incident_id = await self._invoke_poison_runbook(
                    taxonomy=taxonomy,
                    reason=reason,
                    message=message,
                    delivery_attempt=delivery_attempt,
                )
                quarantine_payload = self._build_quarantine_payload(
                    message=message,
                    reason=reason,
                    taxonomy=taxonomy,
                    delivery_attempt=delivery_attempt,
                    incident_id=incident_id,
                )
                quarantined = await self._publish_quarantine_message(
                    payload=quarantine_payload,
                    correlation_id=message.correlation_id,
                )
                if quarantined:
                    await message.ack()
                    record_poison_message(taxonomy, "quarantined")
                    logger.error(
                        f"Message quarantined: taxonomy={taxonomy}, reason={reason}, "
                        f"message_id={message.message_id}"
                    )
                else:
                    await message.nack(requeue=False)
                    record_poison_message(taxonomy, "dlq_fallback")
                    logger.error(
                        f"Quarantine publish failed, routed to DLQ fallback: taxonomy={taxonomy}, "
                        f"message_id={message.message_id}"
                    )

            else:
                # Exponential backoff before requeue
                backoff = self._compute_backoff(delivery_attempt)
                logger.warning(
                    f"Retry backoff: {backoff:.1f}s for {message.message_id} "
                    f"(attempt {delivery_attempt}/{queue_max_retries}, queue={source_queue})"
                )
                await asyncio.sleep(backoff)
                await message.nack(requeue=True)
                record_poison_message(taxonomy, "requeue_retry")
                logger.warning(
                    f"Message requeued for retry ({delivery_attempt}/{queue_max_retries}), "
                    f"reason={reason}, taxonomy={taxonomy}"
                )

        except asyncio.TimeoutError:
            # Handler timeout exceeded - this is the critical fix for semaphore deadlock
            logger.error(
                f"Handler TIMEOUT after {self._handler_timeout_seconds}s: "
                f"routing_key={message.routing_key}, message_id={message.message_id}"
            )
            taxonomy = "transient.handler_timeout"
            if delivery_attempt >= queue_max_retries:
                incident_id = await self._invoke_poison_runbook(
                    taxonomy="poison.retry_budget_exhausted",
                    reason="handler_timeout",
                    message=message,
                    delivery_attempt=delivery_attempt,
                )
                quarantine_payload = self._build_quarantine_payload(
                    message=message,
                    reason="handler_timeout",
                    taxonomy="poison.retry_budget_exhausted",
                    delivery_attempt=delivery_attempt,
                    incident_id=incident_id,
                )
                quarantined = await self._publish_quarantine_message(
                    payload=quarantine_payload,
                    correlation_id=message.correlation_id,
                )
                if quarantined:
                    await message.ack()
                    record_poison_message("poison.retry_budget_exhausted", "quarantined")
                else:
                    await message.nack(requeue=False)
                    record_poison_message("poison.retry_budget_exhausted", "dlq_fallback")
            else:
                backoff = self._compute_backoff(delivery_attempt)
                await asyncio.sleep(backoff)
                await message.nack(requeue=True)
                record_poison_message(taxonomy, "requeue_retry")
                logger.warning(
                    f"Message requeued due to timeout ({delivery_attempt}/{queue_max_retries}), "
                    f"routing_key={message.routing_key}"
                )

        except Exception as e:
            logger.exception(f"Unexpected error handling message: {e}")
            taxonomy = "transient.broker_handler_exception"
            if delivery_attempt >= queue_max_retries:
                incident_id = await self._invoke_poison_runbook(
                    taxonomy="poison.retry_budget_exhausted",
                    reason=f"handler_exception:{e}",
                    message=message,
                    delivery_attempt=delivery_attempt,
                )
                quarantine_payload = self._build_quarantine_payload(
                    message=message,
                    reason=f"handler_exception:{e}",
                    taxonomy="poison.retry_budget_exhausted",
                    delivery_attempt=delivery_attempt,
                    incident_id=incident_id,
                )
                quarantined = await self._publish_quarantine_message(
                    payload=quarantine_payload,
                    correlation_id=message.correlation_id,
                )
                if quarantined:
                    await message.ack()
                    record_poison_message("poison.retry_budget_exhausted", "quarantined")
                else:
                    await message.nack(requeue=False)
                    record_poison_message("poison.retry_budget_exhausted", "dlq_fallback")
            else:
                backoff = self._compute_backoff(delivery_attempt)
                await asyncio.sleep(backoff)
                await message.nack(requeue=True)
                record_poison_message(taxonomy, "requeue_retry")
        finally:
            clear_request_id()

    async def stop_consuming(self) -> None:
        """Stop consuming messages."""
        self._consuming = False

        # Cancel priority queue consumers
        for tag in self._priority_consumer_tags:
            try:
                for ch in self._priority_channels.values():
                    try:
                        await ch.cancel(tag)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Error cancelling priority consumer {tag}: {e}")
        self._priority_consumer_tags.clear()

        # Close priority channels
        for ch in self._priority_channels.values():
            try:
                await ch.close()
            except Exception:
                pass
        self._priority_channels.clear()

        logger.info("Stopped consuming messages")

    def is_connected(self) -> bool:
        """Check if connected to the broker."""
        return (
            self._connection is not None and
            not self._connection.is_closed and
            self._channel is not None
        )



