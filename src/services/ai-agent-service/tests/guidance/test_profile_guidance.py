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
    # Onaylı kayıttaki alanlar canonical profil kaynağından yansır
    # (src/content/author-profile; elle yazılmış ikinci biyografi yok).
    assert "Berkay Kaplan" in outcome.answer
    assert "yazılım eğitmeni" in outcome.answer  # FAQ üçüncü şahıs tanıtımı
    assert "https://mrbekox.dev" in outcome.answer
    assert "https://github.com/MrBekoX" in outcome.answer
    # SEO tabanlı eski statik unvan artık kullanılmaz.
    assert "Software Developer" not in outcome.answer
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


def test_teaching_experience_question_is_not_marked_missing_a03() -> None:
    # A03 (legacy yol): canonical profil eğitmenlik/staj deneyimini YAYIMLAR;
    # "deneyimi var mı?" otomatik "deneyim bilgisi yok" cevabı almaz.
    outcome = run_profile("Berkay'ın eğitmenlik deneyimi var mı?")

    assert outcome.status is RunStatus.COMPLETED
    assert "deneyim süresi" not in (outcome.answer or "")
    assert "2024'ten beri" in outcome.answer  # FAQ: eğitmenlik 2024'ten beri


def test_experience_is_missing_only_for_duration_questions() -> None:
    from agent_core.guidance import MissingInfoField, detect_missing_info_fields

    assert detect_missing_info_fields("Does he have teaching experience?") == []
    assert detect_missing_info_fields("Eğitmenlik deneyimi var mı?") == []
    assert detect_missing_info_fields("How many years of experience does he have?") == [MissingInfoField.EXPERIENCE]
    assert detect_missing_info_fields("Toplam deneyimi ne kadar?") == [MissingInfoField.EXPERIENCE]


def test_broken_canonical_source_fails_with_config_error(tmp_path) -> None:
    # Kaynak bozuksa legacy yol da dürüst config_error döner (servis çökmez).
    import shutil

    from agent_core.adapters import StaticProfileRepository
    from agent_core.profile import resolve_profile_dir

    target = tmp_path / "author-profile"
    shutil.copytree(resolve_profile_dir(), target)
    (target / "profile.json").write_bytes((target / "profile.json").read_bytes() + b" ")

    outcome = run_profile("Blogun sahibi kimdir?", profile_repository=StaticProfileRepository(directory=target))

    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.CONFIG_ERROR
    assert "hash" in (outcome.error_message or "")
