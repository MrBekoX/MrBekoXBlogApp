"""Who am I konu farkındalıklı routing (A14, A17, A18, A31).

- ``who_am_i`` konusu her sinyalden bağımsız PROFILE + profil kapsamı + web yok.
- AUTO (ve v1) konuda blog sahibi soruları "açıkla/özetle/araştır" ifadelerine
  rağmen PROFILE'dır; "CQRS nedir?" gibi teknik sorular etkilenmez.
- AUTO ziyaretçi-kimliği belirsizliği netleştirme işaretli PROFILE rotasıdır.
Kesin kararlarda router modeli ÇAĞRILMAZ.
"""

from __future__ import annotations

import pytest

from routing_helpers import ExplodingRouterModel, make_context, run

from agent_core.models import AgentMode, ConversationTopic, RunIntent, SourceScope
from agent_core.profile import load_profile_source, resolve_profile_dir
from agent_core.routing import (
    OWNER_PROFILE_REASON,
    WHO_AM_I_REASON,
    is_visitor_identity_route,
    route_for_context,
)

SNAPSHOT = load_profile_source(resolve_profile_dir()).snapshot


def decide(question: str, *, topic: str | None = "auto", **overrides):
    fields = dict(question=question, **overrides)
    if topic is not None:
        fields["conversation_topic"] = ConversationTopic(topic)
        fields.setdefault("profile_snapshot", SNAPSHOT)
    context = make_context(**fields)
    router = ExplodingRouterModel()
    decision = run(route_for_context(context, router_model=router))
    assert router.call_count == 0
    return decision


@pytest.mark.parametrize("preference", ["auto", "fast", "analysis", "deep_research"])
@pytest.mark.parametrize(
    "question",
    [
        "Güncel yapay zekâ trendlerini derinlemesine araştır",
        "Bu kodu açıkla ve karşılaştır",
        "Benim projemde kuyruk sınırı nasıl ayarlanır?",
        "Ben kimim?",
    ],
)
def test_who_am_i_topic_forces_profile_without_web_a31(preference: str, question: str) -> None:
    decision = decide(question, topic="who_am_i", mode_preference=preference)

    assert decision.intent is RunIntent.PROFILE
    assert decision.source_scope is SourceScope.PROFILE
    assert decision.needs_web is False
    assert decision.needs_clarification is False
    assert not is_visitor_identity_route(decision)
    expected_mode = AgentMode.FAST if preference == "auto" else AgentMode(preference)
    assert decision.selected_mode is expected_mode
    assert decision.brief_reason.startswith(WHO_AM_I_REASON)


@pytest.mark.parametrize("topic", ["auto", None])
@pytest.mark.parametrize(
    "question",
    [
        "Sample'ın eğitimini açıkla",
        "Sample Author'ın kariyerini özetle",
        "Explain Sample's teaching background",
        "MrBekoX'un mimari yaklaşımını açıkla",
        "Samplein egitimi nedir",
        "Blog sahibinin mimari yaklaşımı nedir?",
    ],
)
def test_owner_biography_questions_route_to_profile_a18(topic, question: str) -> None:
    decision = decide(question, topic=topic)

    assert decision.intent is RunIntent.PROFILE, decision.brief_reason
    assert decision.source_scope is SourceScope.PROFILE
    assert decision.needs_web is False
    assert decision.selected_mode is AgentMode.FAST


@pytest.mark.parametrize("topic", ["auto", None])
@pytest.mark.parametrize(
    ("question", "expected_intent"),
    [
        ("CQRS nedir?", None),
        ("CQRS'i açıkla", None),
        ("What is CQRS?", None),
        ("Bu kodu açıkla", RunIntent.EXPLAIN),
        ("Onion Architecture ile Clean Architecture farkı nedir?", RunIntent.COMPARE),
    ],
)
def test_technical_questions_are_not_forced_into_profile_a18(topic, question: str, expected_intent) -> None:
    decision = decide(question, topic=topic)

    assert decision.intent is not RunIntent.PROFILE
    if expected_intent is not None:
        assert decision.intent is expected_intent


