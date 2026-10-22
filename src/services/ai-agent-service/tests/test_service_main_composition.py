"""``service_main`` kompozisyon smoke testi (sahte bileşenlerle, OFFLINE).

Canlı giriş noktasının bileşen kurulumu ve düzgün kapanışı broker/DB olmadan
kanıtlanır: havuz/tüketici/publisher double'ları enjekte edilir; ``run_service``
önceden kurulmuş bir ``stop`` olayıyla başlatılıp temiz kapanış beklenir
(consumer stop → görev iptali → publisher/bağlantı/havuz kapanışı sırası).

Who am I (K2/K4/K5) eklentileri: v1+v2 execute/control kuyruklarının dördü de
tüketilir; canonical profil deposu worker bağımlılıklarına (``profile_knowledge``
+ legacy ``profile_repository``) bağlanır; ``AGENT_PROFILE_DIR`` geçersizse servis
yine kurulur ve profil çağrıları açık ``config_error`` üretir; yol çözümü
çalışma dizininden bağımsızdır (A33).
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from agent_core.adapters import HttpContentRepository
from agent_core.adapters.test_doubles import FakeModelProvider
from agent_core.errors import AgentErrorCode
from agent_core.ports import ContentRepository
from agent_core.profile import CanonicalProfileRepository, ProfileSourceError, resolve_profile_dir

from app import service_main
from app.messaging import AgentDbSettings, BrokerSettings

EXPECTED_QUEUES = ("agent.execute.q", "agent.execute.v2.q", "agent.control.q", "agent.control.v2.q")


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

    def __init__(self, log: list[str], queue_name: str, handler) -> None:
        self._log = log
        self.queue_name = queue_name
        self.handler = handler
        self.running = False

    async def start(self) -> None:
        self.running = True
        self._log.append(f"consumer:{self.queue_name}:started")

    async def stop(self) -> None:
        self.running = False
        self._log.append(f"consumer:{self.queue_name}:stopped")


class _NoopWorker:
    is_test_double = True

    async def run_forever(self, *, max_cycles: int | None = None) -> None:
        return None


class _NoopReaper:
    is_test_double = True

    async def run_forever(self, *, stop: asyncio.Event | None = None) -> None:
        if stop is not None:
            await stop.wait()


def _build(environ: dict[str, str], **kwargs):
    async def scenario():
        return await service_main.build_components_async(
            db_settings=AgentDbSettings(),
            broker=BrokerSettings(),
            environ=environ,
            pool=kwargs.pop("pool", _FakePool()),
            model=kwargs.pop("model", FakeModelProvider("kompozisyon")),
            **kwargs,
        )

    return asyncio.run(scenario())


def test_build_components_wires_pool_rooted_bileşenler() -> None:
    pool = _FakePool()
    model = FakeModelProvider("kompozisyon")

    components = _build({"AGENT_WORKER_ID": "smoke-worker"}, pool=pool, model=model)

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

    model = FakeModelProvider("kompozisyon")
    env = {
        "AGENT_WORKER_ID": "smoke-worker",
        "AGENT_CONTENT_BASE_URL": "http://content.test/api/v1",
        "AGENT_CONTENT_SERVICE_KEY": "ic-anahtar",
    }

    components = _build(env, model=model)

    repo = components.worker._deps.content
    assert isinstance(repo, HttpContentRepository)  # env'li dal: gerçek adaptör
    assert isinstance(repo, ContentRepository)  # port sözleşmesi yapısal olarak sağlanır
    assert components.content is repo  # kapanış için bileşende taşınır
    assert components.worker._deps.model is model  # model bağlaması değişmez


# --- Who am I: profil kompozisyonu (K2/K5) ---


def test_canonical_profile_repository_is_wired_to_worker_dependencies() -> None:
    components = _build({"AGENT_WORKER_ID": "smoke-worker"})

    deps = components.worker._deps
    assert isinstance(deps.profile_knowledge, CanonicalProfileRepository)
    # Legacy A9 yolu aynı canonical kaynağa bağlıdır (ayrı biyografi kopyası yok).
    assert deps.profile_repository is deps.profile_knowledge
    assert components.profile_repository is deps.profile_knowledge
    assert deps.profile_knowledge.directory == resolve_profile_dir({})
    snapshot = deps.profile_knowledge.active_snapshot()
    assert snapshot.profile_id and snapshot.revision >= 1 and len(snapshot.content_hash) == 64
    assert not getattr(deps.profile_knowledge, "is_test_double", False)  # üretimde sahte depo yok


def test_profile_dir_override_is_used_without_cwd_dependence(tmp_path: Path, monkeypatch) -> None:
    """A33: AGENT_PROFILE_DIR mutlak kopyayı gösterir; kompozisyon başka bir cwd'den koşar."""

    original = resolve_profile_dir({})
    copy_dir = tmp_path / "packaged" / "author-profile"
    shutil.copytree(original, copy_dir)
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    components = _build({"AGENT_WORKER_ID": "smoke-worker", "AGENT_PROFILE_DIR": str(copy_dir)})

    repo = components.worker._deps.profile_knowledge
    assert isinstance(repo, CanonicalProfileRepository)
    assert Path(repo.directory) == copy_dir
    # Aynı canonical içerik: kopyadan okunan sürüm/hash özgün kaynakla aynı.
    assert repo.active_snapshot().same_as(CanonicalProfileRepository(original).active_snapshot())


