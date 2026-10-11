"""Entrypoints entegrasyonu: makale bağlamlı çalışma A4 QA akışına düşer.

A1 sözleşmesi korunur: route kararı hazırlıkta bir kez hesaplanır;
execute/resume yeniden yönlendirmez. Derin araştırma ve makalesiz
akışlar A1 tek-çağrı yürütücüsünde kalır.
"""

from __future__ import annotations

import helpers
from helpers import (
    ScriptedModelProvider,
    ScriptedRetriever,
    make_qa_snapshot,
    make_retriever,
    run,
)

from agent_core.adapters.test_doubles import FakeCheckpointStore
from agent_core.entrypoints import ResumeRequest, execute_plan, prepare_and_route, resume
from agent_core.models import RunStatus


def make_prepared(**context_overrides):
    context = helpers.make_qa_context(make_qa_snapshot(), **context_overrides)
    return run(prepare_and_route(context))


def test_execute_plan_routes_article_bound_fast_run_through_qa_flow() -> None:
    prepared = make_prepared(question="Kuyruk sınırı nasıl ayarlanır?")
    model = ScriptedModelProvider(
        ["asyncio kuyruğunda bekleyen iş sayısı max_queue_size ile sınırlandırılır."]
    )
    retriever = make_retriever(prepared.context.article_snapshot)

    outcome = run(execute_plan(prepared, model=model, retriever=retriever))

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.citations, "QA akışı atıf üretmeli"
    assert "Kaynak bölümü:" in outcome.answer
    assert model.requests[0].metadata["flow"] == "article_qa"
    assert outcome.usage.model_calls == 1
    assert outcome.usage.web_search_calls == 0


def test_execute_plan_without_retriever_keeps_legacy_path_transitionally() -> None:
    """GEÇİŞ DAVRANIŞI (A5 kapanacak): retriever'sız makale çalışması A1 yolunda kalır.

    Bu davranış kanıtsız makale cevabı riskini taşır; worker wiring (A5/B4)
    retriever'ı zorunlu kılınca kaldırılmalıdır (A4-rapor.md açık risk).
    """
    prepared = make_prepared(question="Kuyruk sınırı nasıl ayarlanır?")
    model = ScriptedModelProvider(["A1 tek çağrı yanıtı"])
    retriever = ScriptedRetriever([])

    outcome = run(execute_plan(prepared, model=model, retriever=None))

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.answer == "A1 tek çağrı yanıtı"
    assert outcome.citations == []  # QA atıf akışı çalışmadı
    assert model.call_count == 1
    assert model.requests[0].metadata.get("flow") is None
    assert retriever.indexed == []


def test_execute_plan_deep_research_stays_on_legacy_report_path() -> None:
    prepared = make_prepared(mode_preference="deep_research")
    assert prepared.route.selected_mode.value == "deep_research"
    model = ScriptedModelProvider(["# Rapor\n\nBulgular."])
    retriever = ScriptedRetriever([])

    outcome = run(execute_plan(prepared, model=model, retriever=retriever))

    assert outcome.report is not None
    assert outcome.answer is None
    assert model.call_count == 1
    assert retriever.indexed == []  # A4 QA akışı çalıştırılmadı


def test_execute_plan_non_article_run_stays_on_legacy_path() -> None:
    context = helpers.make_qa_context(None)  # makale bağlamı yok
    prepared = run(prepare_and_route(context))
    model = ScriptedModelProvider(["Hesaplanan yanıt"])
    retriever = ScriptedRetriever([])

    outcome = run(execute_plan(prepared, model=model, retriever=retriever))

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.answer == "Hesaplanan yanıt"
    assert model.call_count == 1
    assert retriever.indexed == []


def test_resume_of_article_bound_run_continues_through_qa_flow() -> None:
    store = FakeCheckpointStore()
    context = helpers.make_qa_context(
        make_qa_snapshot(), question="Kuyruk sınırı nasıl ayarlanır?"
    )
    prepared = run(prepare_and_route(context, checkpoint=store))
    model = ScriptedModelProvider(
        ["asyncio kuyruğunda bekleyen iş sayısı max_queue_size ile sınırlandırılır."]
    )
    retriever = make_retriever(context.article_snapshot)

    outcome = run(
        resume(ResumeRequest(run_id=context.run_id), checkpoint=store, model=model, retriever=retriever)
    )

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.citations
    assert outcome.selected_mode == prepared.route.selected_mode
    assert model.requests[0].metadata["flow"] == "article_qa"
