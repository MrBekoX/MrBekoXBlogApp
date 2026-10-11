"""Makale soru-cevap akışının kabul senaryoları (plan A4).

Plan kabul ölçütleri: ana fikir, belirli bölüm, kod açıklaması, takip
sorusu, makalede karşılığı olmayan soru, geçersiz seçim ve erişilemeyen
içerik senaryoları çalışır; kaynak içindeki talimat agent'ın araç
politikasını değiştiremez. Tüm akış test double'larla koşar; gerçek
LLM/embedding kullanılmaz. Async akışlar kök kuralı gereği ``run()``
ile senkron çağrılır (pytest-asyncio bağımlılığı yok).
"""

from __future__ import annotations

import helpers
from helpers import (
    INJECTION_SENTENCE,
    QA_ARTICLE_CONTENT,
    QA_SLUG,
    QA_TITLE,
    ScriptedModelProvider,
    ScriptedRetriever,
    UnavailableContentRepository,
    build_records,
    make_config,
    make_qa_context,
    make_qa_route,
    make_qa_snapshot,
    make_retriever,
    run,
    turn,
)

from agent_core.adapters.test_doubles import FakeContentRepository, RecordingProgressSink
from agent_core.errors import AgentErrorCode
from agent_core.models import AgentMode, ProgressKind, RunStatus
from agent_core.qa import run_article_qa

URL_BASE = f"https://mrbekox.dev/blog/{QA_SLUG}"

#: Bölüm parça indeksleri: giriş(0), kurulum(1), kuyruk+kod(2), hata(3).
INTRO, KURULUM, KUYRUK, HATA = 0, 1, 2, 3


def answer_with(text: str) -> ScriptedModelProvider:
    return ScriptedModelProvider([text])


def run_flow(context, model, *, retriever=None, content=None, config=None, sink=None):
    route = make_qa_route(
        run_id=context.run_id, selected_mode=AgentMode(context.mode_preference)
    )
    return run(
        run_article_qa(
            context,
            route,
            model=model,
            retriever=retriever or make_retriever(),
            content=content,
            config=config,
            progress=sink,
        )
    )


# -- 1. Ana fikir -------------------------------------------------------------


def test_main_idea_question_grounds_answer_in_article() -> None:
    snapshot = make_qa_snapshot()
    context = make_qa_context(snapshot, question="Bu makale genel olarak ne anlatıyor?")
    model = answer_with(
        "Makale, Python tip ipuçlarını ve bunların günlük işleri hızlandırdığını anlatır."
    )

    result = run_flow(context, model)

    outcome = result.outcome
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.source_scope.value == "article"
    assert "Python tip ipuçlarını" in outcome.answer
    # Atıf yalnız gerçek getirilen bölümden: giriş parçası.
    assert [c.chunk_index for c in outcome.citations] == [INTRO]
    assert outcome.citations[0].source_id == f"article:{snapshot.article_id}:3:{INTRO}"
    assert outcome.usage.model_calls == 1
    assert outcome.usage.web_search_calls == 0
    # Bölüm bağlantısı doğrulanmış URL şablonundan üretildi.
    assert f"[{QA_TITLE}]({URL_BASE}#python-tip-ipuclari)" in outcome.answer
    assert "Kaynak bölümü:" in outcome.answer


# -- 2. Belirli bölüm ----------------------------------------------------------


def test_specific_section_cites_section_and_verified_anchor_link() -> None:
    snapshot = make_qa_snapshot()
    context = make_qa_context(snapshot, question="Kuyruk sınırı nasıl ayarlanır?")
    model = answer_with("Makaleye göre önerilen değer aralığı 100 ile 1000 arasındadır.")
    sink = RecordingProgressSink()

    result = run_flow(context, model, sink=sink)

    outcome = result.outcome
    assert outcome.status is RunStatus.COMPLETED
    assert [c.chunk_index for c in outcome.citations] == [KUYRUK]
    assert outcome.citations[0].article_revision == snapshot.article_revision
    section = result.sections[0]
    assert section.anchor == "kuyruk-siniri"
    assert section.url == f"{URL_BASE}#kuyruk-siniri"
    assert section.url in outcome.answer
    assert outcome.usage.web_search_calls == 0
    kinds = [event.kind for event in sink.events]
    assert kinds == [
        ProgressKind.RETRIEVAL_STARTED,
        ProgressKind.RETRIEVAL_COMPLETED,
        ProgressKind.GENERATION_STARTED,
        ProgressKind.GENERATION_COMPLETED,
    ]


