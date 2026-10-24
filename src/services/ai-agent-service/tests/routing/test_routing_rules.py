"""Router kural kararları — plan A5'in yedi karar ölçütü ve kabul senaryoları.

Kabul ölçütleri (plan A5): kısa karmaşık soru, uzun basit soru, güncellik
sorusu, açık mod tercihi ve eksik bağlam ayrılır. Özet sayılar değil plan
metni asıl kaynaktır (L003): her test plan ölçütünü adıyla sabitler.

Kesin kararlarda model çağrısı YOKTUR (plan A1: karar bir kez, model
çağrısız hesaplanır).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import routing_helpers
from routing_helpers import make_context, run

from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import AgentMode, ModePreference, RouteDecision, RunIntent, SourceScope
from agent_core.routing import (
    clarification_question_for,
    decide_mode,
    is_multi_part_question,
    route_for_context,
    split_answer_headings,
)


def decide(context) -> "object":
    """Kural kararını router modelsiz üretir (kesin yol)."""
    return run(route_for_context(context))


# --- Ölçüt 6: açık mod tercihi ---

def test_explicit_preference_wins_over_question_signals() -> None:
    context = make_context(
        question="Konuyu derinlemesine araştır ve karşılaştır",
        mode_preference="fast",
    )

    decision = decide(context)

    assert decision.selected_mode is AgentMode.FAST
    assert "tercih" in decision.brief_reason


def test_explicit_deep_research_preference_keeps_web_flag() -> None:
    context = make_context(mode_preference="deep_research", article_id="post-1")

    decision = decide(context)

    assert decision.selected_mode is AgentMode.DEEP_RESEARCH
    assert decision.needs_web is True
    assert decision.source_scope is SourceScope.ARTICLE_AND_WEB


# --- Kabul: kısa karmaşık soru (çok bölümlü → analysis) ---

def test_short_complex_multi_part_question_routes_to_analysis() -> None:
    question = "Kuyruk sınırı nasıl ayarlanır ve QueueFull hatası nasıl yönetilir?"
    context = make_context(question=question, article_id="post-1")

    decision = decide(context)

    assert decision.selected_mode is AgentMode.ANALYSIS
    assert decision.intent is RunIntent.ARTICLE_QA
    assert "çok bölümlü" in decision.brief_reason
    assert is_multi_part_question(question)
    assert decision.needs_web is False


def test_multi_part_split_yields_per_section_headings() -> None:
    parts = split_answer_headings("Kuyruk sınırı nasıl ayarlanır ve QueueFull hatası nasıl yönetilir?")

    assert [part.text for part in parts] == [
        "Kuyruk sınırı nasıl ayarlanır",
        "QueueFull hatası nasıl yönetilir",
    ]


# --- Kabul: uzun basit soru (fast'ta kalır; yalnız uzunluk araştırmaya çevirmez) ---

def test_long_simple_single_clause_question_stays_fast() -> None:
    question = (
        "Makalede anlatılan asyncio kuyruk sınırı önerisine göre önerilen değer "
        "aralığının tam olarak kaç ile kaç arasında olduğunun cevabını, makaledeki "
        "kuyruk bölümünde geçen öneriyle uyumlu, tek parça kalan kısa bir yanıt "
        "olarak bana yazabilir misin"
    )
    # Eski A1 eşiği (240) yalnız uzunluğa bakarak araştırmaya çevirirdi; A5'te
    # çok bölümlülük de gerekir — uzun basit soru fast'ta kalır.
    assert len(question) > 240
    context = make_context(question=question, article_id="post-1")

    decision = decide(context)

    assert decision.selected_mode is AgentMode.FAST
    assert decision.needs_web is False


def test_long_multi_part_question_without_research_signal_stays_analysis() -> None:
    question = (
        "Kuyruk sınırı nasıl ayarlanır ve kuyruk dolunca QueueFull istisnası "
        "nasıl yönetilir ve kod örneğindeki aktarım döngüsü hangi adımlarla işleri "
        "sınırlı kuyruğa taşır ve bu davranış makaledeki hangi bölümlerde açıklanır"
    )
    context = make_context(question=question, article_id="post-1")

    decision = decide(context)

    assert decision.selected_mode is AgentMode.ANALYSIS
    assert len(split_answer_headings(question)) >= 2


# --- Ölçüt 4 + kabul: güncellik sorusu (needs_web + deep_research) ---

def test_freshness_question_requires_web_and_research_mode() -> None:
    context = make_context(question="asyncio kuyruk sınırı için güncel öneri nedir?")

    decision = decide(context)

    assert decision.selected_mode is AgentMode.DEEP_RESEARCH
    assert decision.needs_web is True
    assert decision.intent is RunIntent.RESEARCH
    assert decision.source_scope is SourceScope.ARTICLE_AND_WEB
    assert "güncellik" in decision.brief_reason


def test_update_action_verb_is_not_freshness() -> None:
    # "güncellerim" bir eylem sorusudur; güncel dış kanıt istemez.
    context = make_context(question="Kuyruk yapılandırmasını nasıl güncellerim?", article_id="post-1")

    decision = decide(context)

    assert decision.needs_web is False
    assert decision.selected_mode is AgentMode.FAST


# --- Ölçüt 3: karşılaştırma → analysis ---

def test_comparison_question_routes_to_analysis_with_compare_intent() -> None:
    context = make_context(
        question="asyncio.Queue ile janus kütüphanesi hangisi daha uygun?",
        article_id="post-1",
    )

    decision = decide(context)

    assert decision.selected_mode is AgentMode.ANALYSIS
    assert decision.intent is RunIntent.COMPARE
    assert "karşılaştırma" in decision.brief_reason


# --- Ölçüt 7 + plan A5: eksik bağlam/kişisel bilgi tahminle tamamlanmaz ---

def test_missing_personal_context_asks_clarification_instead_of_guessing() -> None:
    context = make_context(
        question="Benim projemde kuyruk sınırını nasıl ayarlamalıyım?",
        article_id="post-1",
    )

    decision = decide(context)

    assert decision.needs_clarification is True
    assert decision.clarification_question == clarification_question_for("tr")
    assert decision.clarification_question  # boş olmayan açık soru


def test_english_personal_context_gets_english_clarification() -> None:
    context = make_context(
        question="How should I set the queue limit for my project?",
        language="en",
    )

    decision = decide(context)

    assert decision.needs_clarification is True
    assert decision.clarification_question == clarification_question_for("en")


def test_article_reference_without_context_falls_back_to_rules_without_model() -> None:
    # Router modeli verilmediğinde belirsiz durum deterministik kuralıyla çözülür
    # (geçiş davranışı); açıklama sorusu üretilmez, karar geçerlidir.
    context = make_context(question="Bu makaledeki öneriyi özetler misin?")

    decision = run(route_for_context(context, router_model=None))

    assert decision.needs_clarification is False
    assert decision.selected_mode is AgentMode.FAST
    assert decision.budget_profile_id == "router-profile"


# --- RouteDecision sözleşmesi (A5 alanları + A1 uyumu) ---

def test_route_decision_web_flag_only_allowed_for_deep_research() -> None:
    with pytest.raises(ValidationError, match="deep_research"):
        RouteDecision(
            run_id="run-1",
            selected_mode="fast",
            brief_reason="test",
            needs_web=True,
            decided_at=routing_helpers.NOW,
        )


def test_route_decision_requires_clarification_question_when_flagged() -> None:
    with pytest.raises(ValidationError, match="clarification_question"):
        RouteDecision(
            run_id="run-1",
            selected_mode="fast",
            brief_reason="test",
            needs_clarification=True,
            decided_at=routing_helpers.NOW,
        )


def test_route_decision_rejects_question_without_flag() -> None:
    with pytest.raises(ValidationError, match="needs_clarification"):
        RouteDecision(
            run_id="run-1",
            selected_mode="fast",
            brief_reason="test",
            clarification_question="Hangi makale?",
            decided_at=routing_helpers.NOW,
        )


def test_route_decision_legacy_field_names_are_accepted_but_not_serialized() -> None:
    decision = RouteDecision(
        run_id="run-1",
        selected_mode="deep_research",
        reason="A1 girdisi",
        requires_web_search=True,
        decided_at=routing_helpers.NOW,
    )

    assert decision.brief_reason == "A1 girdisi"
    assert decision.needs_web is True
    assert decision.reason == "A1 girdisi"  # okuma takma adı
    assert decision.requires_web_search is True
    payload = decision.model_dump()
    assert "brief_reason" in payload and "reason" not in payload
    assert "needs_web" in payload and "requires_web_search" not in payload
    # JSON gidiş-dönüş A5 alanlarını korur.
    restored = RouteDecision.model_validate_json(decision.model_dump_json())
    assert restored == decision


def test_route_decision_serializes_all_eight_plan_fields() -> None:
    decision = decide(make_context(article_id="post-1"))

    payload = decision.model_dump()
    assert set(payload) == {
        "run_id",
        "selected_mode",
        "intent",
        "source_scope",
        "needs_web",
        "needs_clarification",
        "clarification_question",
        "brief_reason",
        "budget_profile_id",
        "decided_at",
    }


def test_budget_profile_id_binds_verified_server_profile() -> None:
    decision = decide(make_context())

    assert decision.budget_profile_id == "router-profile"  # ExecutionContext.budget_profile.name


def test_mode_upgrade_record_is_bounded_to_fast_to_analysis() -> None:
    from datetime import timedelta

    from agent_core.models import ModeUpgradeRecord

    record = ModeUpgradeRecord(
        from_mode="fast",
        to_mode="analysis",
        reason="çok bölümlü soru",
        upgraded_at=routing_helpers.NOW + timedelta(seconds=1),
    )
    assert record.from_mode is AgentMode.FAST

    with pytest.raises(ValidationError):
        ModeUpgradeRecord(
            from_mode="analysis",
            to_mode="fast",
            reason="geri düşüş yasak",
            upgraded_at=routing_helpers.NOW,
        )
    with pytest.raises(ValidationError):
        ModeUpgradeRecord(
            from_mode="fast",
            to_mode="deep_research",
            reason="derin araştırmaya yükseltme A5 kapsamı dışı",
            upgraded_at=routing_helpers.NOW,
        )


# --- decide_mode doğrudan sözleşmesi (A1 imzası korunur) ---

def test_decide_mode_prefers_selection_over_signals() -> None:
    assert (
        decide_mode(
            "Konuyu araştır ve karşılaştır",
            has_selection=True,
            preference=ModePreference.AUTO,
        )
        is AgentMode.ANALYSIS
    )


def test_decide_mode_length_alone_no_longer_routes_to_research() -> None:
    long_simple = "a" * 300
    assert (
        decide_mode(long_simple, has_selection=False, preference=ModePreference.AUTO)
        is AgentMode.FAST
    )
