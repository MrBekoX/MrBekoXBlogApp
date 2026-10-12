"""Broker topology tanımı ve kurulum (B2).

Exchange/kuyruk adları: 3 ana exchange plan B2 bölümünden; 4 ana kuyruk ve
binding'ler planın topology diyagramından (satır 41-56) ve B1 yön/routing
tablosundan (satır 219-233) alınmıştır. ``content.project.changed.v1`` binding'i
B1 registry'sinde tanımlı olduğu için eklenmiştir; bağlı olmayan routing key
kuyruğa düşmez (unroutable) — B1 sözleşmesindeki türe teslim gerekir.

Sorumluluk (K3): üretimde tek declarer backend'dir. ``declare_topology`` yalnız
dev/test ve yönetimsel kurulum içindir; agent tarafı üretimde
``verify_topology`` ile pasif doğrular ve uyuşmazlıkta fail-fast eder.

DLQ: ana kuyruklar ``x-dead-letter-exchange=blog.agent.dead`` ile doğar;
``x-dead-letter-routing-key`` set edilmediği için orijinal routing key korunur
ve mesaj hedef DLQ'ya düşer. Retry kuyrukları TTL + DLX ile geri yönlendirir;
gecikme kademeleri (10s/30s/2dk) B7'nin değerlendirmesine öneri olarak
bildirilmiştir, kademeler argümanla değişirse kuyruk yeniden bildirilemez
(PRECONDITION_FAILED) — dev'de sil-bir-oluştur gerekir (raporda kayıtlı).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

from .errors import TopologyError

__all__ = [
    "COMMANDS_EXCHANGE",
    "EVENTS_EXCHANGE",
    "CONTENT_EXCHANGE",
    "DEAD_EXCHANGE",
    "EXECUTE_QUEUE",
    "CONTROL_QUEUE",
    "CONTENT_QUEUE",
    "BACKEND_EVENTS_QUEUE",
    "DEFAULT_RETRY_TIER_SECONDS",
    "Topology",
    "QueueSpec",
    "build_topology",
    "declare_topology",
    "verify_topology",
]

COMMANDS_EXCHANGE = "blog.agent.commands"
EVENTS_EXCHANGE = "blog.agent.events"
CONTENT_EXCHANGE = "blog.content.events"
DEAD_EXCHANGE = "blog.agent.dead"

EXECUTE_QUEUE = "agent.execute.q"
CONTROL_QUEUE = "agent.control.q"
CONTENT_QUEUE = "agent.content.q"
BACKEND_EVENTS_QUEUE = "backend.agent.events.q"

#: Hedefe özel retry kademeleri (saniye). B7 başlangıç önerisi: 10s/30s/2dk.
DEFAULT_RETRY_TIER_SECONDS: tuple[int, ...] = (10, 30, 120)

_TOPIC = aio_pika.ExchangeType.TOPIC

_BINDING_ARGS: dict[str, Any] | None = None


@dataclass(frozen=True)
class QueueSpec:
    """Durable kuyruk kaydı; arguments DLX/TTL gibi broker argümanlarını taşır."""

    name: str
    durable: bool = True
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Topology:
    """Idempotent declare için tam broker planı."""

    exchanges: tuple[str, ...]
    queues: tuple[QueueSpec, ...]
    bindings: tuple[tuple[str, str, str], ...]  # (kuyruk, exchange, routing_key)

    @property
    def queue_names(self) -> tuple[str, ...]:
        return tuple(q.name for q in self.queues)


def _dlq_for(queue: str) -> str:
    return f"{queue}.dlq"


def _target_retry_names(queue: str, tier: int) -> str:
    """Ana kuyruğu koruyan retry adı: agent.execute.q -> agent.execute.q.retry.10s.q.

    .NET AgentMessagingTopology.RetryQueueFor ile birebir aynı formül; ayna testi
    diller arası tutarlılığı sabitler.
    """
    return f"{queue}.retry.{tier}s.q"


def _origin_exchange(queue: str) -> str:
    if queue == BACKEND_EVENTS_QUEUE:
        return EVENTS_EXCHANGE
    if queue == CONTENT_QUEUE:
        return CONTENT_EXCHANGE
    return COMMANDS_EXCHANGE


def build_topology(
    retry_tier_seconds: tuple[int, ...] = DEFAULT_RETRY_TIER_SECONDS,
) -> Topology:
    """Plan diyagramındaki topology'yi parametrik üretir (retry kademeleri ayarlanabilir)."""

    target_rks: tuple[tuple[str, tuple[str, ...]], ...] = (
        (EXECUTE_QUEUE, ("agent.execute.requested.v1",)),
        (
            CONTROL_QUEUE,
            (
                "agent.cancel.requested.v1",
                "agent.resume.requested.v1",
                "agent.action.result.v1",
            ),
        ),
        (
            CONTENT_QUEUE,
            (
                "content.article.changed.v1",
                "content.sync.#",
                "content.profile.changed.v1",
                "content.project.changed.v1",
            ),
        ),
        (BACKEND_EVENTS_QUEUE, ("agent.run.#", "agent.action.#")),
    )

    exchanges = [
        COMMANDS_EXCHANGE,
        EVENTS_EXCHANGE,
        CONTENT_EXCHANGE,
        DEAD_EXCHANGE,
    ]
    queues: list[QueueSpec] = []
    bindings: list[tuple[str, str, str]] = []

    for queue, rks in target_rks:
        # Ana kuyruk: DLX'e bağlı; routing key korunur, hedef DLQ per-kuyruk.
        queues.append(
            QueueSpec(name=queue, arguments={"x-dead-letter-exchange": DEAD_EXCHANGE})
        )
        queues.append(QueueSpec(name=_dlq_for(queue)))
        for rk in rks:
            bindings.append((queue, _origin_exchange(queue), rk))
            bindings.append((_dlq_for(queue), DEAD_EXCHANGE, rk))

    for tier in retry_tier_seconds:
        retry_exchange = f"blog.agent.retry.{tier}s"
        exchanges.append(retry_exchange)
        for queue, rks in target_rks:
            tier_queue = _target_retry_names(queue, tier)
            # TTL dolunca mesaj orijinal exchange'e, korunan routing key ile döner.
            queues.append(
                QueueSpec(
                    name=tier_queue,
                    arguments={
                        "x-message-ttl": tier * 1000,
                        "x-dead-letter-exchange": _origin_exchange(queue),
                    },
                )
            )
            for rk in rks:
                bindings.append((tier_queue, retry_exchange, rk))

    return Topology(
        exchanges=tuple(exchanges),
        queues=tuple(queues),
        bindings=tuple(bindings),
    )


