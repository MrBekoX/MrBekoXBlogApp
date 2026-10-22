"""Çıktı doğrulayıcısı sertleştirmesi (kod incelemesi bulguları; A12/A13/A19/A21).

Gerçek canonical parçalarla: kısa alıntı, kaynakta olmayan e-posta/telefon/sayı,
yaş/deneyim türetimi, ``www.``/markdown bağlantı allowlist'i ve kalın URL.
"""

from __future__ import annotations

import json

import pytest

from agent_core.profile import load_profile_source, resolve_profile_dir
from agent_core.profile.chunking import chunk_document
from agent_core.profile.policy import evaluate_policy
from agent_core.profile.validation import EvidenceEntry, validate_model_output

DOCUMENT = load_profile_source(resolve_profile_dir())
CHUNKS = {chunk.section_id: chunk for chunk in chunk_document(DOCUMENT) if chunk.chunk_index == 0}
EVIDENCE = [
    EvidenceEntry(label="S1", chunk=CHUNKS["education"]),
    EvidenceEntry(label="S2", chunk=CHUNKS["contact"]),
]
CHANNELS = [channel.url for channel in DOCUMENT.privacy.contact_channels]
SECTIONS = frozenset(section.section_id for section in DOCUMENT.sections)
QUOTE = "Malatya Turgut Özal Üniversitesi, Bilgisayar Mühendisliği"


def validate(answer: str, *, quote: str = QUOTE, claim: str | None = None):
    payload = {"answer": answer, "claims": [{"text": claim or answer, "sources": ["S1"], "quotes": [quote]}]}
    return validate_model_output(json.dumps(payload, ensure_ascii=False), EVIDENCE, channel_urls=CHANNELS, known_section_ids=SECTIONS)


def test_grounded_answer_with_years_from_evidence_passes() -> None:
    result = validate("Berkay, Malatya Turgut Özal Üniversitesi'nde Bilgisayar Mühendisliği okudu (2020–2024).")
    assert result.ok, result.errors


@pytest.mark.parametrize("quote", ["bir", "Malatya", "ing"])
def test_trivially_short_quote_is_rejected(quote: str) -> None:
    result = validate("Berkay Harvard'da okudu.", quote=quote)
    assert not result.ok


@pytest.mark.parametrize(
    "answer",
    [
        "Ona berkay.kaplan@example.com adresinden ulaşabilirsiniz.",
        "Telefonu +90 532 123 45 67.",
        "Berkay 2019'da mezun oldu.",
        "Berkay 4 yıldır yazılım geliştiriyor.",
        "Berkay is a 24-year-old developer.",
        "Berkay 24 yaşındaki bir geliştirici.",
        "He has been coding for 5 years.",
        "Berkay 2001 doğumlu.",
        "Detaylar için www.evil.example/berkay adresine bakın.",
        "Detaylar için [profil](https://evil.example/x) bağlantısına bakın.",
        "Detaylar için [profil](mailto:x@example.com) bağlantısına bakın.",
    ],
)
def test_fabricated_contact_numbers_age_and_links_are_rejected(answer: str) -> None:
    result = validate(answer)
    assert not result.ok, answer


def test_bold_or_www_channel_links_are_allowed() -> None:
    result = validate(
        "Berkay Malatya Turgut Özal Üniversitesi'nde okudu. **https://github.com/MrBekoX** ve "
        "www.linkedin.com/in/berkay-kaplan-133b35245/ üzerinden ulaşılabilir; ayrıntı: [eğitim](/about#education)."
    )
    assert result.ok, result.errors


@pytest.mark.parametrize(
    "question",
    ["How old is Vibeo?", "What is the rate limiting approach in his projects?", "Which rates does Redis use here?"],
)
def test_technical_questions_do_not_trigger_unknown_field_notes(question: str) -> None:
    verdict = evaluate_policy(question, DOCUMENT.privacy)
    assert not verdict.unknown, verdict


@pytest.mark.parametrize("question", ["How old is Berkay?", "What are his hourly rates?", "When was he born?"])
def test_personal_unknown_fields_are_still_detected(question: str) -> None:
    verdict = evaluate_policy(question, DOCUMENT.privacy)
    assert verdict.unknown, question
