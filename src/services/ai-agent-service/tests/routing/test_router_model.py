"""Router modeli yolu — belirsiz durumlarda yapılandırılmış çıktı ve sıkma.

Plan A5: "Kesin durumlarda kuralları, belirsiz durumlarda yapılandırılmış
çıktı üreten router modelini kullan. LLM'nin ürettiği limitleri doğrudan
uygulama; doğrulanmış politika profiline eşle."

Bu testler double model kullanır (is_test_double); double başarısı gerçek
sağlayıcı başarısı sayılmaz (main-prompt kuralı).
"""

from __future__ import annotations

import pytest

import routing_helpers
from routing_helpers import (
    ExplodingRouterModel,
    FailingRouterModel,
    ScriptedRouterModel,
    make_context,
    run,
    suggestion_json,
)

from agent_core.entrypoints import prepare_and_route
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import AgentMode, RunIntent
from agent_core.routing import build_router_request, parse_router_suggestion, route_for_context


AMBIGUOUS_QUESTION = "Bu makaledeki öneriyi özetler misin?"


def make_ambiguous_context(**overrides):
    defaults = {"question": AMBIGUOUS_QUESTION, "article_id": None}
    defaults.update(overrides)
    return make_context(**defaults)


# --- Yapılandırılmış çıktı ayrıştırma ---

def test_parse_accepts_plain_and_fenced_json() -> None:
    plain = parse_router_suggestion(suggestion_json(selected_mode="analysis", intent="explain"))
    fenced = parse_router_suggestion(
        "```json\n" + suggestion_json(selected_mode="analysis", intent="explain") + "\n```"
    )

    assert plain is not None and fenced is not None
    assert plain.selected_mode is AgentMode.ANALYSIS
    assert plain.intent is RunIntent.EXPLAIN
    assert fenced.selected_mode is AgentMode.ANALYSIS


def test_parse_rejects_invalid_mode_and_non_json() -> None:
    assert parse_router_suggestion(suggestion_json(selected_mode="ultra_fast")) is None
    assert parse_router_suggestion("selam, karar yok") is None
    assert parse_router_suggestion("") is None


def test_parse_drops_web_flag_outside_deep_research() -> None:
    # Taşıma değişmezi: web bayrağı yalnız deep_research'te anlamlıdır.
    suggestion = parse_router_suggestion(suggestion_json(selected_mode="fast", needs_web=True))

    assert suggestion is not None
    assert suggestion.needs_web is False


def test_parse_drops_clarification_without_question_text() -> None:
    suggestion = parse_router_suggestion(
        suggestion_json(needs_clarification=True, clarification_question=None)
    )

    assert suggestion is not None
    assert suggestion.needs_clarification is False
    assert suggestion.clarification_question is None


# --- Belirsizlik geçidi ---

def test_confident_rule_decision_skips_router_model() -> None:
    exploding = ExplodingRouterModel()

    decision = run(route_for_context(make_context(article_id="post-1"), router_model=exploding))

    assert exploding.call_count == 0
    assert decision.brief_reason == "kısa ve tekil soru: doğrudan bilgi araması yeterli"


def test_ambiguous_question_consults_router_model_and_merges_suggestion() -> None:
    model = ScriptedRouterModel(
        [suggestion_json(selected_mode="analysis", intent="explain", brief_reason="özet istemi açıklamaya dönüşebilir")]
    )

    decision = run(route_for_context(make_ambiguous_context(), router_model=model))

    assert model.call_count == 1
    assert decision.selected_mode is AgentMode.ANALYSIS
    assert decision.intent is RunIntent.EXPLAIN
    assert decision.brief_reason.startswith("router modeli önerisi:")
    assert "özet istemi" in decision.brief_reason
    # Politika eşlemesi: bütçe daima doğrulanmış sunucu profili.
    assert decision.budget_profile_id == "router-profile"


def test_invalid_model_output_falls_back_to_rules_with_note() -> None:
    model = ScriptedRouterModel(["bu bir JSON değil"])

    decision = run(route_for_context(make_ambiguous_context(), router_model=model))

    assert model.call_count == 1
    assert decision.selected_mode is AgentMode.FAST  # kural kararı
    assert "doğrulanamadı" in decision.brief_reason
    assert decision.budget_profile_id == "router-profile"


