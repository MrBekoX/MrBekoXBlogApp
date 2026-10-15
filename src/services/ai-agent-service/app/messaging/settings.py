"""Broker bağlantı ayarları (B2). Geliştirme/üretim ayrımı vhost ile yapılır
(plan satır 253: "ortam ön eki veya ayrı vhost"); dev değerleri ortam
değişkenlerinde düz metin kalabilir, üretim değerleri env ile verilir.

Sayısal değişkenler ``env_file.env_int/env_float`` ile okunur (source-run
üst seviye modül; testler ``pythonpath = ["app"]`` ile import eder): değer
yok/boşsa kod varsayılanı, tür hatasında anlaşılır ``EnvConfigError``
(mesaj ham değeri yazmaz).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

from env_file import env_float, env_int

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

    return BrokerSettings(
        host=env.get("AGENT_BROKER_HOST", "127.0.0.1"),
        port=env_int("AGENT_BROKER_PORT", 5672, env),
        username=env.get("AGENT_BROKER_USERNAME", "agent_svc"),
        password=env.get("AGENT_BROKER_PASSWORD", "agent_svc_dev"),
        virtualhost=env.get("AGENT_BROKER_VHOST", "blogapp_dev"),
        client_name=env.get("AGENT_BROKER_CLIENT_NAME", "agent-py"),
        heartbeat_seconds=env_int("AGENT_BROKER_HEARTBEAT", 30, env),
        reconnect_interval_seconds=env_float("AGENT_BROKER_RECONNECT_INTERVAL", 5.0, env),
        connection_timeout_seconds=env_float("AGENT_BROKER_CONNECT_TIMEOUT", 10.0, env),
        prefetch_count=env_int("AGENT_BROKER_PREFETCH", 16, env),
    )
