"""B8 içerik consumer servis testleri: B1 doğrulama, tür politikası, indeks etkisi.

Broker'sız akış: ``handle_delivery`` bytes + sahte mesajla çağrılır; gerçek broker
teslimi ``test_content_sync_broker.py`` içindedir. Async akış paylaşımlı loop'taki
``run()`` ile çalışır (pytest-asyncio'suz; B4/B5 deseni).
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
    ContentConsumerService,
    ContentIndexProjector,
    ContentPolicyError,
    ContentSyncState,
)
from messaging.contracts import AgentContractError, parse_envelope

from .conftest import make_article_changed, read_fixture, run

MODEL_CONFIG = EmbeddingModelConfig(model_id="test-embed", dimensions=4)
NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)

EXECUTE_FIXTURE_HASH = "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"


class _FakeMessage:
    def __init__(self, message_id: str = "test-message") -> None:
        self.message_id = message_id


class FakeContentFetcher:
    """(article_id, revision) → ArticleSnapshot köprüsü (K7); test double."""

    is_test_double = True

    def __init__(self, bodies: dict[tuple[str, int], str]) -> None:
        self._bodies = bodies
        self.calls: list[tuple[str, int]] = []

    async def fetch(self, article_id: str, article_revision: int) -> ArticleSnapshot:
        self.calls.append((article_id, article_revision))
        content = self._bodies[(article_id, article_revision)]
        return ArticleSnapshot(
            article_id=article_id,
            slug=f"slug-{article_id}",
            title=f"Makale {article_id}",
            content=content,
            content_hash=compute_content_hash(content),
            article_revision=article_revision,
            language="tr",
            fetched_at=NOW,
        )


def envelope_bytes(document: dict) -> bytes:
    return json.dumps(document).encode("utf-8")


def make_service(state: ContentSyncState | None = None, projector=None) -> ContentConsumerService:
    return ContentConsumerService(state if state is not None else ContentSyncState(), projector=projector)


class TestPolicyAndValidation:
    def test_valid_article_changed_envelope_is_applied(self):
        service = make_service()
        raw = envelope_bytes(make_article_changed(article_id="post-9", revision=4))
        outcome = run(service.handle_delivery(raw, _FakeMessage()))
        assert outcome.applied
        assert service.state.known_revision("post-9") == (4, EXECUTE_FIXTURE_HASH)

    def test_contract_violation_raises_for_dlx(self):
        # Yanlış üretici (agent-py backend→agent içerik olayı yayınlayamaz): kalıcı
        # sözleşme ihlali → istisna B2 consumer tabanında nack(requeue=False) → DLX.
        service = make_service()
        raw = envelope_bytes({**make_article_changed(revision=1), "producer": "agent-py"})
        with pytest.raises(AgentContractError):
            run(service.handle_delivery(raw, _FakeMessage()))

    def test_malformed_body_raises_for_dlx(self):
        service = make_service()
        with pytest.raises(AgentContractError):
            run(service.handle_delivery(b"not-json", _FakeMessage()))

    def test_non_content_type_is_policy_error(self):
        service = make_service()
        fixture = read_fixture("valid/agent.execute.requested.json")
        with pytest.raises(ContentPolicyError):
            run(service.handle_delivery(envelope_bytes(fixture), _FakeMessage()))


class TestIndexProjector:
    def test_tombstone_removes_chunks_and_cache(self):
        # Önce indekslenmiş makale: tombstone → A3 kaldırma iş modeli (parçalar +
        # makale arama önbelleği tek çağrıda düşer).
        index = InMemoryContentIndex()
        snapshot = ArticleSnapshot(
            article_id="post-1",
            slug="post-1",
            title="Makale",
            content="# Baslik\n\nIcerik govdesi.",
            content_hash=compute_content_hash("# Baslik\n\nIcerik govdesi."),
            article_revision=3,
            language="tr",
            fetched_at=NOW,
        )
        run(
            index.index_article(
                snapshot,
                embedding_provider=FakeEmbeddingProvider(),
                model_config=MODEL_CONFIG,
            )
        )
        assert index.chunk_count("post-1") > 0

        state = ContentSyncState()
        projector = ContentIndexProjector(
            index, embedding_provider=FakeEmbeddingProvider(), model_config=MODEL_CONFIG
        )
        service = make_service(state, projector)
        document = make_article_changed(article_id="post-1", revision=4, action="unpublished")
        outcome = run(service.handle_delivery(envelope_bytes(document), _FakeMessage()))
        assert outcome.applied and outcome.reason == "removed"
        assert index.chunk_count("post-1") == 0

    def test_updated_with_fetcher_indexes_new_revision(self):
        index = InMemoryContentIndex()
        body = "# Yeni\n\nGuncel icerik."
        fetcher = FakeContentFetcher({("post-2", 5): body})
        state = ContentSyncState()
        projector = ContentIndexProjector(
            index,
            embedding_provider=FakeEmbeddingProvider(),
            model_config=MODEL_CONFIG,
            content_fetcher=fetcher,
        )
        service = make_service(state, projector)
        outcome = run(
            service.handle_delivery(
                envelope_bytes(
                    make_article_changed(
                        article_id="post-2",
                        revision=5,
                        content_hash=compute_content_hash(body),
                    )
                ),
                _FakeMessage(),
            )
        )
        assert outcome.applied
        assert index.chunk_count("post-2") > 0
        assert fetcher.calls == [("post-2", 5)]

    def test_updated_with_mismatched_fetched_hash_records_conflict(self):
        index = InMemoryContentIndex()

        class MismatchedFetcher(FakeContentFetcher):
            async def fetch(self, article_id: str, article_revision: int) -> ArticleSnapshot:
                snapshot = await super().fetch(article_id, article_revision)
                return snapshot.model_copy(update={"content_hash": "f" * 64})

        fetcher = MismatchedFetcher({("post-4", 2): "# Baskasi\n\nFarkli icerik."})
        state = ContentSyncState()
        projector = ContentIndexProjector(
            index,
            embedding_provider=FakeEmbeddingProvider(),
            model_config=MODEL_CONFIG,
            content_fetcher=fetcher,
        )
        service = make_service(state, projector)
        outcome = run(
            service.handle_delivery(
                envelope_bytes(make_article_changed(article_id="post-4", revision=2)),
                _FakeMessage(),
            )
        )
        assert outcome.applied
        assert len(state.conflicts) == 1
        assert index.chunk_count("post-4") == 0  # hash uyuşmayan gövde indekslenmez

    def test_updated_without_fetcher_is_state_only(self):
        index = InMemoryContentIndex()
        state = ContentSyncState()
        projector = ContentIndexProjector(
            index, embedding_provider=FakeEmbeddingProvider(), model_config=MODEL_CONFIG
        )
        service = make_service(state, projector)
        outcome = run(
            service.handle_delivery(
                envelope_bytes(make_article_changed(article_id="post-3", revision=1)),
                _FakeMessage(),
            )
        )
        assert outcome.applied
        # Gövde köprüsü yok: indeks dokunulmaz, salt revizyon durumu uygulanır.
        assert index.chunk_count("post-3") == 0
        assert state.known_revision("post-3") is not None
