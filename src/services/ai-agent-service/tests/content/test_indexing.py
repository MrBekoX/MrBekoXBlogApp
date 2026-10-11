"""İndeks davranış testleri: idempotency, atomik revizyon, kaldırma, model değişimi.

Plan A3 kabul ölçütleri burada birebir karşılanır:
- "Aynı içerik iki kez indekslenmiyor" → ``test_same_content_is_not_indexed_twice``
- "Güncellenen makale yeni revizyonla bulunuyor" → ``test_updated_article_found_under_new_revision``
- "Bilinen kaldırma revizyonundan eski içerik getirilmiyor" → ``test_known_revision_removal_hides_old_content``

Async çağrılar kök paket kuralıyla ``run()`` ile senkron koşar (pytest-asyncio
bağımlılığı yoktur).
"""

from __future__ import annotations

import pytest

import fixtures
from agent_core.adapters.test_doubles import FakeEmbeddingProvider, PreCancelledToken
from agent_core.content import EmbeddingModelConfig, SearchQuery
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import compute_content_hash

from fixtures import MODEL_CONFIG, run


def small_model(model_id: str) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        model_id=model_id,
        dimensions=MODEL_CONFIG.dimensions,
        max_chunk_tokens=256,
        chars_per_token=4,
    )


def test_same_content_is_not_indexed_twice() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    first = run(
        index.index_article(sample_snapshot, embedding_provider=provider, model_config=MODEL_CONFIG)
    )
    second = run(
        index.index_article(sample_snapshot, embedding_provider=provider, model_config=MODEL_CONFIG)
    )
    assert first.indexed is True
    assert second.indexed is False
    assert second.chunk_count == first.chunk_count
    assert provider.call_count == 1  # ikinci çağrı embedding üretmez
    assert index.chunk_count(sample_snapshot.article_id) == first.chunk_count


def test_updated_article_found_under_new_revision() -> None:
    index = fixtures.make_index()
    # Hashing sağlayıcı sözcük örtüşmesini vektöre taşır; düz vektörlü
    # FakeEmbeddingProvider anlamsal ayrım yapamaz (tüm cosine'lar 1.0).
    provider = fixtures.HashingEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    old_snapshot = fixtures.make_index_snapshot(
        "Eski kurulum adımları venv sanal ortamı kurar.", revision=3
    )
    run(index.index_article(old_snapshot, embedding_provider=provider, model_config=MODEL_CONFIG))
    new_snapshot = fixtures.make_index_snapshot(
        "Yeni kurulum adımları pipx aracıyla yapılır.", revision=4
    )
    result = run(
        index.index_article(new_snapshot, embedding_provider=provider, model_config=MODEL_CONFIG)
    )
    assert result.indexed is True
    hits = run(
        index.search(
            SearchQuery(text="pipx"),
            embedding_provider=provider,
            model_config=MODEL_CONFIG,
        )
    )
    assert hits, "yeni revizyon bulunmalıdır"
    assert {hit.record.article_revision for hit in hits} == {4}
    stale_hits = run(
        index.search(
            SearchQuery(text="venv"),
            embedding_provider=provider,
            model_config=MODEL_CONFIG,
        )
    )
    assert stale_hits == []


def test_same_revision_with_different_hash_is_rejected() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    run(index.index_article(sample_snapshot, embedding_provider=provider, model_config=MODEL_CONFIG))
    tampered = sample_snapshot.model_copy(
        update={"content_hash": compute_content_hash("farklı içerik")}
    )
    with pytest.raises(PortError) as excinfo:
        run(index.index_article(tampered, embedding_provider=provider, model_config=MODEL_CONFIG))
    assert excinfo.value.code is AgentErrorCode.STALE_SNAPSHOT


def test_late_arriving_older_revision_is_rejected() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    newer = sample_snapshot.model_copy(update={"article_revision": 5})
    run(index.index_article(newer, embedding_provider=provider, model_config=MODEL_CONFIG))
    older = sample_snapshot.model_copy(update={"article_revision": 4})
    with pytest.raises(PortError) as excinfo:
        run(index.index_article(older, embedding_provider=provider, model_config=MODEL_CONFIG))
    assert excinfo.value.code is AgentErrorCode.STALE_SNAPSHOT


def test_failed_embed_leaves_previous_revision_intact() -> None:
    index = fixtures.make_index()
    working = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    current = fixtures.make_index_snapshot("Kararlı içerik gövdesi.", revision=3)
    run(index.index_article(current, embedding_provider=working, model_config=MODEL_CONFIG))
    failing = fixtures.FailingEmbeddingProvider()
    updated = fixtures.make_index_snapshot("Kararlı içerik gövdesi güncellendi.", revision=4)
    with pytest.raises(PortError) as excinfo:
        run(index.index_article(updated, embedding_provider=failing, model_config=MODEL_CONFIG))
    assert excinfo.value.code is AgentErrorCode.PROVIDER_ERROR
    # Atomiklik: bozuk revizyon kısmen yazılmaz; eski durum aranır kalır.
    assert index.chunk_count(current.article_id) > 0
    hits = run(
        index.search(
            SearchQuery(text="kararlı içerik"),
            embedding_provider=working,
            model_config=MODEL_CONFIG,
        )
    )
    assert {hit.record.article_revision for hit in hits} == {3}


