"""Kaynak ve kapsam kontrolünün (guardrails) birim testleri.

Plan A4 kuralları burada sabitlenir: atıflar yalnız getirilen kanıttan
seçilir; desteklenmeyen makale atfı sökülür; bölüm bağlantıları canonical
URL'den üretilir.
"""

from __future__ import annotations

import helpers
from helpers import URL_TEMPLATE, build_records, make_qa_snapshot

from agent_core.qa.guardrails import (
    append_source_block,
    build_citations,
    build_section_refs,
    neutralize_attributions,
    select_citations,
)

SNAPSHOT = make_qa_snapshot()
RECORDS = build_records(SNAPSHOT)
KUYRUK = RECORDS[2]
HATA = RECORDS[3]


def test_select_citations_only_from_retrieved_records() -> None:
    answer = "Makaleye göre önerilen değer aralığı 100 ile 1000 arasındadır."
    cited = select_citations(answer, [KUYRUK, HATA], min_overlap=2)
    assert KUYRUK in cited
    assert HATA not in cited


def test_select_citations_orders_by_retrieval_order() -> None:
    answer = (
        "Makaleye göre önerilen değer aralığı 100 ile 1000 arasındadır. "
        "Kuyruk dolunca QueueFull istisnası fırlar."
    )
    cited = select_citations(answer, [KUYRUK, HATA], min_overlap=2)
    assert cited == [KUYRUK, HATA]


def test_select_citations_empty_when_no_overlap() -> None:
    assert select_citations("Tamamen alakasız bir yanıt.", [KUYRUK], min_overlap=2) == []


def test_build_citations_use_canonical_source_id() -> None:
    citations = build_citations([KUYRUK])
    assert len(citations) == 1
    reference = citations[0]
    assert reference.kind == "article"
    assert reference.source_id == f"article:{KUYRUK.article_id}:{KUYRUK.article_revision}:2"


def test_section_refs_carry_anchor_and_canonical_url() -> None:
    sections = build_section_refs([KUYRUK])
    assert sections[0].anchor == "kuyruk-siniri"
    assert sections[0].url == f"{URL_TEMPLATE.replace('{slug}', helpers.QA_SLUG)}#kuyruk-siniri"
    assert sections[0].heading_path == [helpers.QA_TITLE, "Kuyruk sınırı"]
    assert sections[0].chunk_index == 2


def test_source_block_appends_verified_links() -> None:
    sections = build_section_refs([KUYRUK])
    answer = append_source_block("Önerilen aralık 100 ile 1000 arasındadır.", sections)
    assert "Kaynak bölümü:" in answer
    assert f"[{helpers.QA_TITLE} > Kuyruk sınırı]({sections[0].url})" in answer


def test_source_block_without_sections_keeps_answer() -> None:
    assert append_source_block("Yanıt.", []) == "Yanıt."


def test_supported_attribution_is_kept() -> None:
    answer = "Makaleye göre önerilen değer aralığı 100 ile 1000 arasındadır."
    controlled, removed = neutralize_attributions(answer, KUYRUK.chunk.content)
    assert removed == 0
    assert controlled == answer


def test_unsupported_attribution_sentence_is_removed() -> None:
    answer = (
        "Makaleye göre Python 3.14 kalıcı bellek güvenliği getiriyor. "
        "Önerilen değer aralığı 100 ile 1000 arasındadır."
    )
    controlled, removed = neutralize_attributions(answer, KUYRUK.chunk.content)
    assert removed == 1
    assert "makaleye göre" not in controlled.casefold()
    # Makalede gerçekten olan cümle aynen kalır.
    assert "Önerilen değer aralığı 100 ile 1000 arasındadır." in controlled


def test_author_attribution_without_evidence_is_removed() -> None:
    answer = "Yazara göre tip ipuçları üretimde asla hata üretmez."
    controlled, removed = neutralize_attributions(answer, KUYRUK.chunk.content)
    assert removed == 1
    assert "yazara göre" not in controlled.casefold()


def test_sentences_without_markers_are_never_touched() -> None:
    answer = "Kuyruk sınırı performans için önemlidir."
    controlled, removed = neutralize_attributions(answer, KUYRUK.chunk.content)
    assert removed == 0
    assert controlled == answer
