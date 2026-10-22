"""Anlamsal genişleme portu (prompt §6.6): gerçek EmbeddingProvider takılabilir.

- Embedding yokken ``retrieve_async`` lexical sonucu birebir döndürür.
- Test double / hash sağlayıcısı üretimde yok sayılır (anlamsal başarı diye sunulmaz).
- İzin verilen sağlayıcıyla adaylar RRF ile yeniden sıralanır; yeterlilik lexical
  kalır; önbellek embedding model kimliğini kapsar.
"""

from __future__ import annotations

import asyncio

from agent_core.adapters.test_doubles import FakeEmbeddingProvider
from agent_core.content.config import EmbeddingModelConfig
from agent_core.models import AgentMode
from agent_core.profile import ProfileEmbedding, ProfileRetriever, load_profile_source, resolve_profile_dir
from agent_core.profile.retrieval import budget_for_mode

DOCUMENT = load_profile_source(resolve_profile_dir())
BUDGET = budget_for_mode(AgentMode.FAST)
MODEL = EmbeddingModelConfig(model_id="semantic-test-1", dimensions=8)


class CountingSemanticProvider:
    """Testlik 'gerçek' sağlayıcı: is_test_double işareti taşımaz; çağrıları sayar."""

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts, *, cancel=None):
        self.calls += 1
        return [[float((len(text) * (i + 3)) % 7 + 1) for i in range(8)] for text in texts]


def run(coro):
    return asyncio.run(coro)


def test_without_embedding_async_path_equals_lexical() -> None:
    retriever = ProfileRetriever()
    sync = retriever.retrieve(DOCUMENT, "Hangi üniversitede okudu?", language="tr", budget=BUDGET)
    retriever_async = ProfileRetriever()
    result = run(retriever_async.retrieve_async(DOCUMENT, "Hangi üniversitede okudu?", language="tr", budget=BUDGET))
    assert [c.chunk.source_id for c in result.chunks] == [c.chunk.source_id for c in sync.chunks]
    assert result.semantic_model is None


def test_test_double_embedding_is_ignored_in_production() -> None:
    fake = ProfileEmbedding(provider=FakeEmbeddingProvider(), model=MODEL)
    retriever = ProfileRetriever(embedding=fake)
    assert retriever.embedding_ignored and retriever.semantic_model is None
    result = run(retriever.retrieve_async(DOCUMENT, "Eğitmenlik deneyimi var mı?", language="tr", budget=BUDGET))
    assert result.semantic_model is None


def test_semantic_provider_reranks_within_lexical_candidates_and_caches() -> None:
    provider = CountingSemanticProvider()
    retriever = ProfileRetriever(embedding=ProfileEmbedding(provider=provider, model=MODEL))
    lexical = ProfileRetriever().retrieve(
        DOCUMENT, "Hangi projeleri geliştirdi?", language="tr",
        budget=type(BUDGET)(top_k=BUDGET.top_k * 3, max_context_tokens=10**9),
    )
    result = run(retriever.retrieve_async(DOCUMENT, "Hangi projeleri geliştirdi?", language="tr", budget=BUDGET))
    assert result.semantic_model == "semantic-test-1"
    assert len(result.chunks) <= BUDGET.top_k
    # Embedding kanıt uydurmaz: seçilenler lexical aday kümesinin içindedir.
    assert {c.chunk.source_id for c in result.chunks} <= {c.chunk.source_id for c in lexical.chunks}
    again = run(retriever.retrieve_async(DOCUMENT, "Hangi projeleri geliştirdi?", language="tr", budget=BUDGET))
    assert again.cached and provider.calls == 1


def test_semantic_provider_does_not_create_sufficiency() -> None:
    provider = CountingSemanticProvider()
    retriever = ProfileRetriever(embedding=ProfileEmbedding(provider=provider, model=MODEL))
    result = run(retriever.retrieve_async(DOCUMENT, "Kuantum kromodinamiği lagranjiyeni", language="tr", budget=BUDGET))
    assert not result.sufficient
    assert provider.calls == 0
