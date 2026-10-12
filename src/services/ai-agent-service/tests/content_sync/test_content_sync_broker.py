"""B8 gerçek broker testleri: ``blog.content.events`` → ``agent.content.q`` uçtan uca.

Ortam: ``blogapp_dev_b8`` vhost (L009 — bu pakete özel), gerçek RabbitMQ 4.2.
Backend yayını ``backend_svc`` (content exchange yazma izni), tüketim ``agent_svc``
(B2 rol modeli) ile yapılır; topoloji admin bağlantısıyla declare edilmiştir.

Kabul ölçütlerinden karşılananlar:
- kaldırma: tombstone mesajı gerçek kuyruktan tüketilir, A3 indeksi boşalır,
- olayların ters gelmesi: eski revizyon sonradan teslim edilir, durum gerilemez,
- ilk sync: batch + completed gerçek kuyruktan işlenir,
- şema hatalı mesaj: DLX'e düşer (requeue döngüsü yok).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agent_core.adapters.test_doubles import FakeEmbeddingProvider
from agent_core.content.config import EmbeddingModelConfig
from agent_core.content.index import InMemoryContentIndex
from agent_core.models import ArticleSnapshot, compute_content_hash
from messaging import (
    BrokerPublisher,
    ContentConsumerService,
    ContentIndexProjector,
    ContentSyncState,
    build_content_consumer,
    connect_broker,
)
from messaging.topology import CONTENT_EXCHANGE, CONTENT_QUEUE

from .conftest import (
    BACKEND_USER,
    AGENT_USER,
    make_article_changed,
    make_sync_batch,
    make_sync_completed,
    make_settings,
    queue_depth,
    run,
    wait_until,
)

MODEL_CONFIG = EmbeddingModelConfig(model_id="test-embed", dimensions=4)


class _ConsumerHarness:
    """Consumer + publisher ömür yönetimi (tek test içinde açık başlat/durdur)."""

    def __init__(self, service: ContentConsumerService) -> None:
        self.service = service
        self._publisher_conn = None
        self._publisher = None
        self._consumer_conn = None
        self._consumer = None

    async def start(self) -> None:
        self._publisher_conn = await connect_broker(
            make_settings(*BACKEND_USER, client_name="b8-backend-publisher")
        )
        self._publisher = BrokerPublisher(
            self._publisher_conn,
            (CONTENT_EXCHANGE,),
            make_settings(*BACKEND_USER, client_name="b8-backend-publisher"),
        )
        await self._publisher.start()
        self._consumer_conn = await connect_broker(
            make_settings(*AGENT_USER, client_name="b8-agent-consumer")
        )
        self._consumer = build_content_consumer(self._consumer_conn, self.service)
        await self._consumer.start()

    async def stop(self) -> None:
        # BrokerPublisher uzun ömürlüdür ve stop() içermez: bağlantı kapanışı kanalı da kapatır.
        for closer in (
            self._consumer.stop() if self._consumer else None,
            self._consumer_conn.close() if self._consumer_conn else None,
            self._publisher_conn.close() if self._publisher_conn else None,
        ):
            if closer is not None:
                await closer

    async def publish(self, document: dict) -> None:
        await self._publisher.publish_raw(
            CONTENT_EXCHANGE,
            f"{document['message_type']}.v1",
            json.dumps(document).encode("utf-8"),
            message_id=document["message_id"],
            correlation_id=document["correlation_id"],
            type_name=document["message_type"],
        )


def _settings_for(username: str, password: str):
    return make_settings(username, password)


@pytest.fixture()
def harness():
    state = ContentSyncState()
    service = ContentConsumerService(state)
    instance = _ConsumerHarness(service)

    async def _open() -> ContentSyncState:
        await instance.start()
        return state

    run(_open())
    try:
        yield instance
    finally:
        run(instance.stop())


async def _wait_state(condition, timeout_seconds: float = 15.0) -> None:
    from .conftest import wait_until as _wait

    await _wait(condition, timeout_seconds=timeout_seconds)


class TestRealBrokerContentFlow:
    def test_update_then_out_of_order_old_revision(self, harness):
        async def _flow() -> None:
            await harness.publish(make_article_changed(article_id="post-live", revision=3))
            await _wait_state(lambda: harness.service.state.known_revision("post-live") is not None)
            await harness.publish(make_article_changed(article_id="post-live", revision=2))
            await _wait_state(lambda: queue_depth(CONTENT_QUEUE) == 0)

        run(_flow())
        # Eski revizyon yok sayıldı: durum yeni revizyonda kaldı (olayların ters gelmesi).
        assert harness.service.state.known_revision("post-live") == (3, "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae")

    def test_tombstone_consumed_from_real_queue(self, harness):
        from agent_core.content.index import InMemoryContentIndex
        from agent_core.models import ArticleSnapshot, compute_content_hash
        from datetime import datetime, timezone

        index = InMemoryContentIndex()
        now = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)

        async def _seed() -> None:
            await index.index_article(
                ArticleSnapshot(
                    article_id="post-rem",
                    slug="post-rem",
                    title="Kaldırılacak",
                    content="# Icerik\n\nGovde.",
                    content_hash=compute_content_hash("# Icerik\n\nGovde."),
                    article_revision=2,
                    language="tr",
                    fetched_at=now,
                ),
                embedding_provider=FakeEmbeddingProvider(),
                model_config=MODEL_CONFIG,
            )

        run(_seed())
        assert index.chunk_count("post-rem") > 0

        projector = ContentIndexProjector(
            index, embedding_provider=FakeEmbeddingProvider(), model_config=MODEL_CONFIG
        )
        harness.service.projector = projector

        async def _flow() -> None:
            await harness.publish(
                make_article_changed(article_id="post-rem", revision=3, action="unpublished")
            )
            await _wait_state(lambda: queue_depth(CONTENT_QUEUE) == 0)

        run(_flow())
        assert index.chunk_count("post-rem") == 0
        assert harness.service.state.latest_removal_revision("post-rem") == 3

    def test_initial_sync_batch_and_completed(self, harness):
        sync_id = "11111111-1111-4111-8111-111111111111"

        async def _flow() -> None:
            await harness.publish(
                make_sync_batch(
                    sync_id=sync_id,
                    batch_index=0,
                    total_batches=1,
                    items=[{"article_id": "s-1", "article_revision": 1, "content_hash": "a" * 64}],
                )
            )
            await harness.publish(make_sync_completed(sync_id=sync_id, item_count=1))
            await _wait_state(lambda: queue_depth(CONTENT_QUEUE) == 0)

        run(_flow())
        assert harness.service.state.known_revision("s-1") == (1, "a" * 64)
        report = harness.service.state.sync_report(sync_id)
        assert report is not None
        assert report.completed and not report.incomplete
        assert not report.item_count_mismatch

    def test_invalid_contract_message_goes_to_dlq(self, harness):
        invalid = make_article_changed(article_id="post-bad", revision=1)
        invalid["producer"] = "agent-py"  # backend→agent içerik olayına izinli üretici değil

        async def _flow() -> None:
            await harness.publish(invalid)
            await _wait_state(lambda: queue_depth(f"{CONTENT_QUEUE}.dlq") >= 1)

        run(_flow())
        assert harness.service.state.known_revision("post-bad") is None
