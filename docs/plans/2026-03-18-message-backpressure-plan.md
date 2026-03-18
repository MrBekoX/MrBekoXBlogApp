# Mesaj Birikme Önleme — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tek AWS instance üzerinde çalışan AI Agent servisine priority queue, backpressure gateway ve graceful degradation ekleyerek mesaj birikme sorununu önlemek.

**Architecture:** Mevcut tek `q.ai.analysis` kuyruğu 3 öncelikli kuyruğa bölünür (chat / authoring / background). AI Agent tarafında PriorityScheduler ile chat her zaman önce işlenir. Backend tarafında kuyruk derinliği kontrolü ile backpressure uygulanır. Circuit breaker kuyruk bazlı farklı degradation stratejileri uygular.

**Tech Stack:** Python (aio_pika, asyncio, Redis), C# (.NET 9, RabbitMQ.Client, SignalR), RabbitMQ (quorum queues)

**Spec:** `docs/plans/2026-03-18-message-backpressure-design.md`

---

## Dosya Haritası

### AI Agent Service (Python)

| Dosya | İşlem | Sorumluluk |
|-------|-------|------------|
| `app/core/config.py` | Modify | Yeni kuyruk bazlı ayarlar ekle |
| `app/core/circuit_breaker.py` | Modify | Redis state sync + kuyruk bazlı degradation |
| `app/infrastructure/messaging/rabbitmq_adapter.py` | Modify | 3 kuyruk topolojisi + PriorityScheduler |
| `app/infrastructure/messaging/priority_scheduler.py` | Create | Weighted fair scheduling mekanizması |
| `app/infrastructure/messaging/queue_stats_publisher.py` | Create | Redis'e kuyruk derinliği yazar |
| `app/messaging/consumer.py` | Modify | Kuyruk kaynağı bilgisini process_message'a aktar |
| `app/domain/interfaces/i_message_broker.py` | Modify | Multi-queue consume desteği |

### Backend (.NET)

| Dosya | İşlem | Sorumluluk |
|-------|-------|------------|
| `BlogApp.BuildingBlocks.Messaging/Constants.cs` | Modify | Yeni kuyruk sabitleri ekle |
| `BlogApp.Server.Application/Common/Interfaces/Services/IQueueDepthService.cs` | Create | Kuyruk derinliği okuma interface'i |
| `BlogApp.Server.Infrastructure/Services/QueueDepthService.cs` | Create | Redis'ten kuyruk derinliği okur |
| `BlogApp.Server.Api/Extensions/MessagingExtensions.cs` | Modify | QueueDepthService kaydı |
| `BlogApp.Server.Api/Endpoints/AiEndpoints.cs` | Modify | Backpressure kontrolü ekle |
| `BlogApp.Server.Api/Endpoints/ChatEndpoints.cs` | Modify | Queue depth signaling |

### Frontend (Next.js)

| Dosya | İşlem | Sorumluluk |
|-------|-------|------------|
| `src/hooks/use-article-chat.ts` | Modify | 60s client-side timeout + queue depth mesajı |
| `src/hooks/use-authoring-ai-operations.ts` | Modify | Backpressure uyarısı göster |

---

## Task 1: Yeni Config Ayarları (Python)

**Files:**
- Modify: `src/services/ai-agent-service/app/core/config.py:138-155`

- [ ] **Step 1: Yeni kuyruk ayarlarını config'e ekle**

`config.py` dosyasında `broker_backlog_warn_threshold` field'ından sonra (satır 155 civarı) ekle:

```python
    # Priority Queue Configuration
    queue_chat_name: str = Field(
        default="q.chat.requests",
        description="High-priority chat queue name"
    )
    queue_authoring_name: str = Field(
        default="q.ai.authoring",
        description="Medium-priority authoring queue name"
    )
    queue_background_name: str = Field(
        default="q.ai.background",
        description="Low-priority background queue name"
    )
    queue_chat_ttl_ms: int = Field(
        default=60000,
        ge=10000,
        le=300000,
        description="Chat queue message TTL in milliseconds"
    )
    queue_authoring_ttl_ms: int = Field(
        default=300000,
        ge=30000,
        le=600000,
        description="Authoring queue message TTL in milliseconds"
    )
    queue_background_ttl_ms: int = Field(
        default=1800000,
        ge=60000,
        le=3600000,
        description="Background queue message TTL in milliseconds"
    )
    queue_chat_prefetch: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Chat queue prefetch count"
    )
    queue_authoring_prefetch: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Authoring queue prefetch count"
    )
    queue_background_prefetch: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Background queue prefetch count"
    )
    scheduler_total_slots: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Total concurrent processing slots"
    )
    scheduler_chat_slots: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Dedicated chat processing slots"
    )
    scheduler_low_priority_slots: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Shared slot for authoring + background"
    )
    chat_max_retries: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max retry attempts for chat messages"
    )
    authoring_max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max retry attempts for authoring messages"
    )
    background_max_retries: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Max retry attempts for background messages"
    )
    retry_budget_max_inflight: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max concurrent retry messages across all queues"
    )
    retry_backoff_base_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=10.0,
        description="Base delay for retry exponential backoff"
    )
    retry_backoff_max_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Max delay cap for retry backoff"
    )
    queue_stats_redis_ttl_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="TTL for queue stats published to Redis"
    )
    circuit_breaker_failure_threshold: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Failures before circuit opens (out of last 5 requests)"
    )
    circuit_breaker_recovery_timeout: int = Field(
        default=30,
        ge=10,
        le=120,
        description="Seconds before circuit transitions to half-open"
    )
    chat_fallback_message: str = Field(
        default="AI asistanı şu an yoğun, lütfen biraz sonra tekrar deneyin.",
        description="Fallback message when circuit is open for chat"
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/services/ai-agent-service/app/core/config.py
git commit -m "feat(ai-agent): add priority queue configuration settings"
```

