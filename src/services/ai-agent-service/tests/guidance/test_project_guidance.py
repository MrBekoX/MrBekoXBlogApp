"""Proje rehberi testleri (plan A9: "Proje amacı, teknolojiler, katkı ve
doğrulanmış bağlantıları açıkla").

Kayıtlar yalnız repo içi gerçek kaynaklardan (README, decisions) derlenen
onaylı statik kayıtlardır; bağlantılar kayıttan aynen yansır, uydurma proje
üretilemez.
"""

from __future__ import annotations

from agent_core.guidance import run_guidance
from agent_core.models import RunIntent, RunStatus

from .conftest import make_guidance_context, make_route, run


def run_projects(question: str, *, language: str = "tr", project_repository=object()):
    context = make_guidance_context(question, language=language)
    return run(
        run_guidance(context, make_route(RunIntent.PROJECTS), project_repository=project_repository)
    ).outcome


def test_real_projects_listed_with_technologies_and_verified_links() -> None:
    from agent_core.adapters import StaticProjectRepository

    outcome = run_projects("Blogda hangi projeler var ve hangi teknolojileri kullanıyor?", project_repository=StaticProjectRepository())

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.source_scope.value == "projects"
    # Gerçek repo içi projeler amaç/teknoloji/bağlantıyla listelenir.
    for name in ("MrBekoXBlogApp", "ai-agent-service", "BuildingBlocks.Messaging"):
        assert name in outcome.answer
    assert "https://github.com/MrBekoX/MrBekoXBlogApp" in outcome.answer
    assert ".NET 10" in outcome.answer
    assert "LangGraph" in outcome.answer


def test_project_guidance_answers_in_english_when_asked() -> None:
    from agent_core.adapters import StaticProjectRepository

    outcome = run_projects("What projects have you built and which technologies do they use?", language="en", project_repository=StaticProjectRepository())

    assert outcome.status is RunStatus.COMPLETED
    assert "Projects:" in outcome.answer
    assert "Technologies:" in outcome.answer
    assert "Links:" in outcome.answer


def test_no_matching_interest_lists_all_with_honest_note() -> None:
    from agent_core.adapters import StaticProjectRepository

    outcome = run_projects("素焼きの陶芸プロジェクト", language="tr", project_repository=StaticProjectRepository())

    assert outcome.status is RunStatus.COMPLETED
    assert "eşleşen proje ayrıştırılamadı" in outcome.answer
    assert "MrBekoXBlogApp" in outcome.answer  # kayıtlar yine dürüstçe listelenir


def test_unwired_optional_project_repository_returns_honest_partial_availability() -> None:
    outcome = run_projects("Hangi projeler var?", project_repository=None)

    assert outcome.status is RunStatus.PARTIAL
    assert outcome.error_code is None
    assert "onaylı kayıt olmadan cevap üretilmez" in outcome.answer