def test_article_reference_keeps_article_flow_even_with_author_mention() -> None:
    decision = decide("Bu makalede yazar CQRS'i nasıl açıklıyor?", article_id="post-1")

    assert decision.intent is not RunIntent.PROFILE


def test_weak_author_alias_does_not_hijack_article_bound_questions() -> None:
    article = decide("Yazar CQRS'i nasıl kullanıyor?", article_id="post-1")
    general = decide("Yazar hangi üniversitede okudu?")

    assert article.intent is not RunIntent.PROFILE
    assert general.intent is RunIntent.PROFILE


def test_auto_owner_question_with_research_signal_stays_profile_without_web_a31() -> None:
    auto = decide("Sample'ın projelerini derinlemesine araştır")
    explicit_deep = decide("Sample'ın projelerini araştır", mode_preference="deep_research")

    assert auto.intent is RunIntent.PROFILE and auto.selected_mode is AgentMode.FAST and auto.needs_web is False
    assert explicit_deep.intent is RunIntent.PROFILE
    assert explicit_deep.selected_mode is AgentMode.DEEP_RESEARCH
    assert explicit_deep.needs_web is False


def test_article_bound_auto_owner_question_routes_to_profile_a17() -> None:
    decision = decide(
        "Sample hangi üniversitede okudu?",
        article_id="post-1",
        selected_text="Yazar Harvard'dan mezun oldu.",
    )

    assert decision.intent is RunIntent.PROFILE
    assert decision.source_scope is SourceScope.PROFILE
    assert decision.brief_reason.startswith(OWNER_PROFILE_REASON)


@pytest.mark.parametrize("question", ["Ben kimim?", "Who am I?", "Beni tanıyor musun?", "kim oldugumu biliyor musun"])
def test_auto_visitor_identity_is_marked_clarification_a14(question: str) -> None:
    decision = decide(question)

    # Profil iddiası/korpus yok: GENERAL niyet ve kapsam (snapshot gerektirmez).
    assert decision.intent is RunIntent.GENERAL
    assert decision.source_scope is SourceScope.GENERAL
    assert is_visitor_identity_route(decision)
    assert decision.needs_clarification is False  # needs_input DEĞİL; tamamlanan netleştirme
    assert decision.needs_web is False


def test_canonical_owner_aliases_all_trigger_profile_routing() -> None:
    document = load_profile_source(resolve_profile_dir())
    for alias in document.owner.aliases:
        decision = decide(f"{alias} hangi üniversitede okudu?")
        assert decision.intent is RunIntent.PROFILE, alias


def test_legacy_a9_intents_are_preserved() -> None:
    assert decide("Bu blogda hangi projeler var?", topic=None).intent is RunIntent.PROJECTS
    assert decide("Sample'ın projeleri neler?", topic=None).intent is RunIntent.PROJECTS  # v1 A9 korunur
    assert decide("Sample'ın projeleri neler?", topic="auto").intent is RunIntent.PROFILE  # v2: profil RAG
    assert decide("Sample ile iş birliği yapmak istiyorum").intent is RunIntent.COLLABORATION
    assert decide("Bana makale önerir misin?").intent is RunIntent.CONTENT_SUGGESTION


def test_personal_context_overrides_owner_detection() -> None:
    decision = decide("Benim projemde Sample'ın mimari önerisini nasıl uygularım?", article_id="post-1")

    assert decision.intent is not RunIntent.PROFILE
    assert decision.needs_clarification is True


def test_router_model_cannot_select_profile_on_its_own_in_v2() -> None:
    from routing_helpers import ScriptedRouterModel, suggestion_json

    long_question = "Kuyruk tasarımında dikkat edilmesi gereken genel noktalar nelerdir? " * 4
    context = make_context(question=long_question, conversation_topic=ConversationTopic.AUTO)
    router = ScriptedRouterModel([suggestion_json(intent="profile", selected_mode="fast")])

    decision = run(route_for_context(context, router_model=router))

    assert router.call_count == 1
    assert decision.intent is not RunIntent.PROFILE
    assert decision.source_scope is not SourceScope.PROFILE