def test_model_failure_falls_back_to_rules_with_note() -> None:
    model = FailingRouterModel(
        PortError(AgentErrorCode.PROVIDER_ERROR, "router sağlayıcısı yanıt vermiyor", port="ModelProvider")
    )

    decision = run(route_for_context(make_ambiguous_context(), router_model=model))

    assert model.call_count == 1
    assert decision.selected_mode is AgentMode.FAST
    assert "kullanılamadı" in decision.brief_reason


def test_cancelled_router_call_propagates() -> None:
    model = FailingRouterModel(
        PortError(AgentErrorCode.CANCELLED, "iptal edildi", port="ModelProvider")
    )

    with pytest.raises(PortError) as excinfo:
        run(route_for_context(make_ambiguous_context(), router_model=model))

    assert excinfo.value.code is AgentErrorCode.CANCELLED


# --- Sıkma: modelin limitleri asla uygulanmaz ---

def test_model_numeric_limits_are_never_applied() -> None:
    # Model geçersiz sayısal "limit" alanları üretir; hiçbiri okunmaz/kullanılmaz.
    malicious = (
        '{"intent": "explain", "selected_mode": "analysis", "needs_web": false, '
        '"needs_clarification": false, "clarification_question": null, '
        '"brief_reason": "bütçeyi yükselt", "max_model_calls": 999999, '
        '"max_total_tokens": 1000000000, "top_k": 500}'
    )
    model = ScriptedRouterModel([malicious])

    decision = run(route_for_context(make_ambiguous_context(), router_model=model))

    payload = decision.model_dump()
    assert "max_model_calls" not in payload
    assert "max_total_tokens" not in payload
    assert "top_k" not in payload
    # Karar doğrulanmış politika profiline bağlı kalır (sunucu profili).
    assert decision.budget_profile_id == "router-profile"


def test_model_web_suggestion_without_research_mode_is_dropped() -> None:
    model = ScriptedRouterModel(
        [suggestion_json(selected_mode="fast", needs_web=True, brief_reason="web şart")]
    )

    decision = run(route_for_context(make_ambiguous_context(), router_model=model))

    assert decision.selected_mode is AgentMode.FAST
    assert decision.needs_web is False  # değişmez: web bayrağı yalnız deep_research'te
    assert "web şart" in decision.brief_reason  # gerekçe metni alınır, bayrak sıkılır


def test_router_request_is_structured_and_declares_policy_boundary() -> None:
    context = make_ambiguous_context()

    request = build_router_request(context)

    assert request.metadata["role"] == "router"
    assert request.metadata["output"] == "json"
    assert "JSON" in (request.system or "")
    assert "limit" in (request.system or "")  # sayısal limit üretme kuralı istemde
    assert AMBIGUOUS_QUESTION in request.prompt
    assert "Makale bağlamı: yok" in request.prompt


# --- Giriş noktası entegrasyonu ---

def test_prepare_and_route_uses_router_model_only_for_ambiguity() -> None:
    confident_model = ExplodingRouterModel()

    prepared = run(
        prepare_and_route(make_context(article_id="post-1"), router_model=confident_model)
    )
    assert confident_model.call_count == 0
    assert prepared.route.selected_mode is AgentMode.FAST

    ambiguous_model = ScriptedRouterModel(
        [suggestion_json(selected_mode="analysis", intent="summarize")]
    )
    prepared_ambiguous = run(
        prepare_and_route(make_ambiguous_context(), router_model=ambiguous_model)
    )
    assert ambiguous_model.call_count == 1
    assert prepared_ambiguous.route.selected_mode is AgentMode.ANALYSIS
    assert prepared_ambiguous.route.intent is RunIntent.SUMMARIZE


def test_prepared_run_checkpoint_roundtrips_a5_route_fields() -> None:
    from agent_core.adapters.test_doubles import FakeCheckpointStore
    from agent_core.entrypoints import PreparedRun

    store = FakeCheckpointStore()
    prepared = run(prepare_and_route(make_ambiguous_context(), checkpoint=store))

    checkpoint_id, payload = run(store.load_latest(prepared.context.run_id))
    restored = PreparedRun.model_validate_json(payload)

    assert checkpoint_id == "prepared:run"
    assert restored.route == prepared.route
    assert restored.route.budget_profile_id == "router-profile"
    assert restored.route.intent.value == "summarize"  # kural kararı: özet sınıfı soru
