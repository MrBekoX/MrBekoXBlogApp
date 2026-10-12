"""Hibrit retrieval testleri: füzyon, filtre kaçırma yokluğu, önbellek, birim davranış.

Kabul ölçütü: "İlgisiz parçalar ve farklı makalenin parçaları filtrelerden
kaçamıyor" — filtreler skorlamadan önce uygulandığı için sızma yapısal olarak
olanaksızdır; testler bunu özdeş içerikli makalelerle kanıtlar. Async
çağrılar kök paket kuralıyla ``run()`` ile senkron koşar.
"""

from __future__ import annotations

import pytest

import fixtures
from agent_core.content import (
    InMemoryContentIndex,
    SearchFilters,
    SearchQuery,
    cosine_similarity,
    rrf_fuse,
)
from agent_core.content.models import IndexedChunk
from agent_core.content.retrieval import bm25_scores, tokenize
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import ArticleChunk

from fixtures import MODEL_CONFIG, run


def tip_ipucu_markdown() -> str:
    return (
        "# Python ipuçları\n\n"
        "## Tip ipuçları\n\n"
        "Fonksiyon imzalarında tip ipuçları okunabilirliği artırır.\n\n"
        "## Mutfak\n\n"
        "Mercimek çorbası için soğanı kavurun.\n\n"
        "## Gezi\n\n"
        "Kapadokya balon turu gün doğumuyla güzel.\n"
    )


def build_index_with(index: InMemoryContentIndex, markdown: str, **kwargs):
    provider = fixtures.HashingEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    snapshot = fixtures.make_index_snapshot(markdown, **kwargs)
    run(index.index_article(snapshot, embedding_provider=provider, model_config=MODEL_CONFIG))
    return provider, snapshot


def search(index: InMemoryContentIndex, provider, query: SearchQuery):
    return run(index.search(query, embedding_provider=provider, model_config=MODEL_CONFIG))


def test_relevant_chunk_ranks_first() -> None:
    index = fixtures.make_index()
    provider, _snapshot = build_index_with(index, tip_ipucu_markdown())
    hits = search(index, provider, SearchQuery(text="tip ipuçları fonksiyon imzası"))
    assert hits
    # İlgili bölüm hem anlamsal hem anahtar kelime sıralamasında birincidir;
    # füzyon sonucu da onu başa koyar. (Başlık yolu öneki tüm parçalarda
    # makale başlığı kovasını taşıdığı için diğer parçaların skoru sıfır
    # değildir; sıralama yine de ilgili bölümü ayırt eder.)
    assert hits[0].record.heading_path[-1] == "Tip ipuçları"
    assert hits[0].semantic_rank == 1
    assert hits[0].keyword_rank == 1
    assert hits[0].score > hits[1].score


def test_identical_content_of_other_article_cannot_leak_through_filters() -> None:
    index = fixtures.make_index()
    identical = "# Ortak\n\nOrtak gövde kod örneği içerir."
    provider_a, _ = build_index_with(index, identical, article_id="post-1", slug="post-bir")
    provider_b, _ = build_index_with(index, identical, article_id="post-2", slug="post-iki")
    hits = search(
        index,
        provider_a,
        SearchQuery(
            text="ortak gövde kod örneği",
            filters=SearchFilters(article_ids=frozenset({"post-1"})),
        ),
    )
    assert hits, "filtreli sorgu en az bir sonuç döndürmelidir"
    assert {hit.record.article_id for hit in hits} == {"post-1"}
    # Filtresiz aynı sorgu iki makaleyi de görür: içerik özdeştir, ayırt eden
    # tek şey filtre davranışıdır.
    unfiltered = search(index, provider_b, SearchQuery(text="ortak gövde kod örneği"))
    assert {hit.record.article_id for hit in unfiltered} == {"post-1", "post-2"}


def test_language_filter_excludes_other_language() -> None:
    index = fixtures.make_index()
    same = "# Setup\n\nInstall the package with pip."
    build_index_with(index, same, article_id="post-tr", language="tr")
    provider_en, _ = build_index_with(index, same, article_id="post-en", language="en")
    hits = search(
        index,
        provider_en,
        SearchQuery(text="install the package", filters=SearchFilters(language="tr")),
    )
    assert hits
    assert {hit.record.language for hit in hits} == {"tr"}


