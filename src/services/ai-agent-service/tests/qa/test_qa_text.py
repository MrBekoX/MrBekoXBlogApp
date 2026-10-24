"""QA metin yardımcılarının ve yeterlilik değerlendirmesinin birim testleri.

Kararlar deterministiktir: A3'ün katlama/belirteçleme sözleşmesiyle aynı
normalizasyon kullanılır; bu testler o davranışı sabitler.
"""

from __future__ import annotations

from agent_core.content.models import IndexedChunk
from agent_core.models import ArticleChunk

import helpers
from helpers import (
    QA_ARTICLE_CONTENT,
    make_qa_snapshot,
    turn,
)

from agent_core.qa.state import merge_chunks
from agent_core.qa.sufficiency import evaluate_sufficiency
from agent_core.qa.text import (
    build_retrieval_query,
    history_context_tokens,
    is_generic_question,
    is_related_to_article,
    rewrite_query,
    salient_tokens,
)


def make_record(chunk_index: int, content: str, *, revision: int = 3) -> IndexedChunk:
    chunk = ArticleChunk(
        article_id="post-1",
        article_revision=revision,
        chunk_index=chunk_index,
        content=content,
        heading=None,
        char_start=0,
        char_end=len(content),
    )
    return IndexedChunk(
        chunk=chunk,
        content_hash=make_qa_snapshot().content_hash,
        heading_path=[helpers.QA_TITLE],
        anchor="python-tip-ipuclari",
        language="tr",
        published=True,
        canonical_url=None,
    )


# -- genel soru sınıfı -------------------------------------------------------


def test_generic_question_signals_match_article_level_questions() -> None:
    cases = [
        ("Bu makale genel olarak ne anlatıyor?", True),
        ("Makalenin ana fikri nedir?", True),
        ("Makalede hangi konular var?", True),
        ("İçeriği özetler misin? Özeti bekliyorum.", True),
        ("What is this article about?", True),
        ("Kuyruk sınırı nasıl ayarlanır?", False),
        ("Makalede Docker konteyner dağıtımı anlatılıyor mu?", False),
        ("Kod örneğindeki max_queue_size sınırı ne işe yarar?", False),
    ]
    for question, expected in cases:
        assert is_generic_question(question) is expected, question


# -- terim çıkarımı ----------------------------------------------------------


def test_salient_tokens_drop_fillers_and_fold_turkish() -> None:
    tokens = salient_tokens("Kuyruk sınırı için önerilen değer nedir?")
    assert tokens == ["kuyruk", "siniri", "onerilen", "deger"]


def test_salient_tokens_deduplicate_preserving_order() -> None:
    # "tip" uzunluk eşiği (4) altında kaldığı için düşer; yinelenenler tek olur.
    assert salient_tokens("ipuçları, ipuçları ve İPUÇLARI ve ip uclari") == [
        "ipuclari",
        "uclari",
    ]


# -- seçim ilişkisi ----------------------------------------------------------


def test_related_selection_tolerates_whitespace_noise() -> None:
    assert is_related_to_article(
        "Önerilen değer   aralığı 100 ile\n\n1000 arasındadır.", QA_ARTICLE_CONTENT
    )


def test_unrelated_selection_is_rejected() -> None:
    assert not is_related_to_article("Bu seçim makalede yok.", QA_ARTICLE_CONTENT)
    assert not is_related_to_article("   ", QA_ARTICLE_CONTENT)


# -- takip sorusu sorgu kurulumu ---------------------------------------------


def test_first_query_without_history_is_the_question_itself() -> None:
    question = "Önerilen aralık neye göre belirlenmiş?"
    assert build_retrieval_query(question, []) == question


def test_followup_query_absorbs_history_terms_missing_from_question() -> None:
    question = "Önerilen aralık neye göre belirlenmiş?"
    history = [
        turn("user", "Hata yönetimini anlatır mısın?"),
        turn("assistant", "Hata yönetimi QueueFull istisnasıyla başlar ve akışı durdurmaz."),
    ]
    query = build_retrieval_query(question, history)
    assert query.startswith(question)
    for token in history_context_tokens(question, history):
        assert token in query
    # Soruda geçen terimler geçmişten tekrar taşınmaz.
    assert "onerilen" not in query.split(question, 1)[1]


def test_history_terms_are_capped() -> None:
    question = "Önerilen aralık nedir?"
    filler = " ".join(f"terim{index}" for index in range(20))
    history = [turn("assistant", filler)]
    assert len(history_context_tokens(question, history, max_tokens=6)) == 6


def test_rewrite_query_focuses_on_question_terms_only() -> None:
    question = "Önerilen aralık neye göre belirlenmiş?"
    history = [turn("user", "Hata yönetimini anlat")]
    enriched = build_retrieval_query(question, history)
    rewritten = rewrite_query(question)
    assert rewritten == "onerilen aralik belirlenmis"
    assert rewritten != enriched
    assert "hata" not in rewritten


# -- state birleştirme --------------------------------------------------------


def test_merge_chunks_deduplicates_on_article_revision_index() -> None:
    first = make_record(2, "kuyruk bölümü")
    duplicate = make_record(2, "kuyruk bölümü")
    other = make_record(3, "hata bölümü")
    merged = merge_chunks([first], [duplicate, other])
    assert len(merged) == 2
    assert [record.chunk_index for record in merged] == [2, 3]


# -- yeterlilik değerlendirmesi ----------------------------------------------


def test_generic_question_is_satisfied_by_any_retrieved_section() -> None:
    verdict = evaluate_sufficiency(
        "Bu makale genel olarak ne anlatıyor?",
        [make_record(0, "giriş bölümü metni")],
    )
    assert verdict.sufficient is True
    assert verdict.generic_question is True
    assert verdict.matched_chunk_indexes == [0]


def test_generic_question_without_results_is_insufficient() -> None:
    verdict = evaluate_sufficiency("Bu makale genel olarak ne anlatıyor?", [])
    assert verdict.sufficient is False


def test_specific_question_requires_lexical_support() -> None:
    question = "Önerilen değer aralığı nedir?"
    matching = make_record(2, "Önerilen değer aralığı 100 ile 1000 arasındadır.")
    unrelated = make_record(3, "Kuyruk dolunca QueueFull istisnası fırlar.")
    verdict = evaluate_sufficiency(question, [matching, unrelated])
    assert verdict.sufficient is True
    assert verdict.matched_chunk_indexes == [2]


def test_semantic_candidates_without_shared_words_require_answer_verification() -> None:
    verdict = evaluate_sufficiency(
        "Docker konteyner dağıtımı nasıl yapılır?",
        [make_record(2, "Önerilen değer aralığı 100 ile 1000 arasındadır.")],
    )
    assert verdict.sufficient is True
    assert verdict.matched_chunk_indexes == [2]
    assert "verification" in verdict.reason
