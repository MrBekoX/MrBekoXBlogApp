"""B8 içerik senkronizasyonu test kurulumu: gerçek broker, ÖZEL vhost.

Bu dizin B8 test sahipliğidir; kök ``tests/`` conftest'i değiştirilmez (L005:
``tests/content_sync`` __init__.py'li pakettir, conftest.py güvenlidir).

Ortam (L009 / W5 dispatch kuralı: her fazın broker entegrasyon testleri KENDİ
vhost'unu kullanır):
- Broker: ayrı vhost ``blogapp_dev_b8`` — B2/B3 (blogapp_dev), B4 (blogapp_dev_b4)
  ve B5 (blogapp_dev_b5) paketleriyle kuyruk paylaşımı yok.
- B8 consumer projection durumu bellek-içidir (A3 InMemoryContentIndex sınır kararı;
  gerçek pgvector B11 Docker fazının konusudur) — bu paketin scratch DB ihtiyacı yoktur.
- Parola KODA GİRMEZ: dev düz metin kimlikler B2'den devralınır (yalnız lokal broker).

pytest-asyncio varsayımı YOKTUR: senkron testler paylaşımlı loop'ta ``run()`` ile
coroutine çalıştırır (B4/B5 deseni).
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import pytest

from messaging import BrokerSettings, broker_connection, declare_topology
from messaging.topology import CONTENT_QUEUE

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
FIXTURES_DIR = REPO_ROOT / "src" / "contracts" / "agent" / "fixtures"

MGMT = "http://127.0.0.1:15672/api"
#: B8 testlerine ÖZEL vhost (L009: kuyruk paylaşımı yok).
VHOST = "blogapp_dev_b8"
ADMIN = ("blogapp", "blogapp_dev")
BACKEND_USER = ("backend_svc", "backend_svc_dev")
AGENT_USER = ("agent_svc", "agent_svc_dev")

QUEUE_PURGE_TARGETS = (
    CONTENT_QUEUE,
    f"{CONTENT_QUEUE}.dlq",
    "agent.execute.q",
    "agent.execute.q.dlq",
    "agent.control.q",
    "agent.control.q.dlq",
    "backend.agent.events.q",
    "backend.agent.events.q.dlq",
)

CONTENT_EXCHANGE = "blog.content.events"


def ensure_loop() -> asyncio.AbstractEventLoop:
    """Paylaşımlı loop'u döndürür ve current yapar (B4/B5 gerekçesi)."""

    global _shared_loop
    if _shared_loop is None or _shared_loop.is_closed():
        _shared_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_shared_loop)
    return _shared_loop


def run(coroutine: Any) -> Any:
    """Coroutine'i paylaşımlı oturum loop'unda çalıştırır (pytest-asyncio'suz)."""

    ensure_loop()
    assert _shared_loop is not None
    return _shared_loop.run_until_complete(coroutine)


_shared_loop: asyncio.AbstractEventLoop | None = None


@pytest.fixture(scope="session", autouse=True)
def _close_shared_loop() -> Any:
    yield
    global _shared_loop

    if _shared_loop is not None and not _shared_loop.is_closed():
        _shared_loop.close()
    _shared_loop = None


# --------------------------------------------------------------------------
# Management API yardımcıları (stdlib)
# --------------------------------------------------------------------------


