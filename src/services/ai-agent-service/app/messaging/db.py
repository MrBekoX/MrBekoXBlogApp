"""Agent veritabanı bağlantı ayarları ve havuzu (B4).

D011: agent tablolarının tek sahibi Python'dur; blogdb içinde ayrı ``agent``
schema'sı kullanılır ve schema'lar arası FK kurulmaz. Bağlantı ayarları ortam
değişkenlerinden okunur; parola KODDA VARSAYILAN OLARAK TAŞINMAZ (geliştirme
ortamında ``AGENT_DB_PASSWORD`` verilir).

Sürücü: asyncpg 0.32.0 (resmî PyPI kaydı, Python >=3.9). Migration aracı:
Alembic 1.20.0 (resmî belge, SQLAlchemy 2.0+ gerekir) — ``migrations/`` altında.

Wire sürüm izolasyonu (K4, migration 0005): havuzun her bağlantısı başlangıçta
``agent.worker_wire_max`` oturum ayarını bildirir (asyncpg ``server_settings``).
``agent.jobs`` tetikleyicisi bu değerden büyük sürümlü satırların güncellenmesini
atlar: bu kod v1+v2 yürütebildiği için varsayılan ``WORKER_WIRE_MAX`` (2)'dir;
ayarı bildirmeyen eski worker v2 işine dokunamaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

import asyncpg

from env_file import env_float, env_int

from .wire import WORKER_WIRE_MAX, WORKER_WIRE_MAX_SETTING

__all__ = ["AgentDbSettings", "connect_pool", "AgentDbError"]


class AgentDbError(RuntimeError):
    """Veritabanı yapılandırması eksik veya bağlantı kurulamadığında yükselir."""


@dataclass(frozen=True)
class AgentDbSettings:
    """asyncpg bağlantı parametreleri; D011 kapsamındaki agent DB rolü."""

    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "blogapp_user"
    password: str = ""
    database: str = "blogdb_dev"
    schema: str = "agent"
    #: Havuz boyutu: intake hızlı DB işlemleri içindir; LLM çağrısı bu havuzu kullanmaz.
    min_size: int = 1
    max_size: int = 4
    command_timeout_seconds: float = 10.0
    #: Bu süreçte yürütülebilen en yüksek run wire sürümü (``agent.worker_wire_max``).
    worker_wire_max: int = WORKER_WIRE_MAX

    def server_settings(self) -> dict[str, str]:
        """Bağlantı başlangıcında bildirilen oturum ayarları (claim izolasyon GUC'u)."""

        return {WORKER_WIRE_MAX_SETTING: str(int(self.worker_wire_max))}

    def dsn(self) -> str:
        """asyncpg DSN'i üretir; parola URL-encode edilir, loglamaya uygun değildir."""

        return (
            f"postgresql://{quote(self.user, safe='')}:{quote(self.password, safe='')}"
            f"@{self.host}:{self.port}/{self.database}"
        )


def from_env(environ: dict[str, str] | None = None) -> AgentDbSettings:
    """Ortamdan ayarları okur; ``AGENT_DB_PASSWORD`` boşsa AgentDbError fırlatır.

    Parola varsayılanı bilinçli olarak yoktur: sır kod/fixture'a girmez
    (genel kural); eksik değerli sessiz devamları önlemek için fail-fast edilir.
    Sayısal alanlar ``env_file`` yardımcılarıyla okunur: tür hatası anlaşılır
    ``EnvConfigError`` üretir (mesaj ham değeri yazmaz).
    """

    env = os.environ if environ is None else environ
    password = env.get("AGENT_DB_PASSWORD", "")
    if not password:
        raise AgentDbError(
            "AGENT_DB_PASSWORD tanımlı değil; agent DB parolası yalnız ortam değişkeninden alınır"
        )

    return AgentDbSettings(
        host=env.get("AGENT_DB_HOST", "127.0.0.1"),
        port=env_int("AGENT_DB_PORT", 5432, env),
        user=env.get("AGENT_DB_USER", "blogapp_user"),
        password=password,
        database=env.get("AGENT_DB_NAME", "blogdb_dev"),
        schema=env.get("AGENT_DB_SCHEMA", "agent"),
        min_size=env_int("AGENT_DB_POOL_MIN", 1, env),
        max_size=env_int("AGENT_DB_POOL_MAX", 4, env),
        command_timeout_seconds=env_float("AGENT_DB_COMMAND_TIMEOUT", 10.0, env),
    )


async def connect_pool(settings: AgentDbSettings) -> asyncpg.Pool:
    """Bağlantı havuzu açar; ömrü çağıran yönetir (``await pool.close()``)."""

    try:
        return await asyncpg.create_pool(
            dsn=settings.dsn(),
            min_size=settings.min_size,
            max_size=settings.max_size,
            command_timeout=settings.command_timeout_seconds,
            server_settings=settings.server_settings(),
        )
    except (OSError, asyncpg.PostgresError) as exc:
        raise AgentDbError(
            f"agent veritabanına bağlanılamadı ({settings.host}:{settings.port}/{settings.database}): {exc}"
        ) from exc
