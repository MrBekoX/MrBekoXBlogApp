"""Router'ın A9 niyet bağları (plan A9: "Profil, proje, içerik önerisi ve iş
birliği niyetlerini router'a bağla").

Sözleşmeler: AUTO tercihte bu niyetler FAST'a sabitlenir, ``needs_web``
false kalır, router modeline DANILMAZ (deterministik kesin karar sınıfı);
kişisel bağlam sinyali ("benim projem") rehberlik sınıflamasını ezer ve
mevcut A5 kararları (araştırma/karşılaştırma/açıklama) korunur.
"""

from __future__ import annotations

from agent_core.entrypoints import prepare_and_route
from agent_core.models import AgentMode, RunIntent, SourceScope
from agent_core.routing import classify_guidance_intent, route_for_context

from .conftest import (
    ExplodingModelProvider,
    make_article_bound_context,
    make_guidance_context,
    run,
)


def decide(question: str, *, language: str = "tr", **overrides):
    context = make_guidance_context(question, language=language, **overrides)
    return run(route_for_context(context, router_model=ExplodingModelProvider()))


def test_profile_question_binds_profile_intent_with_fast_mode() -> None:
    decision = decide("Blogun sahibi kimdir?")

    assert decision.intent is RunIntent.PROFILE
    assert decision.selected_mode is AgentMode.FAST
    assert decision.needs_web is False
    assert decision.source_scope is SourceScope.PROFILE


def test_projects_question_binds_projects_intent() -> None:
    decision = decide("Bu blogda hangi projeler var?")

    assert decision.intent is RunIntent.PROJECTS
    assert decision.selected_mode is AgentMode.FAST
    assert decision.source_scope is SourceScope.PROJECTS


def test_suggestion_question_binds_content_suggestion_intent() -> None:
    decision = decide("Bana makale önerir misin?")

    assert decision.intent is RunIntent.CONTENT_SUGGESTION
    assert decision.selected_mode is AgentMode.FAST
    assert decision.source_scope is SourceScope.GENERAL


def test_collaboration_question_binds_collaboration_intent() -> None:
    decision = decide("Sitenizle iş birliği yapmak istiyorum")

    assert decision.intent is RunIntent.COLLABORATION
    assert decision.selected_mode is AgentMode.FAST
    assert decision.needs_web is False


def test_guidance_questions_never_consult_router_model() -> None:
    # Kesin karar sınıfı: model çağrısı YAPILMAZ (patlayan double kanıtı).
    decision = decide("Blogun sahibi kimdir ve hangi projelerde çalışıyor?")
    assert decision.intent in (RunIntent.PROFILE, RunIntent.PROJECTS)


def test_personal_context_signal_overrides_guidance_classification() -> None:
    # "benim projem" → rehberlik değil, eksik-bilgi akışı (A5 kuralı korunur).
    decision = decide("Benim projemde kuyruk sınırını nasıl ayarlamalıyım?", article_id="post-1")

    assert decision.needs_clarification is True
    assert decision.intent not in (RunIntent.PROFILE, RunIntent.PROJECTS)


def test_rate_question_routes_to_profile_for_honest_needs_input() -> None:
    # Uydurulması yasak alanlar genel model yoluna bırakılmaz; profil akışı
    # needs_input ile karşılar.
    decision = decide("Ücret tarifiniz nedir?")

    assert decision.intent is RunIntent.PROFILE


def test_multi_part_collab_question_still_forced_fast() -> None:
    # AUTO tercihte rehberlik/iş birliği niyeti çok bölümlü olsa da FAST'tadır.
    decision = decide("Sitenizle iş birliği yapmak istiyorum; ayrıca konuk yazı yazmak istiyorum")

    assert decision.intent is RunIntent.COLLABORATION
    assert decision.selected_mode is AgentMode.FAST


def test_existing_article_qa_question_is_not_hijacked() -> None:
    decision = decide("Bu makaledeki kuyruk sınırı önerisi nedir?", article_id="post-1")

    assert decision.intent is RunIntent.ARTICLE_QA
    assert decision.selected_mode is AgentMode.FAST


def test_classify_helper_returns_none_for_plain_questions() -> None:
    assert classify_guidance_intent("Bu makaledeki öneriyi özetler misin?") is None
    assert classify_guidance_intent("asyncio kuyruk sınırı için güncel öneri nedir?") is None


def test_prepare_and_route_carries_collab_intent_to_prepared_run() -> None:
    context = make_article_bound_context("Sitenizle iş birliği yapmak istiyorum")

    prepared = run(prepare_and_route(context))

    assert prepared.route.intent is RunIntent.COLLABORATION
    assert prepared.collab_state is None  # taze hazırlıkta state boş; akışta dolar
