"""``service_main`` kompozisyon smoke testi (sahte bileşenlerle, OFFLINE).

Canlı giriş noktasının bileşen kurulumu ve düzgün kapanışı broker/DB olmadan
kanıtlanır: havuz/tüketici/publisher double'ları enjekte edilir; ``run_service``
önceden kurulmuş bir ``stop`` olayıyla başlatılıp temiz kapanış beklenir
(consumer stop → görev iptali → publisher/bağlantı/havuz kapanışı sırası).
"""

from __future__ import annotations

import asyncio

from agent_core.adapters import HttpContentRepository
from agent_core.adapters.test_doubles import FakeModelProvider
from agent_core.ports import ContentRepository

from app import service_main
from app.messaging import AgentDbSettings, BrokerSettings


class _FakePool:
    """Havuz double'ı: yalnız yaşam döngüsü gözlemlenir (sorgu yürütülmez)."""

    is_test_double = True

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeConnection:
    is_test_double = True

    def __init__(self, log: list[str], name: str) -> None:
        self._log = log
        self._name = name
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        self._log.append(f"conn:{self._name}:closed")


class _FakeChannel:
    is_test_double = True

    async def close(self) -> None:
        return None


class _FakePublisher:
    is_test_double = True

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True
        self._log.append("publisher:started")

    async def close(self) -> None:
        self.closed = True
        self._log.append("publisher:closed")


class _FakeConsumer:
    is_test_double = True

    def __init__(self, log: list[str], name: str) -> None:
        self._log = log
        self._name = name
        self.running = False

    async def start(self) -> None:
        self.running = True
        self._log.append(f"consumer:{self._name}:started")

    async def stop(self) -> None:
        self.running = False
        self._log.append(f"consumer:{self._name}:stopped")


class _NoopWorker:
    is_test_double = True

    async def run_forever(self, *, max_cycles: int | None = None) -> None:
        return None


class _NoopReaper:
    is_test_double = True

    async def run_forever(self, *, stop: asyncio.Event | None = None) -> None:
        if stop is not None:
            await stop.wait()


def test_build_components_wires_pool_rooted_bileşenler() -> None:
    pool = _FakePool()
    model = FakeModelProvider("kompozisyon")

    async def scenario():
        return await service_main.build_components_async(
            db_settings=AgentDbSettings(),
            broker=BrokerSettings(),
            environ={"AGENT_WORKER_ID": "smoke-worker"},
            pool=pool,
            model=model,
        )

    components = asyncio.run(scenario())

    assert components.pool is pool
    assert components.worker._deps.model is model  # model enjeksiyonu
    assert components.worker._deps.content is None  # env boş: depo bağlanmaz (mevcut davranış)
    assert components.content is None
    assert components.publisher is components.worker._publisher  # aynı yayıncı
    assert components.intake is not None
    assert components.control_service is not None
    assert components.reaper is not None
    assert components.relay is None  # relay publisher'ı run_service kurar


def test_build_components_wires_http_content_repository_when_env_set() -> None:
    """``AGENT_CONTENT_BASE_URL`` dolu: HTTP içerik deposu çekirdeğe bağlanır."""

    pool = _FakePool()
    model = FakeModelProvider("kompozisyon")
    env = {
        "AGENT_WORKER_ID": "smoke-worker",
        "AGENT_CONTENT_BASE_URL": "http://content.test/api/v1",
        "AGENT_CONTENT_SERVICE_KEY": "ic-anahtar",
    }

    async def scenario():
        return await service_main.build_components_async(
            db_settings=AgentDbSettings(),
            broker=BrokerSettings(),
            environ=env,
            pool=pool,
            model=model,
        )

    components = asyncio.run(scenario())

    repo = components.worker._deps.content
    assert isinstance(repo, HttpContentRepository)  # env'li dal: gerçek adaptör
    assert isinstance(repo, ContentRepository)  # port sözleşmesi yapısal olarak sağlanır
    assert components.content is repo  # kapanış için bileşende taşınır
    assert components.worker._deps.model is model  # model bağlaması değişmez


def test_run_service_starts_and_shuts_down_cleanly(monkeypatch) -> None:
    log: list[str] = []
    connections = {
        "execute": _FakeConnection(log, "execute"),
        "control": _FakeConnection(log, "control"),
        "relay": _FakeConnection(log, "relay"),
    }
    publisher = _FakePublisher(log)

    opened = {"count": 0}

    async def _fake_connect_broker(_settings):
        # sırayla execute, control, relay bağlantıları açılır
        name = ("execute", "control", "relay")[opened["count"]]
        opened["count"] += 1
        return connections[name]

    async def _fake_declare_topology(_channel) -> None:
        log.append("topology:declared")

    async def _fake_channel(publisher_confirms=True):
        return _FakeChannel()

    monkeypatch.setattr(service_main, "connect_broker", _fake_connect_broker)
    monkeypatch.setattr(service_main, "declare_topology", _fake_declare_topology)
    monkeypatch.setattr(service_main, "BrokerPublisher", lambda conn, exchanges, settings=None: publisher)

    def _fake_consumer(conn, queue_name, handler, settings=None):
        name = "execute" if queue_name.endswith("execute.q") else "control"
        return _FakeConsumer(log, name)

    monkeypatch.setattr(service_main, "BrokerConsumer", _fake_consumer)
    # BrokerConsumer.channel metodu relay bağlantısında çağrılır
    for conn in connections.values():
        conn.channel = _fake_channel  # type: ignore[attr-defined]
    # D013: declare bayrakla çalışır; bu smoke bayraklı yolu da kanıtlar.
    monkeypatch.setenv("AGENT_TOPOLOGY_DECLARE", "1")

    async def scenario():
        components = await service_main.build_components_async(
            db_settings=AgentDbSettings(),
            broker=BrokerSettings(),
            environ={"AGENT_WORKER_ID": "smoke-worker"},
            pool=_FakePool(),
            model=FakeModelProvider("kompozisyon"),
        )
        # Görev double'ları: gerçek worker/reaper döngüsü broker ister.
        components.worker = _NoopWorker()  # type: ignore[assignment]
        components.reaper = _NoopReaper()  # type: ignore[assignment]
        stop = asyncio.Event()
        stop.set()  # hazır kurulu: run_service derhal düzgün kapanır
        pool = components.pool
        await service_main.run_service(components, stop=stop)
        return log, pool

    log, pool = asyncio.run(scenario())

    assert log.count("consumer:execute:started") == 1
    assert log.count("consumer:control:started") == 1
    assert log.count("consumer:execute:stopped") == 1
    assert log.count("consumer:control:stopped") == 1
    assert "publisher:started" in log and "publisher:closed" in log
    assert "topology:declared" in log
    assert publisher.closed is True
    assert all(conn.closed for conn in connections.values()), f"kapanmamış bağlantı; log={log}"
    assert pool.closed is True  # havuz en son kapanır
    assert log.index("consumer:control:stopped") < log.index("publisher:closed")
