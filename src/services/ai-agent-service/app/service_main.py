"""Production worker: real remote providers, durable PostgreSQL retrieval and RabbitMQ.

Missing credentials or canonical content fail startup; no mock fallback exists.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from contextlib import AsyncExitStack
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
    EmbeddingProviderSettings,
    HttpContentRepository,
    OpenAiEmbeddingProvider,
    OpenAiModelProvider,
    build_embedding_provider_from_env,
    build_content_repository_from_env,
    build_model_provider_from_env,
)
from agent_core.content.postgres import PostgresContentIndex, PostgresEmbeddingCache  # noqa: E402
from agent_core.errors import AgentErrorCode, PortError  # noqa: E402
from agent_core.models import BudgetProfile  # noqa: E402
from agent_core.budget.policy import BudgetPolicy  # noqa: E402
from agent_core.budget.postgres import PostgresBudgetStore  # noqa: E402
from agent_core.budget.content_embedding import (  # noqa: E402
    ContentEmbeddingLimits, PostgresContentEmbeddingBudget, content_embedding_scope,
)
from agent_core.telemetry import configure_telemetry  # noqa: E402
from agent_core.profile import (  # noqa: E402
    CanonicalProfileRepository,
    resolve_profile_dir,
    ProfileEmbedding,
    ProfileRetriever,
)
from agent_core.qa.retrieval import SnapshotRetriever  # noqa: E402
from agent_core.web.config import research_tools_from_env  # noqa: E402

from .messaging.connection import connect_broker  # noqa: E402
from .messaging.content import ContentConsumerService, ContentIndexProjector, ContentSyncState, build_content_consumer  # noqa: E402
from .messaging.consumer import BrokerConsumer  # noqa: E402
from .messaging.control import ControlConsumerService  # noqa: E402
from .messaging.control_driver import CollaborationResumeDriver  # noqa: E402
from .messaging.control_store import ControlStore  # noqa: E402
from .messaging.db import AgentDbSettings, connect_pool, from_env as db_settings_from_env  # noqa: E402
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
    execute_queue_for,
)
from .messaging.worker import ExecutionDependencies, ExecutionWorker, WorkerSettings  # noqa: E402
from .messaging.fenced_checkpoint import FencedCheckpointStore  # noqa: E402
from .healthcheck import heartbeat_path  # noqa: E402

__all__ = [
    "ServiceComponents",
    "build_components_async",
    "main",
    "resolve_model",
    "resolve_profile_repository",
    "run_service",
]

logger = logging.getLogger("service_main")


def resolve_model(environ: dict[str, str] | None = None) -> Any:
    """Create the configured real model provider; missing settings fail startup."""

    provider = build_model_provider_from_env(environ)
    logger.info("model provider: configured remote streaming API")
    return provider


def resolve_profile_repository(environ: dict[str, str] | None = None) -> Any:
    """Resolve the mandatory canonical source; failures prevent startup."""

    directory = resolve_profile_dir(environ)
    logger.info("profil kaynağı: canonical dizin bağlandı (%s)", directory.name)
    return CanonicalProfileRepository(directory)


class ServiceComponents:
    """Production components owned by the running service lifecycle."""

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
        embedding: Any | None = None,
        model: Any | None = None,
        content_service: Any | None = None,
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
        #: Validated canonical profile source shared by both execution versions.
        self.profile_repository = profile_repository
        self.embedding = embedding
        self.model = model
        self.content_service = content_service
        #: run_service kurar: sürüm → tüketici.
        self.execute_consumers: dict[int, Any] = {}
        self.control_consumers: dict[int, Any] = {}


async def _close_startup_provider(resource: Any) -> None:
    """Release an owned provider while preserving the original startup error."""
    try:
        await asyncio.wait_for(resource.aclose(), timeout=10)
    except Exception:
        logger.error("Failed to close a provider during startup cleanup")


async def _close_startup_pool(pool: Any) -> None:
    try:
        await asyncio.wait_for(pool.close(), timeout=10)
    except Exception:
        pool.terminate()
        logger.error("Terminated the database pool during startup cleanup")


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
    """Validate local sources, then compose real providers and durable storage.

    Failed startup closes resources created here. Injected real resources remain
    owned by the caller on failure. Successful composition transfers lifecycle
    ownership to run_service. No provider requests are made during composition.
    """
    env = os.environ if environ is None else environ
    resolved_profile = profile_repository if profile_repository is not None else resolve_profile_repository(dict(env))
    if not isinstance(resolved_profile, CanonicalProfileRepository):
        raise PortError(
            AgentErrorCode.CONFIG_ERROR, "A canonical profile repository is required", port="service_main"
        )
    # Reading/verifying local canonical files must precede opening the DB pool.
    resolved_profile.load(resolved_profile.active_snapshot())
    async with AsyncExitStack() as startup:
        resolved_model = model if model is not None else resolve_model(dict(env))
        if model is None:
            startup.push_async_callback(_close_startup_provider, resolved_model)
        settings = EmbeddingProviderSettings.from_env(env)
        raw_embedding = build_embedding_provider_from_env(env)
        startup.push_async_callback(_close_startup_provider, raw_embedding)
        resolved_content = content if content is not None else build_content_repository_from_env(env)
        if content is None and resolved_content is not None:
            startup.push_async_callback(_close_startup_provider, resolved_content)
        if (
            not isinstance(resolved_model, OpenAiModelProvider)
            or not isinstance(raw_embedding, OpenAiEmbeddingProvider)
            or not isinstance(resolved_content, HttpContentRepository)
        ):
            raise PortError(
                AgentErrorCode.CONFIG_ERROR,
                "Real remote model, OpenAI embedding, and HTTP content providers are required",
                port="service_main",
            )
        if pool is None:
            pool = await connect_pool(db_settings)
            startup.push_async_callback(_close_startup_pool, pool)
        components = await _compose_components(
            db_settings=db_settings, broker=broker, env=dict(env), pool=pool,
            resolved_model=resolved_model, settings=settings, raw_embedding=raw_embedding,
            resolved_content=resolved_content, resolved_profile=resolved_profile,
        )
        startup.pop_all()
        return components


async def _compose_components(
    *, db_settings: AgentDbSettings, broker: BrokerSettings, env: dict[str, str], pool: Any,
    resolved_model: OpenAiModelProvider, settings: EmbeddingProviderSettings,
    raw_embedding: OpenAiEmbeddingProvider, resolved_content: HttpContentRepository,
    resolved_profile: CanonicalProfileRepository,
) -> ServiceComponents:
    store = JobStore(pool, schema=db_settings.schema)
    event_publisher = AgentEventPublisher(pool, schema=db_settings.schema)
    control_store = ControlStore(pool, schema=db_settings.schema)

    embedding = PostgresEmbeddingCache(pool, raw_embedding, settings.index_config, schema=db_settings.schema)
    index = PostgresContentIndex(pool, schema=db_settings.schema)
    canonical_url_template = env.get("AGENT_CANONICAL_URL_TEMPLATE") or None
    resolved_retriever = SnapshotRetriever(
        embedding_provider=embedding, model_config=settings.index_config, index=index,
        canonical_url_template=canonical_url_template,
    )
    state = ContentSyncState()
    # Restore revision/removal guards after a process restart.
    rows = await pool.fetch(f'SELECT article_id,revision,content_hash,deleted FROM "{db_settings.schema}".content_articles')
    state.restore_articles(rows)
    # Refuse startup on unmigrated durable state instead of accepting work that
    # cannot persist its continuation or reserve its first paid call.
    await pool.fetch(f'SELECT run_id,limits FROM "{db_settings.schema}".run_budgets LIMIT 0')
    await pool.fetch(f'SELECT reservation_id,status,actual_amount FROM "{db_settings.schema}".budget_reservations LIMIT 0')
    await pool.fetch(f'SELECT scope_id,token_limit,request_limit FROM "{db_settings.schema}".content_embedding_budgets LIMIT 0')
    await pool.fetch(f'SELECT reservation_id,status,actual_amount FROM "{db_settings.schema}".content_embedding_reservations LIMIT 0')
    await pool.fetch(f'SELECT run_id,checkpoint_id,payload,fencing_token,version FROM "{db_settings.schema}".job_checkpoints LIMIT 0')
    content_embedding_limits = ContentEmbeddingLimits.from_env(env)

    def content_budget(snapshot):
        scope_id = content_embedding_scope(snapshot, settings.index_config)
        return scope_id, PostgresContentEmbeddingBudget(
            pool, scope_id, content_embedding_limits, schema=db_settings.schema,
        )

    class ContentFetcher:
        async def fetch(self, article_id: str, article_revision: int) -> Any:
            return await resolved_content.get_article(article_id)

    content_service = ContentConsumerService(state, projector=ContentIndexProjector(
        index, embedding_provider=embedding, model_config=settings.index_config, content_fetcher=ContentFetcher(),
        canonical_url_template=canonical_url_template,
        embedding_budget_factory=content_budget,
    ))
    research_tools = research_tools_from_env(env)
    # Both profile execution paths share this already validated local source.
    deps = ExecutionDependencies(
        model=resolved_model,
        content=resolved_content,
        retriever=resolved_retriever,
        profile_knowledge=resolved_profile,
        profile_repository=resolved_profile,
        profile_retriever=ProfileRetriever(embedding=ProfileEmbedding(embedding, settings.index_config)),
        content_state=state,
        checkpoint_factory=lambda inner, run_id, fence: FencedCheckpointStore(
            inner, pool, run_id, fence, schema=db_settings.schema,
        ),
        web_tools=research_tools,
        budget_factory=lambda context, fence: PostgresBudgetStore(
            pool, BudgetPolicy.from_budget_profile(context.budget_profile,
                # Internal article retrieval remains bounded and available when
                # external tools are disabled: QA(3) + one analysis upgrade(9).
                max_tool_attempts=max(context.budget_profile.max_tool_calls, 12)),
            context.run_id, fence, schema=db_settings.schema),
    )

    worker_settings = WorkerSettings(
        # These limits are selected by the server, never by a client's profile
        # label. No configured search provider means no external search budget.
        budget_profile=BudgetProfile(name="standard", max_model_calls=16, max_total_tokens=32000,
            max_tool_calls=env_int("AGENT_MAX_TOOL_CALLS", 24, env),
            max_web_search_calls=env_int("AGENT_MAX_WEB_SEARCH_CALLS", 8, env) if research_tools is not None else 0,
            max_duration_seconds=600.0),
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
        embedding=embedding,
        model=resolved_model,
        content_service=content_service,
    )


async def run_service(
    components: ServiceComponents, *, max_cycles: int | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Run all consumers and supervise every long-running task."""
    external_stop = stop
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    if external_stop is None:
        for name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, stop.set)
                except (NotImplementedError, RuntimeError):
                    signal.signal(sig, lambda *_: stop.set())
    marker = heartbeat_path()
    marker.unlink(missing_ok=True)
    connections: list[Any] = []
    tasks: list[asyncio.Task[Any]] = []
    started: list[Any] = []
    relay_publisher = None
    try:
        for _ in range(3):
            connections.append(await connect_broker(components.broker))
        execute_conn, control_conn, relay_conn = connections
        if env_bool("AGENT_TOPOLOGY_DECLARE", False):
            raise RuntimeError("Production topology must be declared by the backend")
        relay_publisher = BrokerPublisher(relay_conn, ("blog.agent.events",), components.broker)
        await relay_publisher.start()
        components.relay = OutboxRelay(components.store, relay_publisher)
        components.execute_consumers = {
            version: BrokerConsumer(execute_conn, execute_queue_for(version), intake.handle_delivery, components.broker)
            for version, intake in components.intakes.items()
        }
        components.control_consumers = {
            version: BrokerConsumer(control_conn, control_queue_for(version), service.handle_delivery, components.broker)
            for version, service in components.control_services.items()
        }
        all_consumers = [*components.execute_consumers.values(), *components.control_consumers.values()]
        if components.content_service is None:
            raise RuntimeError("Persistent content synchronization is required")
        all_consumers.append(build_content_consumer(execute_conn, components.content_service, components.broker))
        for consumer in all_consumers:
            await consumer.start()
            started.append(consumer)

        async def relay_loop() -> None:
            while not stop.is_set():
                try:
                    await components.relay.run_once()
                except Exception:
                    logger.exception("Outbox relay cycle failed; retrying")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=env_float("AGENT_RELAY_INTERVAL", 0.5))
                except TimeoutError:
                    pass

        async def heartbeat() -> None:
            while not stop.is_set():
                marker.touch()
                await asyncio.sleep(5)

        tasks = [
            asyncio.create_task(components.worker.run_forever(max_cycles=max_cycles), name="worker"),
            asyncio.create_task(relay_loop(), name="outbox-relay"),
            asyncio.create_task(components.reaper.run_forever(stop=stop), name="deadline-reaper"),
            asyncio.create_task(heartbeat(), name="heartbeat"),
            asyncio.create_task(stop.wait(), name="shutdown"),
        ]
        logger.info("Worker ready: execute/control v1+v2, persistent content sync, real model and embeddings")
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            return
        for task in done:
            if task.get_name() != "shutdown":
                task.result()
                raise RuntimeError(f"Supervised task stopped unexpectedly: {task.get_name()}")
    finally:
        stop.set()
        marker.unlink(missing_ok=True)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for consumer in reversed(started):
            try:
                await consumer.stop()
            except Exception:
                logger.exception("Consumer shutdown failed")
        if relay_publisher is not None:
            try:
                await relay_publisher.close()
            except Exception:
                logger.exception("Relay publisher shutdown failed")
        for resource in (components.embedding, components.model, components.content):
            if resource is not None and hasattr(resource, "aclose"):
                try:
                    await resource.aclose()
                except Exception:
                    logger.exception("Provider shutdown failed")
        for connection in connections:
            try:
                await connection.close()
            except Exception:
                logger.exception("Broker shutdown failed")
        try:
            await asyncio.wait_for(components.pool.close(), timeout=10)
        except TimeoutError:
            components.pool.terminate()
        logger.info("Worker stopped")


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
    telemetry = None
    try:
        db_settings = db_settings_from_env()
        profile = resolve_profile_repository()
        profile.load(profile.active_snapshot())
        telemetry = configure_telemetry(os.environ)
        components = await build_components_async(db_settings=db_settings, broker=broker_settings_from_env(), profile_repository=profile)
        await run_service(components)
        return 0
    except Exception:
        logger.exception("servis beklenmedik şekilde sonlandı")
        return 1
    finally:
        if telemetry is not None:
            await asyncio.to_thread(telemetry.shutdown)


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    sys.exit(main())