---

## Task 2: PriorityScheduler (Python — Yeni Dosya)

**Files:**
- Create: `src/services/ai-agent-service/app/infrastructure/messaging/priority_scheduler.py`

- [ ] **Step 1: PriorityScheduler'ı oluştur**

```python
"""Priority-based scheduling for multi-queue consumption.

Uses a dual-semaphore design:
- global_semaphore: limits total concurrent Ollama requests
- chat_semaphore: reserves dedicated slots for chat
- low_semaphore: shared slot for authoring + background
"""

import asyncio
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class QueuePriority(str, Enum):
    CHAT = "chat"
    AUTHORING = "authoring"
    BACKGROUND = "background"


class PriorityScheduler:
    """Weighted fair scheduler for multi-queue RabbitMQ consumption.

    Slot allocation:
    - Chat messages try chat_semaphore first, then low_semaphore (always prioritized)
    - Authoring/background messages only use low_semaphore
    - global_semaphore caps total in-flight work
    """

    SLOT_CHAT = "chat"
    SLOT_LOW = "low"

    def __init__(
        self,
        total_slots: int = 3,
        chat_slots: int = 2,
        low_priority_slots: int = 1,
    ):
        self._global_semaphore = asyncio.Semaphore(total_slots)
        self._chat_semaphore = asyncio.Semaphore(chat_slots)
        self._low_semaphore = asyncio.Semaphore(low_priority_slots)
        self._total_slots = total_slots
        self._chat_slots = chat_slots
        self._low_slots = low_priority_slots

    async def acquire(self, priority: QueuePriority) -> str:
        """Acquire a processing slot. Blocks until available.

        Chat can overflow into low_semaphore when chat_semaphore is full.
        Returns slot type string (SLOT_CHAT or SLOT_LOW) for correct release.
        """
        await self._global_semaphore.acquire()

        if priority == QueuePriority.CHAT:
            # Try chat slot first — locked() returns True when value==0
            # No TOCTOU risk: single-threaded asyncio, no await between check and acquire
            if not self._chat_semaphore.locked():
                await self._chat_semaphore.acquire()
                return self.SLOT_CHAT
            # Overflow: use low slot (blocking)
            await self._low_semaphore.acquire()
            return self.SLOT_LOW

        # Authoring and background use low slot only
        await self._low_semaphore.acquire()
        return self.SLOT_LOW

    def release(self, slot_type: str) -> None:
        """Release the processing slot using the token returned by acquire()."""
        if slot_type == self.SLOT_CHAT:
            self._chat_semaphore.release()
        else:
            self._low_semaphore.release()

        self._global_semaphore.release()

    @property
    def available_slots(self) -> int:
        return self._global_semaphore._value

    @property
    def stats(self) -> dict:
        return {
            "total_slots": self._total_slots,
            "available_global": self._global_semaphore._value,
            "available_chat": self._chat_semaphore._value,
            "available_low": self._low_semaphore._value,
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/services/ai-agent-service/app/infrastructure/messaging/priority_scheduler.py
git commit -m "feat(ai-agent): add PriorityScheduler with dual-semaphore design"
```

---

## Task 3: Queue Stats Redis Publisher (Python — Yeni Dosya)

**Files:**
- Create: `src/services/ai-agent-service/app/infrastructure/messaging/queue_stats_publisher.py`

- [ ] **Step 1: QueueStatsPublisher'ı oluştur**

