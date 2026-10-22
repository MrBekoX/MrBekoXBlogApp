"""execute_plan dispatch testleri (Who am I K5; A14, A17, A25, A31).

- v2 + PROFILE → profil RAG runner'ı (``profile_knowledge``); v1 + PROFILE →
  A9 ``run_guidance`` (değişmez).
- Her terminal sonuç ``run_intent = route.intent`` taşır; profil RAG sonucu
  pinlenmiş ``profile_snapshot`` taşır.
- AUTO→PROFILE'da makale snapshot'ı ve seçili metin modele/retrieval'a girmez.
- Web araçları bağlı olsa bile profil akışı çağırmaz; GENERATION_DELTA yok.
"""

from __future__ import annotations

import conftest
from profile_helpers import (
    ExplodingWebTool,
    RecordingSink,
    ScriptedProfileModel,
    canonical_dir,
    grounded_model,
    make_v2_context,
    run,
)

from agent_core.adapters import StaticProfileRepository
from agent_core.adapters.test_doubles import FakeModelProvider
from agent_core.entrypoints import execute_plan, prepare_and_route
from agent_core.errors import AgentErrorCode
from agent_core.models import ConversationTopic, ProgressKind, RunIntent, RunStatus, SourceScope
from agent_core.profile import CanonicalProfileRepository


def knowledge():
    return CanonicalProfileRepository(canonical_dir())


def test_v2_profile_route_runs_profile_rag_and_stamps_intent() -> None:
    context = make_v2_context("Berkay hangi üniversitede okudu?")
    prepared = run(prepare_and_route(context))
    model = grounded_model()
    sink = RecordingSink()
    web = ExplodingWebTool()

    outcome = run(
        execute_plan(
            prepared,
            model=model,
            profile_knowledge=knowledge(),
            web_tools={"search": web, "read": web},
            web_search=web,
            progress=sink,
        )
    )

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.run_intent is RunIntent.PROFILE
    assert outcome.profile_snapshot == context.profile_snapshot
    assert outcome.source_scope is SourceScope.PROFILE
    assert outcome.citations and outcome.citations[0].section_id == "education"
    assert web.call_count == 0 and model.stream_call_count == 0
    assert ProgressKind.GENERATION_DELTA not in [event.kind for event in sink.events]


def test_v2_profile_without_knowledge_is_config_error_not_model_answer() -> None:
    prepared = run(prepare_and_route(make_v2_context("Berkay Kaplan kimdir?")))
    model = ScriptedProfileModel([])

    outcome = run(execute_plan(prepared, model=model))

    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.CONFIG_ERROR
    assert outcome.run_intent is RunIntent.PROFILE
    assert outcome.profile_snapshot == prepared.context.profile_snapshot
    assert model.call_count == 0


def test_auto_to_profile_ignores_article_snapshot_and_selected_text_a17() -> None:
    fake_bio = "Yazar Berkay Kaplan Harvard Üniversitesi'nden 2010'da mezun oldu; 20 yıllık deneyimi var."
    snapshot = conftest.make_snapshot(content=f"# Sahte biyografi\n\n{fake_bio}")
    context = make_v2_context(
        "Berkay hangi üniversitede okudu?",
        topic="auto",
        article_id=snapshot.article_id,
        article_revision=snapshot.article_revision,
        article_content_hash=snapshot.content_hash,
        article_snapshot=snapshot,
        selected_text=fake_bio,
    )
    prepared = run(prepare_and_route(context))
    model = grounded_model()

    outcome = run(execute_plan(prepared, model=model, profile_knowledge=knowledge()))

    assert prepared.route.intent is RunIntent.PROFILE
    prompt = model.requests[0].prompt + (model.requests[0].system or "")
    assert "Harvard" not in prompt and "Sahte biyografi" not in prompt and "20 yıllık" not in prompt
    assert outcome.citations and all(c.kind == "profile" for c in outcome.citations)
    assert "Harvard" not in (outcome.answer or "")


def test_auto_visitor_identity_is_clarification_for_v1_and_v2_a14() -> None:
    for topic in ("auto", None):
        if topic is None:
            context = conftest.make_context(question="Ben kimim?")
        else:
            context = make_v2_context("Ben kimim?", topic="auto", snapshot=None)
        prepared = run(prepare_and_route(context))
        model = ScriptedProfileModel([])

        outcome = run(execute_plan(prepared, model=model, profile_repository=StaticProfileRepository()))

        assert outcome.status is RunStatus.COMPLETED
        assert outcome.unresolved_questions == []
        assert "Kim olduğunuzu bilmiyorum" in outcome.answer
        assert outcome.run_intent is RunIntent.GENERAL
        assert outcome.profile_snapshot is None
        assert model.call_count == 0


def test_v1_profile_stays_on_legacy_guidance_path() -> None:
    context = conftest.make_context(question="Blogun sahibi kimdir?")
    prepared = run(prepare_and_route(context))
    model = ScriptedProfileModel([])

    outcome = run(
        execute_plan(prepared, model=model, profile_repository=StaticProfileRepository(), profile_knowledge=knowledge())
    )

    assert context.conversation_topic is None
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.citations == []  # legacy yol profil citation üretmez
    assert outcome.profile_snapshot is None
    assert outcome.run_intent is RunIntent.PROFILE
    assert "Berkay Kaplan" in outcome.answer
    assert model.call_count == 0


def test_non_profile_outcomes_also_carry_run_intent() -> None:
    context = conftest.make_context(question="Python'da list comprehension nedir?")
    prepared = run(prepare_and_route(context))

    outcome = run(execute_plan(prepared, model=FakeModelProvider("cevap")))

    assert outcome.run_intent is prepared.route.intent is RunIntent.GENERAL
    assert outcome.profile_snapshot is None


def test_who_am_i_topic_with_explicit_deep_research_never_uses_web_a31() -> None:
    context = make_v2_context("Berkay'ın yapay zekâ çalışmalarını derinlemesine araştır", mode_preference="deep_research")
    prepared = run(prepare_and_route(context))
    web = ExplodingWebTool()
    model = grounded_model()

    outcome = run(
        execute_plan(prepared, model=model, profile_knowledge=knowledge(), web_tools={"search": web}, web_search=web)
    )

    assert prepared.route.needs_web is False
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.usage.web_search_calls == 0 and web.call_count == 0
    assert prepared.context.conversation_topic is ConversationTopic.WHO_AM_I