async def declare_topology(
    channel: AbstractChannel,
    topology: Topology | None = None,
) -> None:
    """Topology'yi idempotent declare eder (aynı argümanla tekrarı bozmaz).

    ÜRETİMDE KULLANMAYIN: tek declarer backend'dir (K3); bu işlev yalnız
    dev/test bootstrap ve yönetimsel kurulum içindir.
    """

    plan = topology or build_topology()
    for name in plan.exchanges:
        await channel.declare_exchange(name, type=_TOPIC, durable=True)
    queues = {
        spec.name: await channel.declare_queue(
            spec.name, durable=spec.durable, arguments=dict(spec.arguments)
        )
        for spec in plan.queues
    }
    for queue, exchange, rk in plan.bindings:
        await queues[queue].bind(exchange, rk)


async def verify_topology(
    connection: AbstractRobustConnection,
    topology: Topology | None = None,
    *,
    exchanges: tuple[str, ...] | None = None,
    queues: tuple[str, ...] | None = None,
) -> None:
    """Pasif doğrulama: beklenen her varlık passive declare ile kontrol edilir.

    Eksik/erişilemeyen varlıkta TopologyError ile fail-fast eder (K3: sessiz
    yeniden tanımlama yok). NOT_FOUND kontrolü kanalı kapattığından her varlık
    taze kanalla denetlenir.

    RabbitMQ 4.x'te pasif declare için kullanıcının hedef kaynağa en az bir
    izni gerekir (resmî access-control kuralı): bu yüzden rol bazlı kapsam
    parametreleri vardır. ``exchanges``/``queues`` None ise topology'deki tüm
    varlıklar denetlenir (backend/admin kapsamı); agent rolü yalnız kendi
    kuyrukları ve events exchange'iyle çağırır.
    """

    plan = topology or build_topology()
    names = exchanges if exchanges is not None else plan.exchanges
    missing: list[str] = []
    for name in names:
        channel = await connection.channel(publisher_confirms=False)
        try:
            await channel.declare_exchange(name, type=_TOPIC, durable=True, passive=True)
        except aio_pika.exceptions.ChannelNotFoundEntity:
            missing.append(f"exchange:{name}")
        finally:
            await channel.close()
    for queue_name in queues if queues is not None else plan.queue_names:
        channel = await connection.channel(publisher_confirms=False)
        try:
            await channel.declare_queue(queue_name, passive=True)
        except aio_pika.exceptions.ChannelNotFoundEntity:
            missing.append(f"queue:{queue_name}")
        finally:
            await channel.close()
    if missing:
        raise TopologyError(missing)
