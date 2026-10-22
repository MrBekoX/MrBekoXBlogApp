"""Canlı worker giriş noktası: ``python -m app.service_main``.

B4-B9 bileşenlerinin üretim kompozisyonu (referans: ``tests/e2e/harness.py``
``run_intake_once`` + ``make_e2e_worker``):

- **DB:** ``messaging.db.from_env`` + ``connect_pool`` — ``AGENT_DB_PASSWORD``
  boşsa açık hata ile çıkar (parola koda/fixture'a girmez).
- **Broker:** ``messaging.settings.from_env`` — execute/control kuyrukları için
  iki tüketici + outbox relay için confirm'lu publisher.
- **Model bağlama:** ``AGENT_LLM_API_KEY`` DOLU ise
  ``agent_core.adapters.build_model_provider_from_env`` gerçek OpenAI-uyumlu
  sağlayıcıyı kurar (streaming); boşsa MEVCUT davranış
  (``resolve_model_provider``) kullanılır — anahtarsız default birebir korunur.
- **İçerik deposu bağlama:** ``AGENT_CONTENT_BASE_URL`` DOLU ise
  ``agent_core.adapters.build_content_repository_from_env`` backend iç ucunu
  (``HttpContentRepository``) ``ExecutionDependencies.content``'e bağlar;
  boşsa MEVCUT davranış (depo bağlı değil) birebir korunur. Canlı worker'da
  retrieval citation üretimi ancak depo bağlıyken mümkündür.
- **Ortam yükleme:** ``_async_main`` başında ``load_env_file()`` (``env_file``
  modülü) hizmet kökü ``.env``'ini okur; öncelik GERÇEK ORTAM > ``.env`` >
  kod varsayılanıdır (``AGENT_ENV_FILE`` ile açık yol verilebilir).
- **Profil kaynağı (Who am I, K2/K5):** ``resolve_profile_dir(environ)``
  (``AGENT_PROFILE_DIR`` mutlak yolu → modül konumundan yukarı yürüyerek
  ``src/content/author-profile``; cwd KULLANILMAZ) ile canonical dizin çözülür;
  ``CanonicalProfileRepository`` hem ``deps.profile_knowledge`` (v2 profil RAG,
  pinlenmiş sürüm) hem legacy ``deps.profile_repository`` (v1 A9 yolu; özet
  aynı canonical kaynaktan türetilir) olarak bağlanır. Dizin çözülemezse servis
  makale/genel akışlar için YİNE başlar; profil bağımlılığı her çağrıda
  ``ProfileSourceError`` (→ ``config_error``) üreten açık bir depoyla
  değiştirilir — üretimde sahte sağlayıcıya veya kaynaksız modele düşülmez.
- **Wire sürümleri (K4):** v1 ve v2 execute/control kuyruklarının dördü de
  tüketilir (``agent.execute.q``, ``agent.execute.v2.q``, ``agent.control.q``,
  ``agent.control.v2.q``); her tüketici kendi kuyruğunun sürümünü kabul eder.
  DB havuzu ``agent.worker_wire_max=2`` bildirir (claim izolasyonu, 0005).
- **Paralel yaşam:** intake tüketimi + worker ``run_forever`` + outbox relay
  döngüsü + control tüketimi + deadline reaper ``asyncio`` görevleriyle
  birlikte çalışır; SIGINT/SIGTERM'de düzgün kapanır (görevler iptal edilip
  beklenir, bağlantılar/havuz kapatılır — istisna bastırılmaz).

Bu modül çerçevesiz, yalın ``asyncio`` kompozisyondur; iş mantığı taşımaz.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

# ``python -m app.service_main`` (namespace paketi) ile koşumda agent_core ve
# messaging paketlerinin import kökü bu dosyanın bulunduğu ``app`` dizinidir;
# kök dizinden çalıştırıldığında sys.path'te olmayabilir. Idempotent ekleme.
_APP_DIR = str(Path(__file__).resolve().parent)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from env_file import env_bool, env_float, env_int, load_env_file  # noqa: E402

from agent_core.adapters import (  # noqa: E402
    ProviderSettings,
    build_content_repository_from_env,
    build_model_provider_from_env,
    resolve_model_provider,
)
from agent_core.adapters.local_embedding import (  # noqa: E402
    LOCAL_EMBEDDING_CONFIG,
    LocalHashingEmbedding,
)
from agent_core.profile import (  # noqa: E402
    CanonicalProfileRepository,
    ProfileSourceError,
    resolve_profile_dir,
)
from agent_core.qa.retrieval import SnapshotRetriever  # noqa: E402

from .messaging.connection import connect_broker  # noqa: E402
from .messaging.consumer import BrokerConsumer  # noqa: E402
from .messaging.control import ControlConsumerService  # noqa: E402
from .messaging.control_driver import CollaborationResumeDriver  # noqa: E402
from .messaging.control_store import ControlStore  # noqa: E402
from .messaging.db import AgentDbSettings, connect_pool  # noqa: E402
from .messaging.events import AgentEventPublisher  # noqa: E402
from .messaging.intake import IntakeService  # noqa: E402
from .messaging.job_store import JobStore  # noqa: E402
from .messaging.outbox import OutboxRelay  # noqa: E402
from .messaging.publisher import BrokerPublisher  # noqa: E402
from .messaging.reaper import DeadlineReaper  # noqa: E402
from .messaging.settings import BrokerSettings, from_env as broker_settings_from_env  # noqa: E402
from .messaging.contracts import SUPPORTED_SCHEMA_VERSIONS  # noqa: E402
from .messaging.topology import (  # noqa: E402
    control_queue_for,
    declare_topology,
    execute_queue_for,
)
from .messaging.worker import ExecutionDependencies, ExecutionWorker, WorkerSettings  # noqa: E402

__all__ = [
    "ServiceComponents",
    "UnavailableProfileRepository",
    "build_components_async",
    "main",
    "resolve_model",
    "resolve_profile_repository",
    "run_service",
]

logger = logging.getLogger("service_main")


def resolve_model() -> Any:
    """Model bağlama: anahtar doluysa gerçek sağlayıcı, boşsa MEVCUT davranış."""

    provider = build_model_provider_from_env()
    if provider is not None:
        logger.info("model sağlayıcı: OpenAI-uyumlu streaming (AGENT_LLM_API_KEY dolu)")
        return provider
    # Anahtar yok: mevcut çözümleyici davranışı birebir (anlaşılır config_error
    # üretir; test ortamında test sağlayıcısına izin verir).
    return resolve_model_provider(ProviderSettings())


class UnavailableProfileRepository:
    """Canonical profil kaynağı çözülemediğinde enjekte edilen AÇIK hata deposu.

    Hem ``ProfileKnowledgeRepository`` (``active_snapshot``/``load``) hem legacy
    ``ProfileRepository`` (``get_profile``) çağrıları her seferinde
    ``ProfileSourceError`` (``config_error``) yükseltir: profil run'ı anlaşılır
    failed/config_error ile kapanır; servis makale/genel akışlar için çalışmayı
    sürdürür. Sahte veri veya kaynaksız model cevabı ÜRETMEZ.
    """

    is_test_double = False

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def _fail(self) -> ProfileSourceError:
        return ProfileSourceError(f"canonical profil kaynağı kullanılamıyor: {self.reason}")

    def active_snapshot(self) -> Any:
        raise self._fail()

    def load(self, snapshot: Any) -> Any:
        raise self._fail()

    async def get_profile(self) -> Any:
        raise self._fail()


def resolve_profile_repository(environ: dict[str, str] | None = None) -> Any:
    """Canonical profil deposunu kurar (cwd'den bağımsız yol çözümü).

    Dönüş: ``CanonicalProfileRepository`` veya çözüm başarısızsa
    ``UnavailableProfileRepository`` (hata loglanır; servis yine başlar). Kaynak
    içeriğinin (hash/manifest) doğrulaması her okumada depo tarafından yapılır.
    """

    try:
        directory = resolve_profile_dir(environ)
    except ProfileSourceError as error:
        logger.error("profil kaynağı çözülemedi; profil run'ları config_error üretecek: %s", error.message)
        return UnavailableProfileRepository(error.message)
    logger.info("profil kaynağı: canonical dizin bağlandı (%s)", directory.name)
    return CanonicalProfileRepository(directory)


class ServiceComponents:
    """Kurulan servis bileşenleri; smoke testleri sahte bileşenlerle kurar."""

    def __init__(
        self,
        *,
        pool: Any,
        store: JobStore,
        publisher: AgentEventPublisher,
        worker: ExecutionWorker,
        intake: IntakeService,
        control_service: ControlConsumerService,
        reaper: DeadlineReaper,
        broker: BrokerSettings,
        relay: OutboxRelay | None = None,
        execute_consumer: Any | None = None,
        control_consumer: Any | None = None,
        content: Any | None = None,
        intakes: dict[int, IntakeService] | None = None,
        control_services: dict[int, ControlConsumerService] | None = None,
        profile_repository: Any | None = None,
    ) -> None:
        self.pool = pool
        self.store = store
        self.publisher = publisher
        self.worker = worker
        self.intake = intake
        self.control_service = control_service
        self.reaper = reaper
        self.broker = broker
        self.relay = relay
        self.execute_consumer = execute_consumer
        self.control_consumer = control_consumer
        self.content = content
        #: Sürüm → execute intake servisi (v1 ``agent.execute.q``, v2 ``agent.execute.v2.q``).
        self.intakes = intakes if intakes is not None else {1: intake}
        #: Sürüm → kontrol servisi (v1 ``agent.control.q``, v2 ``agent.control.v2.q``).
        self.control_services = control_services if control_services is not None else {1: control_service}
        #: Canonical profil deposu (veya açık hata deposu); worker'a bağlıdır.
        self.profile_repository = profile_repository
        #: run_service kurar: sürüm → tüketici.
        self.execute_consumers: dict[int, Any] = {}
        self.control_consumers: dict[int, Any] = {}


async def build_components_async(
    *,
    db_settings: AgentDbSettings,
    broker: BrokerSettings,
    environ: dict[str, str] | None = None,
    pool: Any = None,
    model: Any | None = None,
    content: Any | None = None,
    profile_repository: Any | None = None,
) -> ServiceComponents:
    """Bileşenleri kurar; havuz verilmediyse açar (async kompozisyon).

    Relay publisher'ı broker bağlantısı gerektirdiğinden ``run_service``
    kurar; burada bileşen yalnız DB köklü olanlar kurulur. ``content``
    verilmezse ``AGENT_CONTENT_BASE_URL`` doluysa HTTP içerik deposu bağlanır,
    boşsa depo bağlı kalmaz (MEVCUT davranış). ``profile_repository``
    verilmezse ``resolve_profile_repository(env)`` canonical depoyu kurar.
    """

    env = os.environ if environ is None else environ
    if pool is None:
        pool = await connect_pool(db_settings)

    store = JobStore(pool, schema=db_settings.schema)
    event_publisher = AgentEventPublisher(pool, schema=db_settings.schema)
    control_store = ControlStore(pool, schema=db_settings.schema)

    resolved_model = model if model is not None else resolve_model()
    resolved_content = content if content is not None else build_content_repository_from_env(env)
    # K7 geçişi: içerik deposu bağlıyken makale bağlamlı akışlar için yerel
    # bölüm araması kurulur (SnapshotRetriever + deterministik yerel gömme;
    # model çağrısı değildir — B8 pgvector'a kadar olan tasarım köprüsü).
    # Retriever yoksa çekirdek A1 tek-çağrı yoluna düşer: citation üretilemez
    # ve backend terminal guard'ı makale kapsamlı koşuyu failed yapar.
    resolved_retriever = None
    if resolved_content is not None:
        resolved_retriever = SnapshotRetriever(
            embedding_provider=LocalHashingEmbedding(),
            model_config=LOCAL_EMBEDDING_CONFIG,
        )
        logger.info("içerik deposu: HTTP iç uç (AGENT_CONTENT_BASE_URL dolu) + yerel bölüm araması")
    # Who am I: tek canonical kaynak hem v2 profil RAG'ine (pinlenmiş sürüm) hem
    # legacy A9 profil yoluna (özet aynı kaynaktan türetilir) bağlanır.
    resolved_profile = (
        profile_repository if profile_repository is not None else resolve_profile_repository(dict(env))
    )
    deps = ExecutionDependencies(
        model=resolved_model,
        content=resolved_content,
        retriever=resolved_retriever,
        profile_knowledge=resolved_profile,
        profile_repository=resolved_profile,
    )

    worker_settings = WorkerSettings(
        worker_id=env.get("AGENT_WORKER_ID", "agent-py-worker"),
        queue_classes=tuple(
            raw.strip() for raw in env.get("AGENT_WORKER_QUEUE_CLASSES", "fast,research").split(",") if raw.strip()
        ),
        lease_seconds=env_float("AGENT_WORKER_LEASE_SECONDS", 60.0),
        poll_interval_seconds=env_float("AGENT_WORKER_POLL_INTERVAL", 0.5),
        max_execution_attempts=env_int("AGENT_WORKER_MAX_ATTEMPTS", 3),
    )
    worker = ExecutionWorker(
        store,
        deps,
        settings=worker_settings,
        publisher=event_publisher,
        control_store=control_store,
    )
    # Sürüm başına intake/kontrol servisi: her kuyruk yalnız kendi sürümünü kabul
    # eder; aynı consumer_name (inbox idempotency) ve aynı depolar paylaşılır.
    intakes = {
        version: IntakeService(store, accepted_versions=(version,)) for version in SUPPORTED_SCHEMA_VERSIONS
    }
    intake = intakes[1]
    driver = CollaborationResumeDriver(
        worker,
        store,
        worker_id=worker_settings.worker_id,
        lease_seconds=worker_settings.lease_seconds,
    )
    control_services = {
        version: ControlConsumerService(control_store, resume_driver=driver, accepted_versions=(version,))
        for version in SUPPORTED_SCHEMA_VERSIONS
    }
    control_service = control_services[1]
    reaper = DeadlineReaper(control_store, interval_seconds=env_float("AGENT_REAPER_INTERVAL", 30.0))

    return ServiceComponents(
        pool=pool,
        store=store,
        publisher=event_publisher,
        worker=worker,
        intake=intake,
        control_service=control_service,
        reaper=reaper,
        broker=broker,
        content=resolved_content,
        intakes=intakes,
        control_services=control_services,
        profile_repository=resolved_profile,
    )


async def run_service(
    components: ServiceComponents,
    *,
    max_cycles: int | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Tüm bileşenleri paralel yaşatır; SIGINT/SIGTERM'de düzgün kapanır.

    ``stop`` (test/kompozisyon smoke'ı için): verilirse dış sinyal yerine bu
    olay kapanışı tetikler; ``None`` sinyal kolu kurulur.
    """

    external_stop = stop
    stop = stop if stop is not None else asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[int] = []
    if external_stop is None:
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, stop.set)
                installed.append(int(sig))
            except (NotImplementedError, RuntimeError):  # Windows: add_signal_handler yok
                signal.signal(sig, lambda *_: stop.set())
        if installed:
            logger.info("sinyal kolu kuruldu: %s", ", ".join(str(s) for s in installed))

    # Broker bağlantıları: execute + control tüketicileri ve relay publisher'ı.
    # D013: topoloji declarer'ı backend'dir; agent_svc üretim vhost'unda yalnız
    # events write + kuyruk read yetkilidir. Declare bu yüzden BAYRAKLA çalışır
    # (AGENT_TOPOLOGY_DECLARE=1): yalıtık geliştirme/test vhost'ları içindir;
    # üretim vhost'unda backend zaten declare etmiştir ve bayrak kapalı kalır.
    declare = env_bool("AGENT_TOPOLOGY_DECLARE", False)
    execute_conn = await connect_broker(components.broker)
    control_conn = await connect_broker(components.broker)
    relay_conn = await connect_broker(components.broker)
    if declare:
        channel = await relay_conn.channel(publisher_confirms=True)
        await declare_topology(channel)
        await channel.close()
    else:
        logger.info("topoloji declare atlandı (AGENT_TOPOLOGY_DECLARE kapalı; declarer: backend, D013)")
    relay_publisher = BrokerPublisher(relay_conn, ("blog.agent.events",), components.broker)
    await relay_publisher.start()
    components.relay = OutboxRelay(components.store, relay_publisher)

    # v1 + v2 kuyrukları (K4): yeni worker dördünü de tüketir; v2 kuyruklarında
    # tüketici varlığı backend'in üretici bariyerinin (readiness) ön koşuludur.
    execute_consumers = {
        version: BrokerConsumer(
            execute_conn,
            execute_queue_for(version),
            components.intakes[version].handle_delivery,
            components.broker,
        )
        for version in sorted(components.intakes)
    }
    control_consumers = {
        version: BrokerConsumer(
            control_conn,
            control_queue_for(version),
            components.control_services[version].handle_delivery,
            components.broker,
        )
        for version in sorted(components.control_services)
    }
    components.execute_consumers = execute_consumers
    components.control_consumers = control_consumers
    components.execute_consumer = execute_consumers.get(1)
    components.control_consumer = control_consumers.get(1)
    all_consumers = [*execute_consumers.values(), *control_consumers.values()]

    relay_interval = env_float("AGENT_RELAY_INTERVAL", 0.2)

    async def _relay_loop() -> None:
        while not stop.is_set():
            try:
                await components.relay.run_once()
            except Exception:  # relay hatası servisi öldürmez; sonraki çevrim dener
                logger.exception("outbox relay çevrimi başarısız")
            try:
                await asyncio.wait_for(stop.wait(), timeout=relay_interval)
            except TimeoutError:
                pass

    tasks: list[asyncio.Task[Any]] = [
        asyncio.create_task(components.worker.run_forever(max_cycles=max_cycles), name="worker"),
        asyncio.create_task(_relay_loop(), name="outbox-relay"),
        asyncio.create_task(components.reaper.run_forever(stop=stop), name="deadline-reaper"),
    ]
    started: list[Any] = []
    try:
        for consumer in all_consumers:
            await consumer.start()
            started.append(consumer)
        logger.info(
            "servis canlı: execute(v%s)+control(v%s) tüketimi, worker, relay, reaper",
            "/v".join(str(v) for v in sorted(execute_consumers)),
            "/v".join(str(v) for v in sorted(control_consumers)),
        )
        await stop.wait()
    finally:
        stop.set()
        for consumer in started:
            try:
                await consumer.stop()
            except Exception:
                logger.exception("consumer kapanışı başarısız")
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for task, result in zip(tasks, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                continue
            if isinstance(result, BaseException):
                logger.error("görev %s arıza ile bitti: %r", task.get_name(), result)
        try:
            await relay_publisher.close()
        except Exception:
            logger.exception("relay publisher kapanışı başarısız")
        if components.content is not None:
            try:
                await components.content.aclose()  # yalnız kendi kurduğu istemci kapanır
            except Exception:
                logger.exception("içerik deposu kapanışı başarısız")
        for conn in (execute_conn, control_conn, relay_conn):
            try:
                await conn.close()
            except Exception:
                logger.exception("broker bağlantısı kapatılamadı")
        try:
            await components.pool.close()
        except Exception:
            logger.exception("db havuzu kapatılamadı")
        logger.info("servis kapandı")


async def _async_main() -> int:
    # .env en önce yüklenir: AGENT_LOG_LEVEL dahil tüm değişkenler basicConfig
    # öncesi ortama düşer (gerçek ortam .env'i ezer — setdefault semantiği).
    loaded = load_env_file()
    logging.basicConfig(
        level=os.environ.get("AGENT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if loaded:
        # basicConfig sonrası: aksi hâlde handler yokken INFO görünmez.
        logger.info(".env yüklendi: %d değişken", len(loaded))
    else:
        logger.debug(".env bulunamadı")
    try:
        db_settings = AgentDbSettings(
            host=os.environ.get("AGENT_DB_HOST", "127.0.0.1"),
            port=env_int("AGENT_DB_PORT", 5432),
            user=os.environ.get("AGENT_DB_USER", "blogapp_user"),
            password=os.environ.get("AGENT_DB_PASSWORD", ""),
            database=os.environ.get("AGENT_DB_NAME", "blogdb_dev"),
            schema=os.environ.get("AGENT_DB_SCHEMA", "agent"),
        )
        components = await build_components_async(db_settings=db_settings, broker=broker_settings_from_env())
        await run_service(components)
        return 0
    except Exception:
        logger.exception("servis beklenmedik şekilde sonlandı")
        return 1


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    sys.exit(main())
