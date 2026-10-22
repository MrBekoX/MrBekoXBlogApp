"""B2 broker test kurulumu ve paylaşılan yardımcılar.

Bu dizin B2 test sahipliğidir; kök ``tests/`` conftest'i değiştirilmez.
Ortam: docker compose rabbitmq (127.0.0.1:5672, management 15672),
vhost ``blogapp_dev`` ve servis kullanıcıları (dev düz metin kimlikler).
Test oturumu vhost/kullanıcıları idempotent provizyon eder; topology'yi admin
bağlantısıyla declare eder (K3: gerçek üretimde declarer backend'dir).
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from messaging import BrokerSettings, broker_connection, connect_broker, declare_topology
from messaging.topology import (
    BACKEND_EVENTS_QUEUE,
    CONTENT_QUEUE,
    CONTROL_QUEUE,
    EXECUTE_QUEUE,
)

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
FIXTURES_DIR = REPO_ROOT / "src" / "contracts" / "agent" / "fixtures"

MGMT = "http://127.0.0.1:15672/api"
VHOST = "blogapp_dev"
ADMIN = ("blogapp", "blogapp_dev")
BACKEND_USER = ("backend_svc", "backend_svc_dev")
AGENT_USER = ("agent_svc", "agent_svc_dev")
RESTRICTED_USER = ("agent_restricted", "restricted_dev")
RABBITMQ_CONTAINER = "blogapp-rabbitmq"

MAIN_QUEUES = (EXECUTE_QUEUE, CONTROL_QUEUE, CONTENT_QUEUE, BACKEND_EVENTS_QUEUE)
ALL_PURGEABLE_QUEUES = MAIN_QUEUES + tuple(f"{q}.dlq" for q in MAIN_QUEUES)


def run(coroutine: Awaitable[Any]) -> Any:
    """Coroutine'i senkron test içinde çalıştırır (pytest-asyncio'suz)."""
    return asyncio.run(coroutine)


def read_fixture(relative_path: str) -> dict:
    return json.loads((FIXTURES_DIR / relative_path).read_text(encoding="utf-8"))


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


# --------------------------------------------------------------------------
# Management API yardımcıları (stdlib): provizyon + purge + sağlık
# --------------------------------------------------------------------------


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


def provision_vhost_and_users() -> None:
    """vhost + servis kullanıcıları + kapsamlı izinler (idempotent).

    - backend_svc: tek declarer (configure .*); yalnız commands+content'e yazar;
      yalnız kendi olay kuyruğunu (+DLQ) okur.
    - agent_svc: yalnız kendi olaylarını yayınlar; komut/içerik kuyruklarını
      (+DLQ) tüketir; active declare yetkisi yok.
    - agent_restricted: izin yok; hiçbir kaynakta yayın/tüketim yapamaz.
    """

    mgmt_request("PUT", f"/vhosts/{VHOST}")
    for user, password in (BACKEND_USER, AGENT_USER, RESTRICTED_USER):
        mgmt_request("PUT", f"/users/{user}", {"password": password, "tags": "none"})
    mgmt_request(
        "PUT",
        f"/permissions/{VHOST}/{BACKEND_USER[0]}",
        {
            "configure": r".*",
            "write": r"blog\.(agent\.commands|content\.events)",
            # RabbitMQ 4.2 ölçümü: x-dead-letter-exchange'li kuyruğun YARATIMI declarer'dan
            # o kuyruk kaynağına read izni ister (mevcut eşdeğer kuyruğun tekrar declare'i
            # denetimi atlar). Bu yüzden backend declarer read kapsamı DLX'li ana/retry
            # kuyruk adlarını da içerir (regex substring eşleşir).
            "read": r"backend\.agent\.events\.q(\.dlq)?|agent\.(execute|control|content)(\.v2)?\.q",
        },
    )
    mgmt_request(
        "PUT",
        f"/permissions/{VHOST}/{AGENT_USER[0]}",
        {
            "configure": "",
            "write": r"blog\.agent\.events",
            "read": r"agent\.(execute|control|content)(\.v2)?\.q(\.dlq)?",
        },
    )


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


def purge_queues() -> None:
    """Ana kuyruk ve DLQ'ları boşaltır.

    Not: RabbitMQ 4.2 management'ında ``DELETE /queues/{vh}/{name}/purge`` 405
    döndürür (ölçüldü); kuyruk boşaltma ``/contents`` uç noktasıyla yapılır.
    Statü denetimi açıktır: sessiz başarısızlık izin verilmez (kalıntı mesaj
    sonraki testi bozar — bu hata 2026-10-11'de yakalandı).
    """

    vhost = urllib.parse.quote(VHOST, safe="")
    for queue in ALL_PURGEABLE_QUEUES:
        status = mgmt_try("DELETE", f"/queues/{vhost}/{queue}/contents")
        if status not in (200, 204, 404):  # 404: kuyruk henüz yok (geçerli)
            raise RuntimeError(f"purge başarısız: {queue} -> HTTP {status}")


def restart_broker_container() -> None:
    """docker restart ile gerçek broker kesintisi (durable topology volume'de kalır)."""

    if shutil.which("docker") is None:
        pytest.skip("docker CLI yok: gerçek broker kesinti testi atlandı")
    subprocess.run(
        ["docker", "restart", RABBITMQ_CONTAINER],
        check=True,
        timeout=180,
        capture_output=True,
    )


# --------------------------------------------------------------------------
# pytest fixture'ları
# --------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def provisioned_broker() -> None:
    wait_for_management()
    provision_vhost_and_users()


@pytest.fixture(scope="session", autouse=True)
def topology_ready(provisioned_broker: None) -> None:
    """Topolojiyi admin bağlantısıyla kurar; broker yeni restart edildiyse kısa retry yapar."""

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
        except Exception as exc:  # vhost boot penceresi: kısa bekle, tekrar dene
            last_error = exc
            time.sleep(10.0)
    assert last_error is None, f"topology kurulamadı: {last_error}"


@pytest.fixture(autouse=True)
def clean_queues(topology_ready: None) -> None:
    purge_queues()
    yield
    purge_queues()


async def wait_until(
    condition: Callable[[], bool],
    timeout_seconds: float = 15.0,
    interval: float = 0.2,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"koşul {timeout_seconds}s içinde sağlanmadı")


async def open_admin_channel(publisher_confirms: bool = False) -> Any:
    conn = await connect_broker(make_settings(*ADMIN))
    channel = await conn.channel(publisher_confirms=publisher_confirms)
    return conn, channel