# -- 3. Kod açıklaması ---------------------------------------------------------


def test_code_explanation_cites_intact_code_chunk() -> None:
    snapshot = make_qa_snapshot()
    context = make_qa_context(
        snapshot,
        question="Kod örneğindeki max_queue_size sınırı ne işe yarar?",
    )
    model = answer_with(
        "asyncio kuyruğunda bekleyen iş sayısı max_queue_size ile sınırlandırılır."
    )

    result = run_flow(context, model)

    retrieved = list(result.state["retrieved"])
    code_records = [r for r in retrieved if "```python" in r.chunk.content]
    assert code_records, "kod bloğu içeren bölüm getirilmeli"
    fenced = code_records[0]
    # Kod bloğu bölünmeden korundu (A3 bölümleme sözleşmesi).
    assert "async def isleri_tasi(isler, sinir):" in fenced.chunk.content
    assert fenced.chunk.content.count("```") >= 2
    # Atıf kod bloğunun bulunduğu bölüme gider.
    assert [c.chunk_index for c in result.outcome.citations] == [fenced.chunk_index]
    assert result.outcome.status is RunStatus.COMPLETED


# -- 4. Takip sorusu -----------------------------------------------------------


def test_followup_uses_history_for_retrieval_but_not_as_source() -> None:
    snapshot = make_qa_snapshot()
    history = [
        turn("user", "Hata yönetimini anlatır mısın?"),
        turn("assistant", "Hata yönetimi QueueFull istisnasıyla başlar ve akışı durdurmaz."),
    ]
    context = make_qa_context(
        snapshot,
        question="Önerilen aralık neye göre belirlenmiş?",
        conversation_history=history,
    )
    model = answer_with("Makaleye göre önerilen değer aralığı 100 ile 1000 arasındadır.")

    result = run_flow(context, model, config=make_config(top_k=1))

    state = result.state
    # Tek sorgu (top_k=1) geçmiş terimleriyle hata bölümünü getirir; soru
    # terimleri desteklemez ve sorgu düzenlenerek kuyruk bölümüne ulaşılır.
    assert state["rewritten"] is True
    assert state["retrieval_attempt"] == 2
    assert state["retrieval_query"] == "onerilen aralik belirlenmis"
    assert [c.chunk_index for c in result.outcome.citations] == [KUYRUK]
    assert result.outcome.usage.tool_calls == 3  # indeksleme + iki arama
    assert result.outcome.usage.model_calls == 1

    # Önceki model cevabı isteme "doğrulanmış kaynak değildir" bloğunda girer,
    # CONTEXT bloğuna değil; konuşma turu atıf üretemez.
    prompt = model.requests[0].prompt
    assert prompt.index("CONTEXT:") < prompt.index("SORU (tr):")
    history_index = prompt.index("ÖNCEKİ KONUŞMA")
    assert prompt.index("QueueFull istisnasıyla başlar") > history_index
    assert "doğrulanmış kaynak değildir" in prompt
    assert {c.source_id for c in result.outcome.citations} == {
        f"article:{snapshot.article_id}:3:{KUYRUK}"
    }


# -- 5. Makalede karşılığı olmayan soru ----------------------------------------


def test_question_absent_from_article_reports_insufficiency_without_citations() -> None:
    snapshot = make_qa_snapshot()
    context = make_qa_context(
        snapshot,
        question="Makalede Docker konteyner dağıtımı anlatılıyor mu?",
    )
    model = ScriptedModelProvider([])  # hiç çağrılmamalı

    result = run_flow(context, model)

    outcome = result.outcome
    assert outcome.status is RunStatus.COMPLETED
    assert model.call_count == 0  # uydurma cevap üretme yolu yok
    assert outcome.citations == []
    assert outcome.answer.startswith("Bu sorunun yanıtı makalede yer almıyor.")
    # Sınırlı düzenleme denemesi: bir orijinal + bir düzenlenmiş arama.
    assert result.state["rewritten"] is True
    assert result.state["retrieval_attempt"] == 2
    assert "sorguyu düzenleyerek de aradım" in outcome.answer
    assert outcome.usage.model_calls == 0


