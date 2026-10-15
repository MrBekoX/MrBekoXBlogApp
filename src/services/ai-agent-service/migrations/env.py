"""Alembic ortamı (B4): agent schema'sının migration aracı.

D011: agent tablolarının tek sahibi Python'dur; bu dizin blogdb içindeki
``agent`` schema'sını yönetir, backend (EF Core) migration'larına dokunmaz.
Alembic sürümü 1.20.0 (resmî belge: SQLAlchemy 2.0+ gerekir); async çalışma
şablonu resmî "cookbook" async desenini izler (asyncpg sürücüsü).

Bağlantı:
- ``AGENT_DB_URL`` verilirse doğrudan kullanılır (testler bu yolu kullanır).
- Aksi halde ``AGENT_DB_*`` değişkenlerinden DSN kurulur (bkz. app/messaging/db.py);
  ``AGENT_DB_PASSWORD`` zorunludur.

Sürüm tablosu hedef schema içinde tutulur (``agent.alembic_version_agent``):
migration sahipliği tek yerden doğrulanabilir ve backend şemasından ayrışır.

CLI: ``alembic -c migrations/alembic.ini upgrade head`` (repo kökünden).
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import quote

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# .env yükleme: app/env_file.py üst seviye modülüdür; alembic repo kökünden
# çalışır (CWD bağımsızlığı dosya konumundan türetilir). Yükleme config
# okumalarından ÖNCE yapılır: AGENT_DB_* değerleri (.env'dekiler dâhil) hem
# AGENT_SCHEMA okumasına hem _resolve_url'a düşer. Gerçek ortam > .env.
_MIGRATIONS_APP_DIR = str(Path(__file__).resolve().parents[1] / "app")
if _MIGRATIONS_APP_DIR not in sys.path:
    sys.path.insert(0, _MIGRATIONS_APP_DIR)

from env_file import load_env_file  # noqa: E402

load_env_file()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

AGENT_SCHEMA = config.attributes.get("agent_schema") or os.environ.get("AGENT_DB_SCHEMA", "agent")


def _resolve_url() -> str:
    from_config = config.get_section_option(config.config_ini_section, "sqlalchemy.url")
    if from_config:
        return from_config
    explicit = os.environ.get("AGENT_DB_URL")
    if explicit:
        return explicit
    host = os.environ.get("AGENT_DB_HOST", "127.0.0.1")
    port = os.environ.get("AGENT_DB_PORT", "5432")
    user = os.environ.get("AGENT_DB_USER", "blogapp_user")
    password = os.environ.get("AGENT_DB_PASSWORD", "")
    database = os.environ.get("AGENT_DB_NAME", "blogdb_dev")
    if not password:
        raise RuntimeError(
            "AGENT_DB_URL veya AGENT_DB_PASSWORD tanımlı olmalıdır; parola koda gömülmez"
        )
    return (
        f"postgresql+asyncpg://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{database}"
    )


def run_migrations_offline() -> None:
    """``--sql`` modu: DB bağlantısı olmadan SQL üretir."""

    context.configure(
        url=_resolve_url(),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=AGENT_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def _ensure_agent_schema(connection: Connection) -> None:
    """Hedef schema'yı kendi transaction'ında garanti eder ve commit eder.

    Alembic sürüm tablosunu migration'lardan ÖNCE hedef schema'da yaratır;
    ilk kurulumda schema yoksa chicken-and-egg doğar. DDL ayrı commit edilir:
    aynı bağlantıda commit'siz bırakılırsa alembic'in transaction'ı iç içe
    geçer ve bağlantı kapanışında tüm DDL geri alınır (bu hata 2026-10-11'de
    yakalandı: upgrade "başarılı" görünüyordu, hiçbir tablo kalmıyordu).
    """

    if not AGENT_SCHEMA.replace("_", "").isalnum():
        raise ValueError(f"geçersiz schema adı: {AGENT_SCHEMA!r}")
    connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{AGENT_SCHEMA}"')
    connection.commit()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=None,
        version_table="alembic_version_agent",
        version_table_schema=AGENT_SCHEMA,
        # Agent schema'sı bu migration zincirinin sahibidir; include_object ile
        # yabancı schema nesnelerine dokunulmaz (D011: schema'lar arası müdahale yok).
        include_schemas=True,
        include_object=lambda obj, name, type_, reflected, compare_to: (
            obj.schema == AGENT_SCHEMA if hasattr(obj, "schema") else True
        ),
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_ensure_agent_schema)
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
