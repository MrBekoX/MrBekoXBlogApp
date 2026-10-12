"""İlgiye göre makale önerisi testleri (plan A9: "İlgiye göre makale önerirken
kısa uygunluk gerekçesi ve kaynak bağlantısı ver").

Katalog girdisi AÇIK test verisidir; öneri yalnız verilen onaylı kayıtlarla
çalışır — boş kataloğa karşı dürüst "kullanılamaz" sonucu döner (uydurma yok).
"""

from __future__ import annotations

from agent_core.guidance import run_guidance
from agent_core.models import RunIntent, RunStatus

from .conftest import TEST_CATALOG, make_guidance_context, make_route, run


def run_suggestion(question: str, *, catalog=None, language: str = "tr"):
    context = make_guidance_context(question, language=language)
    return run(
        run_guidance(context, make_route(RunIntent.CONTENT_SUGGESTION), article_catalog=catalog)
    ).outcome


def test_suggestion_carries_relevance_reason_and_source_link() -> None:
    outcome = run_suggestion("Bana asyncio ve kuyruk yönetimi hakkında bir makale önerir misin?", catalog=TEST_CATALOG)

    assert outcome.status is RunStatus.COMPLETED
    # Kısa uygunluk gerekçesi: eşleşen konular adıyla anılır.
    assert "asyncio" in outcome.answer
    # Kaynak bağlantısı girdi kaydından aynen taşınır (uydurma link yok).
    assert "https://example.com/posts/asyncio-kuyruk" in outcome.answer
    assert "asyncio kuyruk sınırı yönetimi" in outcome.answer


def test_empty_catalog_returns_honest_partial_without_invention() -> None:
    # Üretim kataloğu repoda gerçek makale listesi olmadığından boştur.
    outcome = run_suggestion("Bana makale önerir misin?", catalog=[])

    assert outcome.status is RunStatus.PARTIAL
    assert "kataloğu" in outcome.answer  # kataloğu (yumuşama): g → ğ
    assert "https://" not in outcome.answer  # uydurma bağlantı yok


def test_no_catalog_argument_same_honest_partial() -> None:
    outcome = run_suggestion("Bana makale önerir misin?", catalog=None)

    assert outcome.status is RunStatus.PARTIAL


def test_unmatched_interest_reports_no_suggestion() -> None:
    outcome = run_suggestion("Bana croissant tarifi önerir misin?", catalog=TEST_CATALOG)

    assert outcome.status is RunStatus.PARTIAL
    assert "eşleşen öneri üretilemedi" in outcome.answer


def test_suggestion_answers_in_english() -> None:
    outcome = run_suggestion(
        "Recommend an article about rabbitmq and reliable messaging",
        catalog=TEST_CATALOG,
        language="en",
    )

    assert outcome.status is RunStatus.COMPLETED
    assert "https://example.com/posts/rabbitmq-mesajlasma" in outcome.answer
