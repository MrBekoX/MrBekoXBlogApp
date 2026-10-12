"""Dil değişimi testleri (plan A9 kabul ölçütü: "Türkçe ve İngilizce cevap").

Aynı niyet, farklı dil kodu: şablon dili sorunun dilini izler; içerik
onaylı kayıtlardan aynen taşınır.
"""

from __future__ import annotations

from agent_core.guidance import run_guidance
from agent_core.models import RunIntent, RunStatus

from .conftest import TEST_CATALOG, make_guidance_context, make_route, run


def test_profile_language_switch_tr_en() -> None:
    from agent_core.adapters import StaticProfileRepository

    tr = run(
        run_guidance(
            make_guidance_context("Blogun sahibi kimdir?", language="tr"),
            make_route(RunIntent.PROFILE),
            profile_repository=StaticProfileRepository(),
        )
    ).outcome
    en = run(
        run_guidance(
            make_guidance_context("Who is the author of this blog?", language="en"),
            make_route(RunIntent.PROFILE),
            profile_repository=StaticProfileRepository(),
        )
    ).outcome

    assert tr.status is RunStatus.COMPLETED and en.status is RunStatus.COMPLETED
    assert "Bağlantılar:" in tr.answer and "Skills" not in tr.answer
    assert "Links:" in en.answer and "Yetkinlikler" not in en.answer
    # İçerik (isim/bağlantılar) iki dilde aynı onaylı kayıttan gelir.
    assert "Berkay Kaplan" in tr.answer and "Berkay Kaplan" in en.answer


def test_missing_info_question_language_switch() -> None:
    from agent_core.adapters import StaticProfileRepository

    tr = run(
        run_guidance(
            make_guidance_context("Ücretiniz nedir?", language="tr"),
            make_route(RunIntent.PROFILE),
            profile_repository=StaticProfileRepository(),
        )
    ).outcome
    en = run(
        run_guidance(
            make_guidance_context("What is your pricing?", language="en"),
            make_route(RunIntent.PROFILE),
            profile_repository=StaticProfileRepository(),
        )
    ).outcome

    assert tr.status is RunStatus.NEEDS_INPUT and en.status is RunStatus.NEEDS_INPUT
    assert any("ücret/fiyat" in q for q in tr.unresolved_questions)
    assert any("rates/pricing" in q for q in en.unresolved_questions)


def test_suggestion_language_switch() -> None:
    tr = run(
        run_guidance(
            make_guidance_context("Bana langgraph ile ilgili makale önerir misin?", language="tr"),
            make_route(RunIntent.CONTENT_SUGGESTION),
            article_catalog=TEST_CATALOG,
        )
    ).outcome
    en = run(
        run_guidance(
            make_guidance_context("Recommend an article about langgraph agents", language="en"),
            make_route(RunIntent.CONTENT_SUGGESTION),
            article_catalog=TEST_CATALOG,
        )
    ).outcome

    assert tr.status is RunStatus.COMPLETED and en.status is RunStatus.COMPLETED
    assert "İlginize göre makale önerileri:" in tr.answer
    assert "Articles matched to your interests:" in en.answer
