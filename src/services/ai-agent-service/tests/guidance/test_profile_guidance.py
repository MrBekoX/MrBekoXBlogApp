"""Profil davranışı testleri (plan A9: "Profil ve proje davranışı").

Kabul ölçütleri karşılanan senaryolar: profil tanıtımı onaylı kayıttan
cevaplanır; eksik deneyim/ücret/müsaitlik UYDURULMAZ ve ``needs_input`` ile
bildirilir; port arızaları dürüst terminale çevrilir. Model çağrısı YOKTUR.
"""

from __future__ import annotations

import re

from agent_core.errors import AgentErrorCode
from agent_core.guidance import run_guidance
from agent_core.models import RunIntent, RunStatus

from .conftest import (
    ExplodingModelProvider,
    FailingProfileRepository,
    make_guidance_context,
    make_route,
    run,
)


_UNSET = object()


def run_profile(question: str, *, language: str = "tr", profile_repository=_UNSET):
    from agent_core.adapters import StaticProfileRepository

    context = make_guidance_context(question, language=language)
    repo = StaticProfileRepository() if profile_repository is _UNSET else profile_repository
    return run(
        run_guidance(
            context,
            make_route(RunIntent.PROFILE),
            profile_repository=repo,
        )
    ).outcome


def test_profile_intro_answered_from_approved_record_without_model() -> None:
    from agent_core.adapters import StaticProfileRepository

    model = ExplodingModelProvider()
    context = make_guidance_context("Blogun sahibi kimdir, bana kendisinden bahseder misin?")
    result = run(
        run_guidance(
            context,
            make_route(RunIntent.PROFILE),
            profile_repository=StaticProfileRepository(),
            progress=None,
            cancel=None,
        )
    )

    assert model.call_count == 0  # rehberlik deterministiktir; model çağrılmaz
    outcome = result.outcome
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.usage.model_calls == 0
    # Onaylı kayıttaki alanlar aynen yansır (site-config.ts gerçek değerleri).
    assert "Sample Author" in outcome.answer
    assert "Software Developer" in outcome.answer
    assert "https://mrbekox.dev" in outcome.answer
    assert "https://example.invalid/author" in outcome.answer
    # Eksik bilgi sorulmadı; uydurma not da gerekmez.
    assert "bulunmuyor" not in outcome.answer


def test_missing_experience_is_reported_and_never_invented() -> None:
    # Plan A9: "Eksik deneyim, ücret veya müsaitlik bilgisini uydurma."
    outcome = run_profile("Kaç yıllık deneyiminiz var?")

    assert outcome.status is RunStatus.NEEDS_INPUT
    assert outcome.unresolved_questions, "eksik bilgi için açık soru zorunludur"
    assert "deneyim süresi" in " ".join(outcome.unresolved_questions)
    # Uydurma yasağı: cevapta "N yıl" biçiminde uydurma deneyim beyanı YOKTUR.
    assert re.search(r"\b\d+\s*y[ıi]l\b", outcome.answer or "") is None
    assert "tahminle doldurulmaz" in outcome.answer


def test_rate_and_availability_questions_report_missing() -> None:
    outcome = run_profile("Ücret tarifiniz nedir ve freelance işlere müsait misiniz?")

    assert outcome.status is RunStatus.NEEDS_INPUT
    joined = " ".join(outcome.unresolved_questions)
    assert "ücret/fiyat" in joined
    assert "müsaitlik" in joined


def test_unwired_profile_repository_fails_with_config_error() -> None:
    # Onaylı kaynak bağlı değilken kayıtsız model yoluna düşülmez.
    outcome = run_profile("Blogun sahibi kimdir?", profile_repository=None)

    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.CONFIG_ERROR


def test_profile_port_error_becomes_failed_outcome() -> None:
    outcome = run_profile("Blogun sahibi kimdir?", profile_repository=FailingProfileRepository())

    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.NOT_FOUND
    assert outcome.error_message is not None