```python
"""Publishes queue depth and circuit breaker state to Redis.

Backend reads these keys to make backpressure decisions.
Frontend receives them via SignalR for queue depth signaling.
"""

import json
import logging
from datetime import datetime, timezone

from app.domain.interfaces.i_cache import ICache

logger = logging.getLogger(__name__)

# Redis key constants
QUEUE_STATS_PREFIX = "queue:stats"
CIRCUIT_STATE_KEY = f"{QUEUE_STATS_PREFIX}:ollama:circuit_state"
RETRY_INFLIGHT_KEY = "retry:inflight:count"


class QueueStatsPublisher:
    """Writes queue depth statistics to Redis for cross-service visibility."""

    def __init__(self, cache: ICache, ttl_seconds: int = 30):
        self._cache = cache
        self._ttl = ttl_seconds

    async def publish_queue_depth(
        self, queue_name: str, depth: int, consumer_count: int | None = None
    ) -> None:
        """Write queue depth for a specific queue to Redis."""
        key = f"{QUEUE_STATS_PREFIX}:{queue_name}"
        value = {
            "depth": depth,
            "consumer_count": consumer_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._cache.set_json(key, value, ttl_seconds=self._ttl)
        except Exception as e:
            logger.warning(f"Failed to publish queue stats for {queue_name}: {e}")

    async def publish_circuit_state(self, state: str) -> None:
        """Write Ollama circuit breaker state to Redis."""
        try:
            await self._cache.set_json(
                CIRCUIT_STATE_KEY,
                {"state": state, "updated_at": datetime.now(timezone.utc).isoformat()},
                ttl_seconds=self._ttl,
            )
        except Exception as e:
            logger.warning(f"Failed to publish circuit state: {e}")

    async def get_retry_inflight_count(self) -> int:
        """Get current retry inflight count from Redis."""
        try:
            val = await self._cache.get_json(RETRY_INFLIGHT_KEY)
            return int(val.get("count", 0)) if val else 0
        except Exception:
            return 0

    async def increment_retry_inflight(self) -> int:
        """Atomically increment retry inflight counter. Returns new value."""
        try:
            rc = self._cache.client  # RedisAdapter.client property (raises if not connected)
            new_val = await rc.incr(RETRY_INFLIGHT_KEY)
            await rc.expire(RETRY_INFLIGHT_KEY, 300)  # 5 min TTL safety
            return int(new_val)
        except Exception as e:
            logger.warning(f"Failed to increment retry inflight: {e}")
            return 0

    async def decrement_retry_inflight(self) -> None:
        """Atomically decrement retry inflight counter."""
        try:
            rc = self._cache.client
            val = await rc.decr(RETRY_INFLIGHT_KEY)
            if val < 0:
                await rc.set(RETRY_INFLIGHT_KEY, 0, ex=300)
        except Exception as e:
            logger.warning(f"Failed to decrement retry inflight: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add src/services/ai-agent-service/app/infrastructure/messaging/queue_stats_publisher.py
git commit -m "feat(ai-agent): add QueueStatsPublisher for Redis-based queue depth signaling"
```

---

## Task 4: Circuit Breaker Redis Sync + Kuyruk Bazlı Degradation (Python)

**Files:**
- Modify: `src/services/ai-agent-service/app/core/circuit_breaker.py`

- [ ] **Step 1: CircuitBreaker'ı Redis sync ve kuyruk degradation ile genişlet**

Mevcut `CircuitBreaker` sınıfını koru, yeni `QueueAwareCircuitBreaker` sınıfı ekle (dosyanın sonuna):

```python
class QueueAwareCircuitBreaker(CircuitBreaker):
    """Circuit breaker that publishes state to Redis and provides
    queue-specific degradation strategies.

    Delegates state machine logic to parent CircuitBreaker.
    Adds Redis sync and per-queue behavior on top.
    """

    def __init__(
        self,
        stats_publisher=None,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
        chat_fallback_message: str = "AI asistanı şu an yoğun, lütfen biraz sonra tekrar deneyin.",
    ):
        super().__init__(failure_threshold, recovery_timeout)
        self._stats_publisher = stats_publisher
        self._chat_fallback_message = chat_fallback_message

    async def record_success_async(self):
        """Record success and sync state to Redis."""
        self.record_success()
        await self._publish_state()

    async def record_failure_async(self):
        """Record failure and sync state to Redis."""
        self.record_failure()
        await self._publish_state()

    async def _publish_state(self):
        """Publish current circuit state to Redis."""
        if self._stats_publisher:
            try:
                await self._stats_publisher.publish_circuit_state(self._state.value.lower())
            except Exception as e:
                logger.warning(f"Failed to publish circuit state to Redis: {e}")

    def get_degradation_action(self, queue_priority: str) -> str:
        """Return action for given queue when circuit is open.

        Returns: 'fallback' | 'requeue' | 'requeue'
        """
        if self._state != CircuitState.OPEN:
            return "proceed"

        if queue_priority == "chat":
            return "fallback"
        # authoring and background: requeue
        return "requeue"

    @property
    def chat_fallback_message(self) -> str:
        return self._chat_fallback_message
```