def test_default_profile_resolution_is_independent_of_cwd(tmp_path: Path, monkeypatch) -> None:
    expected = resolve_profile_dir({})
    monkeypatch.chdir(tmp_path)

    components = _build({"AGENT_WORKER_ID": "smoke-worker"})

    assert components.worker._deps.profile_knowledge.directory == expected


@pytest.mark.parametrize(
    "configured",
    [
        "relative/author-profile",  # cwd'ye göre çözülmez → reddedilir
        "__MISSING__",  # mutlak ama manifest yok
    ],
)
def test_unresolvable_profile_dir_keeps_service_up_with_explicit_config_error(
    tmp_path: Path, configured: str
) -> None:
    value = str(tmp_path / "missing-profile") if configured == "__MISSING__" else configured

    components = _build({"AGENT_WORKER_ID": "smoke-worker", "AGENT_PROFILE_DIR": value})

    repo = components.worker._deps.profile_knowledge
    assert isinstance(repo, service_main.UnavailableProfileRepository)
    assert components.worker._deps.profile_repository is repo
    # Servis kurulur (makale/genel akışlar etkilenmez); profil çağrıları açık hata.
    assert components.intakes and components.control_services
    with pytest.raises(ProfileSourceError) as excinfo:
        repo.active_snapshot()
    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    with pytest.raises(ProfileSourceError):
        repo.load(None)
    with pytest.raises(ProfileSourceError):
        asyncio.run(repo.get_profile())


def test_injected_profile_repository_overrides_resolution() -> None:
    sentinel = service_main.UnavailableProfileRepository("test")

    components = _build({"AGENT_WORKER_ID": "smoke-worker"}, profile_repository=sentinel)

    assert components.worker._deps.profile_knowledge is sentinel
    assert components.worker._deps.profile_repository is sentinel


# --- Wire sürümleri (K4) ---


def test_per_version_intake_and_control_services_accept_only_their_version() -> None:
    components = _build({"AGENT_WORKER_ID": "smoke-worker"})

    assert sorted(components.intakes) == [1, 2]
    assert sorted(components.control_services) == [1, 2]
    for version, intake in components.intakes.items():
        assert intake._accepted_versions == (version,)
    for version, control in components.control_services.items():
        assert control._accepted_versions == (version,)
    assert components.intake is components.intakes[1]
    assert components.control_service is components.control_services[1]


def test_worker_db_pool_declares_wire_capability() -> None:
    """Yeni worker havuzu claim izolasyon GUC'unu bildirir (migration 0005)."""

    assert AgentDbSettings().server_settings() == {"agent.worker_wire_max": "2"}
    assert AgentDbSettings(worker_wire_max=1).server_settings() == {"agent.worker_wire_max": "1"}


def test_run_service_starts_and_shuts_down_cleanly(monkeypatch) -> None:
    log: list[str] = []
    connections = {
        "execute": _FakeConnection(log, "execute"),
        "control": _FakeConnection(log, "control"),
        "relay": _FakeConnection(log, "relay"),
    }
    publisher = _FakePublisher(log)
    consumers: list[_FakeConsumer] = []

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
        consumer = _FakeConsumer(log, queue_name, handler)
        consumers.append(consumer)
        return consumer

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
        return log, pool, components

    log, pool, components = asyncio.run(scenario())

    # v1 + v2 execute/control kuyruklarının dördü de tüketildi ve kapatıldı.
    assert sorted(c.queue_name for c in consumers) == sorted(EXPECTED_QUEUES)
    for queue in EXPECTED_QUEUES:
        assert log.count(f"consumer:{queue}:started") == 1, log
        assert log.count(f"consumer:{queue}:stopped") == 1, log
    by_queue = {c.queue_name: c for c in consumers}
    assert by_queue["agent.execute.q"].handler == components.intakes[1].handle_delivery
    assert by_queue["agent.execute.v2.q"].handler == components.intakes[2].handle_delivery
    assert by_queue["agent.control.q"].handler == components.control_services[1].handle_delivery
    assert by_queue["agent.control.v2.q"].handler == components.control_services[2].handle_delivery
    assert components.execute_consumers[2] is by_queue["agent.execute.v2.q"]
    assert components.control_consumers[2] is by_queue["agent.control.v2.q"]
    assert "publisher:started" in log and "publisher:closed" in log
    assert "topology:declared" in log
    assert publisher.closed is True
    assert all(conn.closed for conn in connections.values()), f"kapanmamış bağlantı; log={log}"
    assert pool.closed is True  # havuz en son kapanır
    assert log.index("consumer:agent.control.v2.q:stopped") < log.index("publisher:closed")