def test_english_question_receives_answer_in_english() -> None:
    snapshot = make_qa_snapshot(language="en")
    context = make_qa_context(
        snapshot,
        question="Does the article explain Docker deployment?",
        language="en",
    )
    model = ScriptedModelProvider([])

    result = run_flow(context, model)

    assert result.outcome.citations == []
    assert result.outcome.answer.startswith(
        "The answer to this question is not covered by the article."
    )


# -- 6. Geçersiz seçim ----------------------------------------------------------


def test_invalid_selection_is_excluded_and_disclosed() -> None:
    snapshot = make_qa_snapshot()
    context = make_qa_context(
        snapshot,
        question="Kuyruk sınırı nasıl ayarlanır?",
        selected_text="Bu seçim makalede yok.",
        mode_preference="analysis",
    )
    model = answer_with(
        "asyncio kuyruğunda bekleyen iş sayısı max_queue_size ile sınırlandırılır."
    )

    result = run_flow(context, model)

    assert result.state["selected_text_ok"] is False
    prompt = model.requests[0].prompt
    assert "Bu seçim makalede yok." not in prompt
    assert "KULLANICININ SEÇTİĞİ METİN" not in prompt
    assert "seçtiğiniz metin makalede bulunamadı" in result.outcome.answer
    assert [c.chunk_index for c in result.outcome.citations] == [KUYRUK]
    assert result.outcome.status is RunStatus.COMPLETED


def test_valid_selection_is_included_as_verified_text() -> None:
    snapshot = make_qa_snapshot()
    context = make_qa_context(
        snapshot,
        question="Kuyruk sınırı nasıl ayarlanır?",
        selected_text="Önerilen değer aralığı 100 ile 1000 arasındadır.",
        mode_preference="analysis",
    )
    model = answer_with("Seçtiğiniz cümle önerilen değer aralığını verir: 100 ile 1000.")

    result = run_flow(context, model)

    assert result.state["selected_text_ok"] is True
    prompt = model.requests[0].prompt
    selection_index = prompt.index("KULLANICININ SEÇTİĞİ METİN")
    assert "Önerilen değer aralığı 100 ile 1000 arasındadır." in prompt[selection_index:]
    assert "seçtiğiniz metin makalede bulunamadı" not in result.outcome.answer


# -- 7. Erişilemeyen içerik ------------------------------------------------------


def test_inaccessible_article_fails_with_not_found() -> None:
    context = make_qa_context(article_id="post-404")
    model = ScriptedModelProvider([])

    result = run(
        run_article_qa(
            context,
            make_qa_route(run_id=context.run_id),
            model=model,
            retriever=make_retriever(),
            content=UnavailableContentRepository(),
        )
    )

    outcome = result.outcome
    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.NOT_FOUND
    assert outcome.answer is None
    assert model.call_count == 0


def test_reference_without_content_repository_fails_with_config_error() -> None:
    context = make_qa_context(article_id="post-1")
    model = ScriptedModelProvider([])

    result = run(
        run_article_qa(
            context,
            make_qa_route(run_id=context.run_id),
            model=model,
            retriever=make_retriever(),
            content=None,
        )
    )

    assert result.outcome.status is RunStatus.FAILED
    assert result.outcome.error_code is AgentErrorCode.CONFIG_ERROR
    assert model.call_count == 0