- [ ] **Step 2: Commit**

```bash
git add src/services/ai-agent-service/app/core/circuit_breaker.py
git commit -m "feat(ai-agent): add QueueAwareCircuitBreaker with Redis sync and per-queue degradation"
```

---

## Task 5: RabbitMQ Adapter — 3 Kuyruk Topolojisi (Python)

**Files:**
- Modify: `src/services/ai-agent-service/app/infrastructure/messaging/rabbitmq_adapter.py:31-58,130-185,341-429`
- Modify: `src/services/ai-agent-service/app/domain/interfaces/i_message_broker.py`

Bu en büyük task. Adapter'ı 3 kuyruğu dinleyecek şekilde güncelle.

- [ ] **Step 1: IMessageBroker interface'ine multi-queue desteği ekle**

`i_message_broker.py` dosyasına yeni method ekle (dosyanın sonuna, `is_connected` altına):

```python
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
```

- [ ] **Step 2: Adapter sabitlerini güncelle**

`rabbitmq_adapter.py` dosyasında satır 31-58 arasındaki sabitleri güncelle:

```python
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
    "ai.analysis.requested",      # legacy routing key, kept for backward compat
    "ai.summarize.requested",
    "ai.keywords.requested",
    "ai.sentiment.requested",
    "ai.reading-time.requested",   # senkron işlem ama kuyruktan da gelebilir (eski publisher'lar)
    "ai.geo-optimize.requested",
    "ai.collect-sources.requested",
]

# Combined for backward compat
ROUTING_KEYS = ROUTING_KEYS_CHAT + ROUTING_KEYS_AUTHORING + ROUTING_KEYS_BACKGROUND
```

- [ ] **Step 3: `_declare_topology()` metodunu 3 kuyruk için güncelle**

Mevcut `_declare_topology` (satır 130-185) metodunu güncelle. Eski `q.ai.analysis` binding'lerini koru (migration), yeni 3 kuyruğu ekle:

```python
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

        # ── Priority queues with per-queue TTL and DLQ ──
        queue_configs = [
            (QUEUE_CHAT, DLQ_CHAT, ROUTING_KEYS_CHAT, settings.queue_chat_ttl_ms),
            (QUEUE_AUTHORING, DLQ_AUTHORING, ROUTING_KEYS_AUTHORING, settings.queue_authoring_ttl_ms),
            (QUEUE_BACKGROUND, DLQ_BACKGROUND, ROUTING_KEYS_BACKGROUND, settings.queue_background_ttl_ms),
        ]

        self._priority_queues: dict[str, AbstractQueue] = {}

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

        # Legacy queue (migration: keep consuming until drained)
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
        # Legacy bindings removed — new messages go to priority queues
        # Old bindings in RabbitMQ will remain until manually unbound

        logger.info(
            f"Declared priority topology: "
            f"{QUEUE_CHAT}, {QUEUE_AUTHORING}, {QUEUE_BACKGROUND} "
            f"+ legacy {LEGACY_QUEUE_NAME}"
        )
```

- [ ] **Step 4: `start_consuming_multi()` metodu ekle**

`start_consuming` metodundan sonra (satır ~397 civarı) yeni metod ekle:

```python
    async def start_consuming_multi(
        self,
        handlers: dict[str, MessageHandler],
    ) -> None:
        """Start consuming from multiple priority queues.

        Args:
            handlers: Dict mapping queue_name -> handler function.
                     Each handler receives (body: bytes) and returns (success, reason).
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

        self._priority_channels: dict[str, AbstractChannel] = {}
        self._priority_consumer_tags: list[str] = []

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
        while self._consuming:
            await asyncio.sleep(0.5)

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
        """Callback for priority queue messages. Injects queue_name into message headers."""
        if not self._consuming:
            await message.nack(requeue=True)
            return

        # Tag message with source queue for downstream priority decisions
        if message.headers is None:
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
```

- [ ] **Step 5: `refresh_queue_stats()` metodunu 3 kuyruk için güncelle**

Mevcut `refresh_queue_stats` (satır 664 civarı) metodunu güncelle — her 3 kuyruk için stats topla:

```python
    async def refresh_queue_stats(self) -> dict[str, Any]:
        """Refresh cached stats for all priority queues."""
        all_stats = {}

        # Priority queues
        for queue_name in [QUEUE_CHAT, QUEUE_AUTHORING, QUEUE_BACKGROUND]:
            stats = await self._refresh_single_queue_stats(queue_name)
            all_stats[queue_name] = stats

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
```

