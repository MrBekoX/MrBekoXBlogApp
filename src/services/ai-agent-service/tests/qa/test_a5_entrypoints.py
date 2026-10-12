"""A5 giriş noktası entegrasyonu: açıklama sorusu, kayıtlı mod yükseltmesi,
web kullanılamazlık durumu ve analysis dispatch'i.

Plan A5 maddelerinin yürütme tarafı karşılıkları:
- ``needs_clarification`` → tahmin yok, ``needs_input`` terminali (model çağrısı yok).
- fast yetersiz + çok bölümlü soru → TEK KEZ fast → analysis yükseltmesi, kayıtlı.
- ``needs_web`` → web araçları bağlı değilken özelliğin kullanılamaz olduğu
  doğru durumla bildirilir (web gerçekleştirimi A6/A7 kapsamıdır).
"""

from __future__ import annotations

import helpers
from helpers import (
    ScriptedModelProvider,
    ScriptedRetriever,
    build_records,
    make_qa_context,
    make_qa_snapshot,
    run,
)

from agent_core.adapters.test_doubles import ExplodingModelProvider, FakeWebSearchProvider, RecordingProgressSink
from agent_core.entrypoints import execute_plan, prepare_and_route
from agent_core.models import AgentMode, ProgressKind, RunStatus
from agent_core.routing import split_answer_headings

MULTI_PART_QUESTION = "Kuyruk sınırı nasıl ayarlanır ve QueueFull hatası nasıl yönetilir?"
UPGRADE_ANSWER = (
    "## Kuyruk sınırı\n\n"
    "asyncio kuyruğunda bekleyen iş sayısı `max_queue_size` ile sınırlandırılır.\n\n"
    "## Hata yönetimi\n\n"
    "Kuyruk dolunca `QueueFull` istisnası fırlar; akış try/except ile yönetilir."
)


def make_prepared(**context_overrides):
    context = make_qa_context(make_qa_snapshot(), **context_overrides)
    return run(prepare_and_route(context))


# --- Eksik kişisel bilgi: tahmin yok, needs_input ---

def test_needs_clarification_run_returns_needs_input_without_model_call() -> None:
    context = make_qa_context(
        make_qa_snapshot(),
        question="Benim projemde kuyruk sınırını nasıl ayarlamalıyım?",
    )
    prepared = run(prepare_and_route(context))
    assert prepared.route.needs_clarification is True

    exploding = ExplodingModelProvider()
    outcome = run(execute_plan(prepared, model=exploding, retriever=ScriptedRetriever([])))

    assert outcome.status is RunStatus.NEEDS_INPUT
    assert outcome.unresolved_questions == [prepared.route.clarification_question]
    assert outcome.answer is None and outcome.report is None
    assert exploding.call_count == 0  # eksik bilgi modelle tahmin edilmez


def test_plain_question_does_not_trigger_clarification() -> None:
    prepared = make_prepared(question="Kuyruk sınırı nasıl ayarlanır?")

    assert prepared.route.needs_clarification is False
    assert prepared.route.clarification_question is None


# --- Sınırlı ve kayıtlı mod yükseltmesi: fast → analysis ---

def test_fast_run_upgrades_to_analysis_once_and_records_it() -> None:
    snapshot = make_qa_snapshot()
    records = build_records(snapshot)
    context = make_qa_context(
        snapshot, question=MULTI_PART_QUESTION, mode_preference="fast"
    )
    prepared = run(prepare_and_route(context))
    assert prepared.route.selected_mode is AgentMode.FAST  # kullanıcı fast istedi
    # fast QA: 2 boş arama (ilk + düzenlenmiş) → yetersiz; analysis: 2 başlık araması.
    retriever = ScriptedRetriever([[], [], [records[2]], [records[3]]])
    model = ScriptedModelProvider([UPGRADE_ANSWER])
    sink = RecordingProgressSink()

    outcome = run(execute_plan(prepared, model=model, retriever=retriever, progress=sink))

    # Yükseltme sınırlı: çalışma başına tek kayıt, yalnız fast → analysis.
    assert len(outcome.mode_upgrades) == 1
    upgrade = outcome.mode_upgrades[0]
    assert upgrade.from_mode is AgentMode.FAST
    assert upgrade.to_mode is AgentMode.ANALYSIS
    assert upgrade.reason
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.selected_mode is AgentMode.ANALYSIS
    # Yükseltilen akış analysis alt akışıdır: farklı adımlar (başlık aramaları).
    assert model.requests[0].metadata["flow"] == "article_analysis"
    assert outcome.citations
    # Yükseltme kayıtlıdır: ilerleme olayında da taşınır.
    upgrade_events = [event for event in sink.events if "yükseltme" in event.message]
    assert upgrade_events and upgrade_events[0].kind is ProgressKind.MODE_SELECTED


