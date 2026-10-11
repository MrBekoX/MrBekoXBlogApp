"""Transport katmanı: RabbitMQ üzerinden backend (.NET) ile agent çekirdeği arasındaki taşıma.

Bu paket agent iş modellerinin (``agent_core``) DIŞINDADIR; yön tek yönlüdür
(messaging → agent_core izinli, tersi yasak — W0 Ç2). Broker envelope'u yalnız
burada bilinir; agent_core transport kavramı görmez.
"""

from .settings import BrokerSettings, from_env
from .topology import (
    BACKEND_EVENTS_QUEUE,
    COMMANDS_EXCHANGE,
    CONTENT_EXCHANGE,
    CONTENT_QUEUE,
    CONTROL_QUEUE,
    DEAD_EXCHANGE,
    DEFAULT_RETRY_TIER_SECONDS,
    EVENTS_EXCHANGE,
    EXECUTE_QUEUE,
    QueueSpec,
    Topology,
    build_topology,
    declare_topology,
    verify_topology,
)
from .errors import TopologyError
from .connection import broker_connection, connect_broker
from .publisher import BrokerPublisher, PublishResult
from .consumer import BrokerConsumer

__all__ = [
    "BrokerSettings",
    "from_env",
    "Topology",
    "QueueSpec",
    "build_topology",
    "declare_topology",
    "verify_topology",
    "TopologyError",
    "connect_broker",
    "broker_connection",
    "BrokerPublisher",
    "PublishResult",
    "BrokerConsumer",
    "COMMANDS_EXCHANGE",
    "EVENTS_EXCHANGE",
    "CONTENT_EXCHANGE",
    "DEAD_EXCHANGE",
    "EXECUTE_QUEUE",
    "CONTROL_QUEUE",
    "CONTENT_QUEUE",
    "BACKEND_EVENTS_QUEUE",
    "DEFAULT_RETRY_TIER_SECONDS",
]