- [ ] **Step 6: `_build_quarantine_payload` metodunda `sourceQueue` düzelt**

`_build_quarantine_payload` (satır 589) metodunda `sourceQueue` değerini `x-source-queue` header'ından al:

```python
    def _build_quarantine_payload(
        self,
        message: aio_pika.IncomingMessage,
        reason: str,
        taxonomy: str,
        delivery_attempt: int,
        incident_id: str | None = None,
    ) -> dict[str, Any]:
        headers = message.headers or {}
        source_queue = headers.get("x-source-queue", LEGACY_QUEUE_NAME)
        # ... rest aynı, sadece "sourceQueue": source_queue olarak değiştir
```

- [ ] **Step 7: Commit**

```bash
git add src/services/ai-agent-service/app/infrastructure/messaging/rabbitmq_adapter.py
git add src/services/ai-agent-service/app/domain/interfaces/i_message_broker.py
git commit -m "feat(ai-agent): implement 3-queue topology with priority consumption"
```

---

## Task 6: Consumer'da Kuyruk Bazlı Retry + Circuit Breaker Entegrasyonu (Python)

**Files:**
- Modify: `src/services/ai-agent-service/app/messaging/consumer.py`
- Modify: `src/services/ai-agent-service/app/infrastructure/messaging/rabbitmq_adapter.py:946-1098` (`_handle_message`)

- [ ] **Step 1: Consumer'a kuyruk kaynağı bilgisini aktar**

`consumer.py` dosyasında `process_message` metoduna (satır 711) `source_queue` parametresi ekle:

```python
    async def process_message(self, body: bytes, source_queue: str = "") -> tuple[bool, str]:
```

Bu parametre `_handle_message` içinden iletilecek.

- [ ] **Step 2: `_handle_message` içinde kuyruk bazlı retry limiti ve circuit breaker**

`rabbitmq_adapter.py` dosyasının `_handle_message` metodunda (satır 946 civarı), `source_queue` header'ını okuyup retry limitini ve circuit breaker davranışını belirle:

```python
    # _handle_message içinde, handler çağrısından önce:
    headers = message.headers or {}
    source_queue = headers.get("x-source-queue", LEGACY_QUEUE_NAME)

    # Kuyruk bazlı max retry
    max_retries_map = {
        QUEUE_CHAT: settings.chat_max_retries,
        QUEUE_AUTHORING: settings.authoring_max_retries,
        QUEUE_BACKGROUND: settings.background_max_retries,
    }
    queue_max_retries = max_retries_map.get(source_queue, self._max_retries)
```

- [ ] **Step 3: Retry backoff'u güncelle**

Handler `False` döndüğünde ve retry hakkı varsa, exponential backoff uygula:

```python
    # Mevcut retry logic yerine:
    if delivery_attempt < queue_max_retries:
        backoff = min(
            settings.retry_backoff_base_seconds * (4 ** (delivery_attempt - 1)),
            settings.retry_backoff_max_seconds,
        )
        logger.info(
            f"Retry backoff: {backoff:.1f}s for {message.message_id} "
            f"(attempt {delivery_attempt}/{queue_max_retries}, queue={source_queue})"
        )
        await asyncio.sleep(backoff)
        await message.nack(requeue=True)
        return
```

- [ ] **Step 4: Commit**

```bash
git add src/services/ai-agent-service/app/messaging/consumer.py
git add src/services/ai-agent-service/app/infrastructure/messaging/rabbitmq_adapter.py
git commit -m "feat(ai-agent): add per-queue retry limits and exponential backoff"
```

---

## Task 7: DI Container + Lifecycle Güncelle (Python)

**Files:**
- Modify: `src/services/ai-agent-service/app/container.py`
- Modify: `src/services/ai-agent-service/app/api/routes.py` (lifespan)

- [ ] **Step 1: Container'a yeni provider'lar ekle**

`container.py` dosyasına `QueueStatsPublisher`, `PriorityScheduler`, `QueueAwareCircuitBreaker` provider'ları ekle:

```python
    # ── Priority Queue Infrastructure ───────────────────────────────────
    priority_scheduler = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.messaging.priority_scheduler",
            fromlist=["PriorityScheduler"],
        ).PriorityScheduler(
            total_slots=get_settings().scheduler_total_slots,
            chat_slots=get_settings().scheduler_chat_slots,
            low_priority_slots=get_settings().scheduler_low_priority_slots,
        )
    )

    queue_stats_publisher = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.messaging.queue_stats_publisher",
            fromlist=["QueueStatsPublisher"],
        ).QueueStatsPublisher(
            cache=ApplicationContainer.redis_adapter(),  # RedisAdapter (ICache + .client property)
            ttl_seconds=get_settings().queue_stats_redis_ttl_seconds,
        )
    )

    queue_aware_circuit_breaker = providers.Singleton(
        lambda: __import__(
            "app.core.circuit_breaker",
            fromlist=["QueueAwareCircuitBreaker"],
        ).QueueAwareCircuitBreaker(
            stats_publisher=ApplicationContainer.queue_stats_publisher(),
            failure_threshold=get_settings().circuit_breaker_failure_threshold,
            recovery_timeout=get_settings().circuit_breaker_recovery_timeout,
            chat_fallback_message=get_settings().chat_fallback_message,
        )
    )
```

- [ ] **Step 2: Lifespan'da `start_consuming_multi` kullan**

`routes.py` lifespan fonksiyonunda `_start_consumer()` (satır 219-227) ve `_consumer_handler` (satır 180-203) güncellenir. Kill switch, standby, admin processor mantığı korunur:

```python
    # routes.py — _start_consumer() içinde (satır 224):
    # Eski:
    # _consumer_task = asyncio.create_task(broker.start_consuming(_consumer_handler))

    # Yeni:
    from app.infrastructure.messaging.rabbitmq_adapter import (
        QUEUE_CHAT, QUEUE_AUTHORING, QUEUE_BACKGROUND,
    )
    _consumer_task = asyncio.create_task(broker.start_consuming_multi({
        QUEUE_CHAT: _consumer_handler,
        QUEUE_AUTHORING: _consumer_handler,
        QUEUE_BACKGROUND: _consumer_handler,
    }))
```

**Not:** `_consumer_handler` fonksiyonu (satır 180-203) değişmez — kill switch kontrolü, trace_span wrapping, idle activity kaydı aynı kalır. Her 3 kuyruk aynı handler'ı kullanır çünkü `process_message` zaten event_type'a göre routing yapar. Kuyruk kaynağı bilgisi `x-source-queue` header'ından gelir (Task 5'te eklendi).

`_stop_consumer_for_standby()` (satır 229-243) de aynı kalır — `broker.stop_consuming()` tüm kuyruk consumer'larını durdurur. `_resume_consumer_from_standby()` yeniden `start_consuming_multi` çağırır.

Admin processor consumer'ı ayrı kalır (admin kuyruğu bu değişiklikten etkilenmez).

- [ ] **Step 3: Commit**

```bash
git add src/services/ai-agent-service/app/container.py
git add src/services/ai-agent-service/app/api/routes.py
git commit -m "feat(ai-agent): wire PriorityScheduler and multi-queue consumption in DI container"
```

---

## Task 8: Backend — Yeni Queue Sabitleri ve QueueDepthService (C#)

**Files:**
- Modify: `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Messaging/Constants.cs:111-147`
- Create: `src/BlogApp.Server/BlogApp.Server.Application/Common/Interfaces/Services/IQueueDepthService.cs`
- Create: `src/BlogApp.Server/BlogApp.Server.Infrastructure/Services/QueueDepthService.cs`
- Modify: `src/BlogApp.Server/BlogApp.Server.Infrastructure/DependencyInjection.cs`

- [ ] **Step 1: Constants.cs'e yeni kuyruk sabitleri ekle**

`QueueNames` sınıfına ekle:

```csharp
        /// <summary>
        /// AI Agent consumes authoring generation requests (medium priority)
        /// </summary>
        public const string AiAuthoring = "q.ai.authoring";

        /// <summary>
        /// AI Agent consumes background analysis requests (low priority)
        /// </summary>
        public const string AiBackground = "q.ai.background";
```

- [ ] **Step 2: IQueueDepthService interface'i oluştur**

```csharp
namespace BlogApp.Server.Application.Common.Interfaces.Services;

public record QueueDepthInfo(int Depth, string? UpdatedAt, bool IsStale);

public interface IQueueDepthService
{
    Task<QueueDepthInfo> GetQueueDepthAsync(string queueName, CancellationToken ct = default);
    Task<string> GetCircuitStateAsync(CancellationToken ct = default);
}
```

- [ ] **Step 3: QueueDepthService implementasyonu oluştur**