def make_settings(
    username: str = AGENT_USER[0],
    password: str = AGENT_USER[1],
    **overrides: Any,
) -> BrokerSettings:
    defaults: dict[str, Any] = dict(
        host="127.0.0.1",
        username=username,
        password=password,
        virtualhost=VHOST,
        reconnect_interval_seconds=1.5,
        connection_timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return BrokerSettings(**defaults)


def mgmt_request(method: str, path: str, body: Any = None, auth: tuple[str, str] = ADMIN) -> Any:
    token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    req = urllib.request.Request(
        MGMT + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Basic " + token, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def mgmt_try(method: str, path: str, body: Any = None, auth: tuple[str, str] = ADMIN) -> int:
    try:
        mgmt_request(method, path, body, auth)
        return 200
    except urllib.error.HTTPError as exc:
        return exc.code


def broker_management_healthy() -> bool:
    try:
        mgmt_request("GET", "/overview")
        return True
    except Exception:
        return False


def wait_for_management(timeout_seconds: float = 180.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if broker_management_healthy():
            return
        time.sleep(2.0)
    raise TimeoutError(f"RabbitMQ management {timeout_seconds}s içinde hazır olmadı")


def provision_vhost_and_users() -> None:
    """vhost ``blogapp_dev_b8`` + servis kullanıcıları izinleri (idempotent).

    İzin modeli B2/B5 ile aynıdır: backend yalnız commands+content exchange'lerine
    yazar; agent yalnız kendi olaylarını yayınlar ve komut/içerik kuyruklarını tüketir.
    """

    mgmt_request("PUT", f"/vhosts/{VHOST}")
    for user, password in (BACKEND_USER, AGENT_USER):
        mgmt_request("PUT", f"/users/{user}", {"password": password, "tags": "none"})
    mgmt_request(
        "PUT",
        f"/permissions/{VHOST}/{BACKEND_USER[0]}",
        {
            "configure": ".*",
            "write": r"blog\.(agent\.commands|content\.events)",
            "read": r"backend\.agent\.events\.q(\.dlq)?|agent\.(execute|control|content)\.q",
        },
    )
    mgmt_request(
        "PUT",
        f"/permissions/{VHOST}/{AGENT_USER[0]}",
        {
            "configure": "",
            "write": r"blog\.agent\.events",
            "read": r"agent\.(execute|control|content)\.q(\.dlq)?",
        },
    )


def purge_queues() -> None:
    """Ana kuyruk ve DLQ'ları boşaltır (RabbitMQ 4.2: ``/contents`` uç noktası)."""

    vhost = urllib.parse.quote(VHOST, safe="")
    for queue in QUEUE_PURGE_TARGETS:
        status = mgmt_try("DELETE", f"/queues/{vhost}/{queue}/contents")
        if status not in (200, 204, 404):  # 404: kuyruk henüz yok (geçerli)
            raise RuntimeError(f"purge başarısız: {queue} -> HTTP {status}")


def queue_depth(queue: str) -> int:
    vhost = urllib.parse.quote(VHOST, safe="")
    info = mgmt_request("GET", f"/queues/{vhost}/{queue}")
    return int(info.get("messages", 0))


async def wait_until(condition, timeout_seconds: float = 15.0, interval: float = 0.2) -> None:
    """Koşul sağlanana kadar bekler (broker asenkron teslim senkronizasyonu)."""

    import asyncio as _asyncio

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return
        await _asyncio.sleep(interval)
    raise TimeoutError(f"koşul {timeout_seconds}s içinde sağlanmadı")


# --------------------------------------------------------------------------
# pytest fixture'ları
# --------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def provisioned_broker() -> None:
    wait_for_management()
    provision_vhost_and_users()


@pytest.fixture(scope="session", autouse=True)
def topology_ready(provisioned_broker: None) -> None:
    """Topolojiyi admin bağlantısıyla kurar (K3: üretimde declarer backend'dir)."""

    async def _declare() -> None:
        async with broker_connection(make_settings(*ADMIN)) as conn:
            channel = await conn.channel(publisher_confirms=False)
            await declare_topology(channel)
            await channel.close()

    last_error: Exception | None = None
    for _ in range(3):
        try:
            run(_declare())
            return
        except Exception as exc:  # vhost boot penceresi
            last_error = exc
            time.sleep(5.0)
    assert last_error is None, f"topology kurulamadı: {last_error}"


@pytest.fixture(autouse=True)
def clean_queues(topology_ready: None) -> None:
    purge_queues()
    yield
    purge_queues()


# --------------------------------------------------------------------------
# Zarf üreticileri (tests kendi zarfını kurar; ortak fixture'lar da okunur)
# --------------------------------------------------------------------------


def read_fixture(relative_path: str) -> dict:
    return json.loads((FIXTURES_DIR / relative_path).read_text(encoding="utf-8"))


def _uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"b8-{seed}"))


def make_article_changed(
    *,
    article_id: str = "my-blog-post",
    revision: int = 1,
    action: str = "updated",
    content_hash: str = "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
    message_id: str | None = None,
    title: str = "Deneme baslik",
) -> dict:
    payload: dict[str, Any] = {
        "article_id": article_id,
        "article_revision": revision,
        "action": action,
    }
    if action == "updated":
        payload["content_hash"] = content_hash
    return {
        "message_id": message_id or _uuid(f"article-{article_id}-{revision}-{action}"),
        "message_type": "content.article.changed",
        "schema_version": 1,
        "occurred_at": "2026-10-12T09:00:00Z",
        "producer": "backend-net",
        "correlation_id": _uuid("corr-article"),
        "payload": payload,
    }


def make_sync_batch(
    *,
    sync_id: str,
    batch_index: int,
    total_batches: int,
    items: list[dict],
    message_id: str | None = None,
) -> dict:
    return {
        "message_id": message_id or _uuid(f"batch-{sync_id}-{batch_index}"),
        "message_type": "content.sync.batch",
        "schema_version": 1,
        "occurred_at": "2026-10-12T09:00:00Z",
        "producer": "backend-net",
        "correlation_id": _uuid(f"corr-batch-{sync_id}"),
        "payload": {
            "sync_id": sync_id,
            "batch_index": batch_index,
            "total_batches": total_batches,
            "items": items,
        },
    }


def make_sync_completed(*, sync_id: str, item_count: int, message_id: str | None = None) -> dict:
    return {
        "message_id": message_id or _uuid(f"completed-{sync_id}"),
        "message_type": "content.sync.completed",
        "schema_version": 1,
        "occurred_at": "2026-10-12T09:00:00Z",
        "producer": "backend-net",
        "correlation_id": _uuid(f"corr-completed-{sync_id}"),
        "payload": {
            "sync_id": sync_id,
            "item_count": item_count,
        },
    }
