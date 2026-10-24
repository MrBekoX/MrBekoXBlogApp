"""Explicit disposable-infrastructure settings shared by integration fixtures.

The established local/CI endpoints remain defaults. Supplying test PostgreSQL
credentials bypasses docker/.env entirely; partial overrides fail closed.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import pytest


def broker_address() -> dict[str, str | int]:
    return {"host": os.environ.get("RABBITMQ_HOST", "127.0.0.1"),
            "port": int(os.environ.get("RABBITMQ_PORT", "5672"))}


def broker_management_url() -> str:
    return os.environ.get("RABBITMQ_MGMT_URL", "http://127.0.0.1:15672/api").rstrip("/")


def postgres_host() -> str:
    return os.environ.get("BLOGAPP_TEST_PG_HOST", "127.0.0.1")


def postgres_port() -> int:
    return int(os.environ.get("BLOGAPP_TEST_PG_PORT", "5432"))


def postgres_credentials(repo_root: Path) -> dict[str, str]:
    keys = ("BLOGAPP_TEST_PG_HOST", "BLOGAPP_TEST_PG_PORT", "BLOGAPP_TEST_PG_USER", "BLOGAPP_TEST_PG_PASSWORD")
    if any(key in os.environ for key in keys):
        if not os.environ.get("BLOGAPP_TEST_PG_USER") or "BLOGAPP_TEST_PG_PASSWORD" not in os.environ:
            pytest.fail("Explicit PostgreSQL test settings require BLOGAPP_TEST_PG_USER and BLOGAPP_TEST_PG_PASSWORD")
        return {"POSTGRES_USER": os.environ["BLOGAPP_TEST_PG_USER"],
                "POSTGRES_PASSWORD": os.environ["BLOGAPP_TEST_PG_PASSWORD"]}
    env_path = repo_root / "docker" / ".env"
    if not env_path.exists():
        pytest.fail("docker/.env not found; supply explicit PostgreSQL test credentials")
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def postgres_migration_url(database: str, user: str, password: str) -> str:
    host = postgres_host()
    if ":" in host:
        host = f"[{host}]"
    return (f"postgresql+asyncpg://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{host}:{postgres_port()}/{quote(database, safe='')}")
