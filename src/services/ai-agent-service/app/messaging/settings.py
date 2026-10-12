"""Broker bağlantı ayarları (B2). Geliştirme/üretim ayrımı vhost ile yapılır
(plan satır 253: "ortam ön eki veya ayrı vhost"); dev değerleri ortam
değişkenlerinde düz metin kalabilir, üretim değerleri env ile verilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

__all__ = ["BrokerSettings"]


@dataclass(frozen=True)
class BrokerSettings:
    """aio-pika bağlantı ve tüketim parametreleri."""

    host: str = "127.0.0.1"
    port: int = 5672
    username: str = "agent_svc"
    password: str = "agent_svc_dev"
    virtualhost: str = "blogapp_dev"
    client_name: str = "agent-py"
    heartbeat_seconds: int = 30
    reconnect_interval_seconds: float = 5.0
    connection_timeout_seconds: float = 10.0
    prefetch_count: int = 16

    @property
    def amqp_url(self) -> str:
        vhost = quote(self.virtualhost, safe="")
        password = quote(self.password, safe="")
        return (
            f"amqp://{quote(self.username, safe='')}:{password}"
            f"@{self.host}:{self.port}/{vhost}"
        )


def from_env(environ: dict[str, str] | None = None) -> BrokerSettings:
    env = os.environ if environ is None else environ

    def _int(name: str, default: int) -> int:
        raw = env.get(name)
        return int(raw) if raw else default

    def _float(name: str, default: float) -> float:
        raw = env.get(name)
        return float(raw) if raw else default

    return BrokerSettings(
        host=env.get("AGENT_BROKER_HOST", "127.0.0.1"),
        port=_int("AGENT_BROKER_PORT", 5672),
        username=env.get("AGENT_BROKER_USERNAME", "agent_svc"),
        password=env.get("AGENT_BROKER_PASSWORD", "agent_svc_dev"),
        virtualhost=env.get("AGENT_BROKER_VHOST", "blogapp_dev"),
        client_name=env.get("AGENT_BROKER_CLIENT_NAME", "agent-py"),
        heartbeat_seconds=_int("AGENT_BROKER_HEARTBEAT", 30),
        reconnect_interval_seconds=_float("AGENT_BROKER_RECONNECT_INTERVAL", 5.0),
        connection_timeout_seconds=_float("AGENT_BROKER_CONNECT_TIMEOUT", 10.0),
        prefetch_count=_int("AGENT_BROKER_PREFETCH", 16),
    )