def test_published_filter_respects_all_states() -> None:
    index = fixtures.make_index()
    markdown = "# Taslak\n\nYayın durumu filtresi gövdesi."
    provider, _ = build_index_with(index, markdown, article_id="post-draft", slug="taslak")
    hidden_snapshot = fixtures.make_index_snapshot(
        markdown, article_id="post-hidden", slug="gizli", revision=1
    )
    run(
        index.index_article(
            hidden_snapshot,
            embedding_provider=provider,
            model_config=MODEL_CONFIG,
            published=False,
        )
    )
    text = "yayın durumu filtresi gövdesi"
    all_hits = search(index, provider, SearchQuery(text=text))
    assert {hit.record.article_id for hit in all_hits} == {"post-draft", "post-hidden"}
    published_hits = search(
        index, provider, SearchQuery(text=text, filters=SearchFilters(published=True))
    )
    assert {hit.record.article_id for hit in published_hits} == {"post-draft"}
    hidden_hits = search(
        index, provider, SearchQuery(text=text, filters=SearchFilters(published=False))
    )
    assert {hit.record.article_id for hit in hidden_hits} == {"post-hidden"}


def test_top_k_limits_result_count() -> None:
    index = fixtures.make_index()
    provider, _ = build_index_with(index, tip_ipucu_markdown())
    # Üç bölüm de sorgu terimleriyle örtüşür; top_k sonucu sınırlandırır.
    hits = search(
        index,
        provider,
        SearchQuery(text="tip mutfak çorbası gezi kapadokya", top_k=2),
    )
    assert len(hits) == 2


def test_cache_hit_avoids_reembed_and_removal_invalidates() -> None:
    index = fixtures.make_index()
    provider, snapshot = build_index_with(index, tip_ipucu_markdown())
    query = SearchQuery(text="tip ipuçları")
    first = search(index, provider, query)
    calls_after_first = provider.call_count
    second = search(index, provider, query)
    assert provider.call_count == calls_after_first  # önbellekten döndü
    assert [h.record.chunk_index for h in second] == [h.record.chunk_index for h in first]
    run(index.remove_article(snapshot.article_id, article_revision=snapshot.article_revision))
    third = search(index, provider, query)
    assert third == []  # önbellek geçersizleşti; eski sonuç sızmadı
    # Aday kümesi boşaldığı için yeni gömme çağrısı da yapılmaz.
    assert provider.call_count == calls_after_first


def test_search_validations() -> None:
    index = fixtures.make_index()
    provider = fixtures.HashingEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    with pytest.raises(PortError) as empty:
        search(index, provider, SearchQuery(text="   "))
    assert empty.value.code is AgentErrorCode.VALIDATION_ERROR
    with pytest.raises(PortError) as zero:
        search(index, provider, SearchQuery(text="sorgu", top_k=0))
    assert zero.value.code is AgentErrorCode.VALIDATION_ERROR


def test_search_on_empty_index_returns_empty() -> None:
    index = fixtures.make_index()
    provider = fixtures.HashingEmbeddingProvider(dimensions=MODEL_CONFIG.dimensions)
    assert search(index, provider, SearchQuery(text="herhangi bir sorgu")) == []


def make_record(article_id: str, chunk_index: int) -> IndexedChunk:
    return IndexedChunk(
        chunk=ArticleChunk(
            article_id=article_id,
            article_revision=1,
            chunk_index=chunk_index,
            content=f"içerik {chunk_index}",
            char_start=0,
            char_end=12,
        ),
        content_hash="0" * 64,
        heading_path=["Başlık"],
        anchor="baslik",
    )


def test_rrf_fusion_combines_both_rankings() -> None:
    semantic = [make_record("a", 0), make_record("a", 1), make_record("b", 0)]
    keyword = [make_record("b", 0), make_record("a", 0)]
    fused = rrf_fuse(semantic, keyword)

    both = fused[("a", 1, 0)][0]
    only_semantic = fused[("a", 1, 1)][0]
    # ("b",1,0) her iki sıralamada da var: semantic rank 3 + keyword rank 1.
    both_ranks_b = fused[("b", 1, 0)][0]
    assert both == pytest.approx(1 / 61 + 1 / 62)
    assert only_semantic == pytest.approx(1 / 62)
    assert both_ranks_b == pytest.approx(1 / 63 + 1 / 61)
    assert fused[("a", 1, 0)][1:] == (1, 2)
    assert fused[("a", 1, 1)][1:] == (2, None)
    assert fused[("b", 1, 0)][1:] == (3, 1)


def test_bm25_scores_reward_term_overlap_and_ignore_absence() -> None:
    docs = [tokenize("python tip ipuçları"), tokenize("mercimek çorbası tarifi")]
    query = tokenize("python ipuçları")
    scores = bm25_scores(query, docs)
    assert scores[0] > 0.0
    assert scores[1] == 0.0


def test_cosine_similarity_edges() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0  # boyut uyuşmazlığı