def test_fast_run_without_need_stays_on_qa_flow_without_upgrade() -> None:
    context = make_qa_context(make_qa_snapshot(), question="Kuyruk sınırı nasıl ayarlanır?")
    prepared = run(prepare_and_route(context))
    assert split_answer_headings(context.question) and len(split_answer_headings(context.question)) == 1
    retriever = ScriptedRetriever([
        [record for record in build_records(make_qa_snapshot()) if record.chunk_index == 2]
    ])
    model = ScriptedModelProvider(
        ["asyncio kuyruğunda bekleyen iş sayısı max_queue_size ile sınırlandırılır."]
    )

    outcome = run(execute_plan(prepared, model=model, retriever=retriever))

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.mode_upgrades == []  # yetersizlik yok; yükseltme tetiklenmedi
    assert model.requests[0].metadata["flow"] == "article_qa"


def test_single_part_fast_run_never_upgrades_even_when_insufficient() -> None:
    context = make_qa_context(
        make_qa_snapshot(), question="Gölge mod değişkenleri nasıl tanımlanır?"
    )
    prepared = run(prepare_and_route(context))
    assert prepared.route.selected_mode is AgentMode.FAST
    retriever = ScriptedRetriever([[], []])  # ilk + düzenlenmiş arama boş
    exploding = ExplodingModelProvider()  # yetersizlikte model çağrısı da yok

    outcome = run(execute_plan(prepared, model=exploding, retriever=retriever))

    assert outcome.answer.startswith("Bu sorunun yanıtı makalede yer almıyor.")
    assert outcome.mode_upgrades == []  # tek bölümlü soru analysis'e yükseltilmez
    assert exploding.call_count == 0


# --- Web araçları bağlı değil: doğru durum bildirimi ---

def test_freshness_question_routes_deep_and_reports_web_unavailable() -> None:
    context = make_qa_context(
        make_qa_snapshot(),
        question="asyncio kuyruk sınırı için güncel öneri nedir?",
        mode_preference="auto",
    )
    prepared = run(prepare_and_route(context))
    assert prepared.route.needs_web is True
    assert prepared.route.selected_mode is AgentMode.DEEP_RESEARCH

    outcome = run(
        execute_plan(
            prepared,
            model=ScriptedModelProvider(["# Rapor\n\nMakale bulguları."]),
            retriever=ScriptedRetriever([]),
        )
    )

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.report is not None
    assert "web araştırma araçları bu sürümde bağlı olmadığı için bu özellik kullanılamıyor" in outcome.report
    assert outcome.source_scope.value == "article_and_web"
    assert outcome.usage.web_search_calls == 0


def test_wired_web_search_provider_is_not_called_and_flow_gap_is_disclosed() -> None:
    context = make_qa_context(
        make_qa_snapshot(),
        question="asyncio kuyruk sınırı için güncel öneri nedir?",
        mode_preference="auto",
    )
    prepared = run(prepare_and_route(context))
    web = FakeWebSearchProvider([])

    outcome = run(
        execute_plan(
            prepared,
            model=ScriptedModelProvider(["# Rapor\n\nMakale bulguları."]),
            retriever=ScriptedRetriever([]),
            web_search=web,
        )
    )

    assert "web araştırma akışı bu sürümde henüz uygulanmadığı için dış kanıt toplanamadı" in outcome.report
    assert web.call_count == 0  # A5 web araçlarını ÇALIŞTIRMAZ (A6 kapsamı)


def test_analysis_mode_dispatches_to_analysis_flow_through_entrypoint() -> None:
    snapshot = make_qa_snapshot()
    records = build_records(snapshot)
    context = make_qa_context(
        snapshot, question=MULTI_PART_QUESTION, mode_preference="analysis"
    )
    prepared = run(prepare_and_route(context))
    assert prepared.route.selected_mode is AgentMode.ANALYSIS
    retriever = ScriptedRetriever([[records[2]], [records[3]]])
    model = ScriptedModelProvider([UPGRADE_ANSWER])

    outcome = run(execute_plan(prepared, model=model, retriever=retriever))

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.selected_mode is AgentMode.ANALYSIS
    assert model.requests[0].metadata["flow"] == "article_analysis"
    assert outcome.mode_upgrades == []  # doğrudan analysis çalışması yükseltme değildir
