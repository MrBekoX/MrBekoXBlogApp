"""Analysis alt akışı testleri (plan A5).

Mod farkı farklı adımlar ve bütçelerle kanıtlanır: analysis soruyu cevap
başlıklarına ayırır, başlık başına arar, karşılıksız başlıkta retrieval
kapsamını sınırlı artırır, kanıt kontrolü ile karşılıksız başlıklar için
uydurma içerik üretmez ve açıklamayı makale kaynaklarıyla (atıf + bölüm
bağlantısı) ilişkilendirir.

Test double'lar gerçek LLM/embedding değildir (is_test_double); başarılar
yalnız akış davranışını kanıtlar.
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

from agent_core.analysis import (
    AnalysisConfig,
    analysis_policy_for,
    build_analysis_plan,
    run_article_analysis,
)
from agent_core.models import AgentMode, RunStatus

MULTI_PART_QUESTION = "Kuyruk sınırı nasıl ayarlanır ve QueueFull hatası nasıl yönetilir?"


def make_analysis_context(**overrides):
    defaults = {"question": MULTI_PART_QUESTION, "mode_preference": "analysis"}
    defaults.update(overrides)
    return make_qa_context(make_qa_snapshot(), **defaults)


def make_route(context):
    from agent_core.models import RouteDecision
    from agent_core.routing import route_for_context

    return run(route_for_context(context))


# --- Planlama: soru → küçük cevap başlıkları ---

def test_analysis_plan_splits_question_into_headings() -> None:
    context = make_analysis_context()

    plan = build_analysis_plan(context)

    assert [part.text for part in plan.headings] == [
        "Kuyruk sınırı nasıl ayarlanır",
        "QueueFull hatası nasıl yönetilir",
    ]


def test_analysis_plan_caps_heading_count() -> None:
    question = (
        "a konusu nasıl çalışır ve b konusu nasıl çalışır ve c konusu nasıl çalışır "
        "ve d konusu nasıl çalışır ve e konusu nasıl çalışır"
    )
    context = make_analysis_context(question=question)

    plan = build_analysis_plan(context, max_headings=AnalysisConfig().max_headings)

    assert len(plan.headings) <= AnalysisConfig().max_headings


# --- Akış: başlık başına arama + kaynaklı açıklama ---

def test_analysis_flow_retrieves_per_heading_and_cites_sections() -> None:
    snapshot = make_qa_snapshot()
    records = build_records(snapshot)
    context = make_analysis_context()
    route = make_route(context)
    retriever = ScriptedRetriever([[records[2]], [records[3]]])
    model = ScriptedModelProvider(
        [
            "## Kuyruk sınırı\n\n"
            "asyncio kuyruğunda bekleyen iş sayısı `max_queue_size` ile sınırlandırılır; "
            "önerilen değer aralığı 100 ile 1000 arasındadır.\n\n"
            "## Hata yönetimi\n\n"
            "Kuyruk dolunca `QueueFull` istisnası fırlar; akış try/except ile yönetilir."
        ]
    )

    result = run(run_article_analysis(context, route, model=model, retriever=retriever))
    outcome = result.outcome

    # Mod farkı — adımlar: her başlık için ayrı arama yapıldı.
    assert retriever.queries == [
        "Kuyruk sınırı nasıl ayarlanır",
        "QueueFull hatası nasıl yönetilir",
    ]
    # Mod farkı — bütçe: analysis top_k=6, fast QA'nın 4'ünden geniş.
    assert retriever.top_ks == [6, 6]
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.selected_mode is AgentMode.ANALYSIS
    assert model.requests[0].metadata["flow"] == "article_analysis"
    assert outcome.usage.model_calls == 1
    # Analiz cevabı makale kaynaklarıyla ilişkilendirilir: atıf + bölüm bağlantısı.
    assert outcome.citations, "analysis cevabı atıf üretmeli"
    assert result.sections, "analysis cevabı bölüm bağlantısı üretmeli"
    assert all(section.url and section.url.startswith("https://mrbekox.dev/blog/") for section in result.sections)
    assert "Kaynak bölümü:" in outcome.answer
    assert outcome.mode_upgrades == []
    assert outcome.usage.tool_calls == 3  # 1 indeksleme + 2 başlık araması
    assert outcome.usage.web_search_calls == 0


def test_analysis_expands_retrieval_scope_for_uncovered_heading() -> None:
    snapshot = make_qa_snapshot()
    records = build_records(snapshot)
    context = make_analysis_context()
    route = make_route(context)
    # Başlık 1 kanıt bulur; başlık 2 ilk aramada boş döner → kapsam artırma turu.
    retriever = ScriptedRetriever([[records[2]], [], [records[3]]])
    model = ScriptedModelProvider(["## Açıklama\n\nKuyruk dolunca `QueueFull` istisnası fırlar."])

    result = run(run_article_analysis(context, route, model=model, retriever=retriever))

    # Kapsam artırma: başlık sorgusu + makale başlığı, iki katı top_k, tek tur.
    assert len(retriever.queries) == 3
    expanded_query = retriever.queries[-1]
    assert "QueueFull hatası nasıl yönetilir" in expanded_query
    assert snapshot.title in expanded_query
    assert retriever.top_ks[-1] == 12  # analysis top_k=6 → kapsam artışında 12
    assert result.state["scope_expanded"] is True
    assert result.outcome.status is RunStatus.COMPLETED
    assert result.outcome.citations


def test_analysis_reports_uncovered_heading_without_fabrication() -> None:
    snapshot = make_qa_snapshot()
    records = build_records(snapshot)
    context = make_analysis_context()
    route = make_route(context)
    # Başlık 2 kapsamı artırıldıktan sonra da karşılıksız.
    retriever = ScriptedRetriever([[records[2]], [], []])
    model = ScriptedModelProvider(
        ["## Kuyruk sınırı\n\nİş sayısı `max_queue_size` ile sınırlandırılır, önerilen aralık 100 ile 1000 arasındadır."]
    )

    result = run(run_article_analysis(context, route, model=model, retriever=retriever))
    outcome = result.outcome
    coverage = result.state["coverage"]

    assert coverage.uncovered_indexes == [1]
    # Karşılıksız başlık için uydurma içerik/atıf yok; deterministik kapsam notu var.
    assert "makalede karşılanmıyor" in outcome.answer
    assert "QueueFull hatası nasıl yönetilir" in outcome.answer
    assert all(citation.chunk_index == 2 for citation in outcome.citations)
    assert len(result.sections) == 1


def test_analysis_without_any_evidence_answers_deterministically_without_model_call() -> None:
    context = make_analysis_context()
    route = make_route(context)
    retriever = ScriptedRetriever([[], [], [], []])  # 2 başlık + 2 kapsam artırma boş
    model = ScriptedModelProvider([])  # hiç çağrılmamalı; çağrılırsa test kırılır

    result = run(run_article_analysis(context, route, model=model, retriever=retriever))
    outcome = result.outcome

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.answer.startswith("Bu sorunun yanıtı makalede yer almıyor.")
    assert outcome.citations == []
    assert model.call_count == 0


def test_analysis_budget_policy_covers_heading_steps_but_stays_under_profile() -> None:
    profile = make_analysis_context().budget_profile
    config = AnalysisConfig()

    policy = analysis_policy_for(profile, config)

    needed = config.max_headings * (1 + config.max_expansion_rounds) + 1
    assert policy.max_tool_attempts >= needed
    # Sunucu profili nihai üst sıradır: model/token/süre profilden aşılıramaz.
    assert policy.max_model_calls == profile.max_model_calls
    assert policy.max_total_tokens == profile.max_total_tokens
    assert policy.max_duration_seconds == profile.max_duration_seconds