```csharp
using System.Text.Json;
using BlogApp.Server.Application.Common.Interfaces.Services;
using Microsoft.Extensions.Logging;
using StackExchange.Redis;

namespace BlogApp.Server.Infrastructure.Services;

public class QueueDepthService : IQueueDepthService
{
    private const string QueueStatsPrefix = "queue:stats";
    private const string CircuitStateKey = "queue:stats:ollama:circuit_state";
    private const int StalenessThresholdSeconds = 60;

    private readonly IConnectionMultiplexer? _redis;
    private readonly ILogger<QueueDepthService> _logger;

    public QueueDepthService(IConnectionMultiplexer? redis, ILogger<QueueDepthService> logger)
    {
        _redis = redis;
        _logger = logger;
    }

    public async Task<QueueDepthInfo> GetQueueDepthAsync(string queueName, CancellationToken ct = default)
    {
        if (_redis is null)
            return new QueueDepthInfo(0, null, true);

        try
        {
            var db = _redis.GetDatabase();
            var value = await db.StringGetAsync($"{QueueStatsPrefix}:{queueName}");
            if (value.IsNullOrEmpty)
                return new QueueDepthInfo(0, null, true);

            var doc = JsonDocument.Parse(value.ToString());
            var depth = doc.RootElement.GetProperty("depth").GetInt32();
            var updatedAt = doc.RootElement.TryGetProperty("updated_at", out var ua) ? ua.GetString() : null;

            var isStale = updatedAt is null ||
                (DateTime.UtcNow - DateTime.Parse(updatedAt)).TotalSeconds > StalenessThresholdSeconds;

            return new QueueDepthInfo(depth, updatedAt, isStale);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to read queue depth for {QueueName}", queueName);
            return new QueueDepthInfo(0, null, true);
        }
    }

    public async Task<string> GetCircuitStateAsync(CancellationToken ct = default)
    {
        if (_redis is null)
            return "unknown";

        try
        {
            var db = _redis.GetDatabase();
            var value = await db.StringGetAsync(CircuitStateKey);
            if (value.IsNullOrEmpty)
                return "unknown";

            var doc = JsonDocument.Parse(value.ToString());
            return doc.RootElement.GetProperty("state").GetString() ?? "unknown";
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to read circuit state");
            return "unknown";
        }
    }
}
```

- [ ] **Step 4: DI kaydı**

`DependencyInjection.cs` dosyasına ekle (nullable IConnectionMultiplexer ile uyumlu factory):

```csharp
services.AddSingleton<IQueueDepthService>(sp => new QueueDepthService(
    sp.GetService<IConnectionMultiplexer>(),
    sp.GetRequiredService<ILogger<QueueDepthService>>()));
```

- [ ] **Step 5: Commit**

```bash
git add src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Messaging/Constants.cs
git add src/BlogApp.Server/BlogApp.Server.Application/Common/Interfaces/Services/IQueueDepthService.cs
git add src/BlogApp.Server/BlogApp.Server.Infrastructure/Services/QueueDepthService.cs
git add src/BlogApp.Server/BlogApp.Server.Infrastructure/DependencyInjection.cs
git commit -m "feat(backend): add IQueueDepthService and priority queue constants"
```

---

## Task 9: Backend — Backpressure Kontrolü Endpoint'lerde (C#)

**Files:**
- Modify: `src/BlogApp.Server/BlogApp.Server.Api/Endpoints/AiEndpoints.cs`
- Modify: `src/BlogApp.Server/BlogApp.Server.Api/Endpoints/ChatEndpoints.cs`
- Modify: `src/BlogApp.Server/BlogApp.Server.Api/Endpoints/PostsEndpoints.cs`

- [ ] **Step 1: AiEndpoints'te backpressure kontrolü ekle**

Authoring endpointlerinde (title, excerpt, tags, seo, content improvement) publish öncesi:

```csharp
var depthInfo = await queueDepthService.GetQueueDepthAsync(
    MessagingConstants.QueueNames.AiAuthoring, ct);

// Kuyruk derinliği > 10 ise uyarı flag'i ekle
var isBackpressured = depthInfo.Depth > 10;
```

Response'a `isBackpressured` flag'i ekle. Mesajı yine publish et.

- [ ] **Step 2: PostsEndpoints'te background backpressure kontrolü ekle**

Publish/create post sonrası background analiz tetiklenirken:

```csharp
var bgDepth = await queueDepthService.GetQueueDepthAsync(
    MessagingConstants.QueueNames.AiBackground, ct);

if (bgDepth.Depth > 20 && !bgDepth.IsStale)
{
    logger.LogInformation("Background queue depth {Depth} exceeds threshold, skipping analysis", bgDepth.Depth);
    // Mesajı publish etme, sessizce atla
    return;
}
// Normal publish devam
```

- [ ] **Step 3: ChatEndpoints'te circuit state kontrolü ekle**

Chat isteği gönderilirken:

```csharp
var circuitState = await queueDepthService.GetCircuitStateAsync(ct);
var chatDepth = await queueDepthService.GetQueueDepthAsync(
    MessagingConstants.QueueNames.ChatRequests, ct);
```

Response'a `estimatedWaitSeconds` ve `circuitState` ekle.

- [ ] **Step 4: Commit**