def test_known_revision_removal_hides_old_content_and_invalidates_cache() -> None:
    index = fixtures.make_index()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    snapshot = fixtures.make_index_snapshot("Kaldırılacak deney kaydı.", revision=7)
    run(index.index_article(snapshot, embedding_provider=provider, model_config=MODEL_CONFIG))
    query = SearchQuery(text="kaldırılacak deney kaydı")
    first = run(index.search(query, embedding_provider=provider, model_config=MODEL_CONFIG))
    assert first  # önbelleğe girdi
    calls_after_first = provider.call_count
    repeat = run(index.search(query, embedding_provider=provider, model_config=MODEL_CONFIG))
    assert [h.record.chunk_index for h in repeat] == [h.record.chunk_index for h in first]
    assert provider.call_count == calls_after_first  # tekrar sorgu gömmedi

    removal = run(index.remove_article(snapshot.article_id, article_revision=7))
    assert removal.removed is True
    assert removal.removed_chunks == len(first)

    after = run(index.search(query, embedding_provider=provider, model_config=MODEL_CONFIG))
    assert after == []  # kaldırma revizyonundan eski içerik getirilemez
    assert index.chunk_count(snapshot.article_id) == 0


def test_stale_removal_keeps_newer_content() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    newer = sample_snapshot.model_copy(update={"article_revision": 9})
    run(index.index_article(newer, embedding_provider=provider, model_config=MODEL_CONFIG))
    removal = run(index.remove_article(newer.article_id, article_revision=8))
    assert removal.removed is False
    assert index.chunk_count(newer.article_id) > 0


def test_removal_of_missing_article_is_idempotent() -> None:
    index = fixtures.make_index()
    removal = run(index.remove_article("boyle-bir-yazi-yok", article_revision=1))
    assert removal.removed is False
    assert removal.removed_chunks == 0


def test_embedding_model_change_requires_reindex() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    run(index.index_article(sample_snapshot, embedding_provider=provider, model_config=MODEL_CONFIG))
    other = small_model("different-model")
    with pytest.raises(PortError) as excinfo:
        run(
            index.search(
                SearchQuery(text="kurulum"),
                embedding_provider=provider,
                model_config=other,
            )
        )
    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    with pytest.raises(PortError):
        run(index.index_article(sample_snapshot, embedding_provider=provider, model_config=other))


def test_reindex_rebuilds_whole_index_atomically() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    second = fixtures.make_index_snapshot(
        "İkinci makale gövdesi.", article_id="post-2", slug="ikinci"
    )
    run(index.index_article(sample_snapshot, embedding_provider=provider, model_config=MODEL_CONFIG))
    run(index.index_article(second, embedding_provider=provider, model_config=MODEL_CONFIG))

    small = small_model("small-model")
    results = run(
        index.reindex([sample_snapshot], embedding_provider=provider, model_config=small)
    )
    assert [item.article_id for item in results] == [sample_snapshot.article_id]
    assert index.article_ids() == [sample_snapshot.article_id]  # eski küçük tek atamayla değişti
    assert index.model_id == small.model_id
    hits = run(
        index.search(
            SearchQuery(text="tip ipuçları"),
            embedding_provider=provider,
            model_config=small,
        )
    )
    assert hits  # yeni modelle arama çalışır


def test_cancellation_stops_indexing_and_search() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    token = PreCancelledToken("kullanıcı iptal etti")
    with pytest.raises(PortError) as excinfo:
        run(
            index.index_article(
                sample_snapshot,
                embedding_provider=provider,
                model_config=MODEL_CONFIG,
                cancel=token,
            )
        )
    assert excinfo.value.code is AgentErrorCode.CANCELLED
    assert provider.call_count == 0
    run(index.index_article(sample_snapshot, embedding_provider=provider, model_config=MODEL_CONFIG))
    with pytest.raises(PortError):
        run(
            index.search(
                SearchQuery(text="kurulum"),
                embedding_provider=provider,
                model_config=MODEL_CONFIG,
                cancel=token,
            )
        )


def test_canonical_url_template_is_validated() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    with pytest.raises(PortError) as excinfo:
        run(
            index.index_article(
                sample_snapshot,
                embedding_provider=provider,
                model_config=MODEL_CONFIG,
                canonical_url_template="https://mrbekox.dev/blog/kesim-eksik",
            )
        )
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR


def test_indexed_chunks_carry_contract_fields() -> None:
    index = fixtures.make_index()
    sample_snapshot = fixtures.make_sample_snapshot()
    provider = FakeEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    run(
        index.index_article(
            sample_snapshot,
            embedding_provider=provider,
            model_config=MODEL_CONFIG,
            canonical_url_template="https://mrbekox.dev/blog/{slug}",
        )
    )
    hits = run(
        index.search(
            SearchQuery(text="Kurulum", top_k=8),
            embedding_provider=provider,
            model_config=MODEL_CONFIG,
        )
    )
    assert hits
    for hit in hits:
        record = hit.record
        assert record.content_hash == sample_snapshot.content_hash
        assert record.article_revision == sample_snapshot.article_revision
        assert record.heading_path[0] == sample_snapshot.title
        assert record.anchor
        assert record.canonical_url is not None
        assert record.canonical_url.startswith(f"https://mrbekox.dev/blog/{sample_snapshot.slug}#")
        assert record.published is True
        assert record.language == "tr"