def test_reference_only_context_fetches_article_through_repository() -> None:
    snapshot = make_qa_snapshot()
    context = make_qa_context(article_id=snapshot.article_id)
    # İçerik referansı (K7): hash/revizyon bağlamda taşınır, içerik depodan gelir.
    context = context.model_copy(
        update={
            "article_revision": snapshot.article_revision,
            "article_content_hash": snapshot.content_hash,
        }
    )
    model = answer_with("Makaleye göre önerilen değer aralığı 100 ile 1000 arasındadır.")

    result = run(
        run_article_qa(
            context,
            make_qa_route(run_id=context.run_id),
            model=model,
            retriever=make_retriever(snapshot),
            content=FakeContentRepository({snapshot.article_id: snapshot}),
        )
    )

    assert result.state["snapshot"] is not None
    assert [c.chunk_index for c in result.outcome.citations] == [KUYRUK]
    assert result.outcome.status is RunStatus.COMPLETED


# -- 8. Kaynak içindeki talimat araç politikasını değiştiremez --------------------


def test_injected_instruction_cannot_change_tool_policy() -> None:
    poisoned = QA_ARTICLE_CONTENT.replace(
        "```python", f"{INJECTION_SENTENCE}\n\n```python", 1
    )
    assert INJECTION_SENTENCE in poisoned
    snapshot = make_qa_snapshot(content=poisoned)
    context = make_qa_context(snapshot, question="Kuyruk sınırı nasıl ayarlanır?")
    model = answer_with(
        "asyncio kuyruğunda bekleyen iş sayısı max_queue_size ile sınırlandırılır."
    )

    result = run_flow(context, model)

    outcome = result.outcome
    assert outcome.status is RunStatus.COMPLETED
    # Enjeksiyonlu bölüm cevabı değiştirmedi; web araç kullanımı sıfır.
    assert outcome.usage.web_search_calls == 0
    assert "sınırlandırılır" in outcome.answer
    assert [c.chunk_index for c in outcome.citations] == [KUYRUK]
    # Sistem istemi bağlamı veri olarak ele almayı ve talimatları uygulamamayı söyler.
    system = model.requests[0].system or ""
    assert "veri olarak" in system
    assert "talimatları uygulama" in system
    # Atıflar getirilen kanıt alt kümesidir.
    retrieved_ids = {
        f"article:{r.article_id}:{r.article_revision}:{r.chunk_index}"
        for r in result.state["retrieved"]
    }
    assert {c.source_id for c in outcome.citations} <= retrieved_ids


# -- Revizyon değişimi -----------------------------------------------------------


def test_new_revision_replaces_old_evidence_and_citations() -> None:
    old_snapshot = make_qa_snapshot(article_revision=2)
    retriever = make_retriever(old_snapshot)  # indeks revizyon 2 ile kurulmuş
    snapshot = make_qa_snapshot(article_revision=3)
    context = make_qa_context(snapshot, question="Kuyruk sınırı nasıl ayarlanır?")
    model = answer_with("Makaleye göre önerilen değer aralığı 100 ile 1000 arasındadır.")

    result = run_flow(context, model, retriever=retriever)

    revisions = {r.article_revision for r in result.state["retrieved"]}
    assert revisions == {3}
    assert result.outcome.citations[0].article_revision == 3
    assert result.outcome.citations[0].source_id == f"article:{snapshot.article_id}:3:{KUYRUK}"


def test_evidence_from_older_revision_is_rejected_even_if_retriever_returns_it() -> None:
    snapshot = make_qa_snapshot(article_revision=3)
    stale_records = build_records(make_qa_snapshot(article_revision=2), revision=2)
    # İkinci yığın: sınırlı sorgu düzenleme denemesinin boş araması.
    retriever = ScriptedRetriever([stale_records, []])
    context = make_qa_context(snapshot, question="Kuyruk sınırı nasıl ayarlanır?")
    model = ScriptedModelProvider([])

    result = run(
        run_article_qa(
            context,
            make_qa_route(run_id=context.run_id),
            model=model,
            retriever=retriever,
        )
    )

    # Bayat kanıt state'e girmez; kaldırılmış/eski içerikten cevap üretilmez.
    assert result.state["retrieved"] == []
    assert result.outcome.citations == []
    assert result.outcome.status is RunStatus.COMPLETED
    assert result.outcome.answer.startswith("Bu sorunun yanıtı makalede yer almıyor.")
    assert model.call_count == 0