```bash
git add src/BlogApp.Server/BlogApp.Server.Api/Endpoints/AiEndpoints.cs
git add src/BlogApp.Server/BlogApp.Server.Api/Endpoints/ChatEndpoints.cs
git add src/BlogApp.Server/BlogApp.Server.Api/Endpoints/PostsEndpoints.cs
git commit -m "feat(backend): add backpressure checks in AI and chat endpoints"
```

---

## Task 10: Frontend — Client-Side Timeout + Queue Depth Mesajları

**Files:**
- Modify: `src/blogapp-web/src/hooks/use-article-chat.ts`
- Modify: `src/blogapp-web/src/hooks/use-authoring-ai-operations.ts`

- [ ] **Step 1: Chat hook'a 60s client-side timeout ekle**

`use-article-chat.ts` dosyasında chat mesajı gönderildikten sonra 60s timeout:

```typescript
// Chat isteği gönderildikten sonra
const CHAT_TIMEOUT_MS = 60_000;

const timeoutId = setTimeout(() => {
  // 60s içinde yanıt gelmediyse
  addMessage({
    role: 'assistant',
    content: 'Yanıt alınamadı, lütfen tekrar deneyin.',
  });
  setIsLoading(false);
}, CHAT_TIMEOUT_MS);

// Yanıt geldiğinde timeout'u temizle
clearTimeout(timeoutId);
```

- [ ] **Step 2: Chat response'taki backpressure bilgisini göster**

API response'ında `estimatedWaitSeconds` veya `circuitState` varsa kullanıcıya göster:

```typescript
if (response.circuitState === 'open') {
  addMessage({
    role: 'system',
    content: 'AI asistanı şu an kullanılamıyor, lütfen daha sonra tekrar deneyin.',
  });
  return;
}
```

- [ ] **Step 3: Authoring hook'ta backpressure uyarısı**

`use-authoring-ai-operations.ts` dosyasında response'taki `isBackpressured` flag'ini kontrol et:

```typescript
if (response.isBackpressured) {
  toast.warning('AI şu an yoğun, işlem biraz bekleyebilir.');
}
```

- [ ] **Step 4: Commit**

```bash
git add src/blogapp-web/src/hooks/use-article-chat.ts
git add src/blogapp-web/src/hooks/use-authoring-ai-operations.ts
git commit -m "feat(frontend): add chat timeout, backpressure warnings, and circuit state handling"
```

---

## Task 11: Queue Stats Refresh Loop + Redis Publish Entegrasyonu (Python)

**Files:**
- Modify: `src/services/ai-agent-service/app/infrastructure/messaging/rabbitmq_adapter.py`

- [ ] **Step 1: `refresh_queue_stats` sonrası Redis'e yaz**

`refresh_queue_stats` metodunun sonunda `QueueStatsPublisher`'ı çağır:

```python
    async def refresh_queue_stats(self) -> dict[str, Any]:
        all_stats = {}
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
        # ... rest of method
```

`RabbitMQAdapter.__init__`'e `stats_publisher` parametresi ekle:

```python
    def __init__(self, rabbitmq_url: str | None = None, stats_publisher=None):
        # ... mevcut init kodu ...
        self._stats_publisher = stats_publisher
```

`container.py` dosyasında `message_broker` provider'ını güncelle:

```python
    message_broker = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.messaging.rabbitmq_adapter", fromlist=["RabbitMQAdapter"]
        ).RabbitMQAdapter(
            stats_publisher=ApplicationContainer.queue_stats_publisher(),
        )
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/services/ai-agent-service/app/infrastructure/messaging/rabbitmq_adapter.py
git add src/services/ai-agent-service/app/container.py
git commit -m "feat(ai-agent): wire QueueStatsPublisher into RabbitMQAdapter and publish stats to Redis"
```

---

## Task 12: Dokümantasyon

**Files:**
- Create: `docs/message-backpressure-architecture.md`

- [ ] **Step 1: Mimari dokümanı yaz**

Yapılan tüm değişiklikleri, yeni topolojiyi, konfigürasyon parametrelerini ve operasyonel bilgileri dokümante et. İçerik:
- Yeni RabbitMQ topoloji diyagramı
- Kuyruk özellikleri tablosu (TTL, prefetch, max retry)
- PriorityScheduler çalışma mantığı
- Backpressure gateway kuralları
- Circuit breaker durumları ve kuyruk bazlı davranışlar
- Redis key'leri
- Konfigürasyon parametreleri (.env)
- Migration planı
- Troubleshooting (kuyruk birikirse ne yapılır)

- [ ] **Step 2: Commit**

```bash
git add docs/message-backpressure-architecture.md
git commit -m "docs: add message backpressure architecture documentation"
```
