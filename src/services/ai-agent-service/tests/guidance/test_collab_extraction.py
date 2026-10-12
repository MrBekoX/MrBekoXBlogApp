"""İş birliği detay çıkarımı testleri (plan A9: "Amaç, kapsam, takvim,
isteğe bağlı bütçe ve iletişim yöntemini çıkar").

Çıkarım deterministiktir: yalnız soruda geçen ifadelerle; çıkarılamayan
zorunlu alan ``None`` kalır ve KISA soru sorulur — tahmin yoktur.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_core.collab import extract_collaboration_details, questions_for_missing_fields
from agent_core.collab.models import CollabField, PurposeKind
from agent_core.models import ConversationTurn


class _Ctx:
    """Minimal ExecutionContext benzeri çıkarım girdisi."""

    def __init__(self, question: str, history: list[tuple[str, str]] | None = None) -> None:
        self.question = question
        self.conversation_history = [
            ConversationTurn(role=role, content=content, created_at=datetime(2026, 10, 12, tzinfo=timezone.utc))
            for role, content in (history or [])
        ]


def test_full_details_extracted_from_single_message() -> None:
    ctx = _Ctx(
        "Sitenizle i\u015f birli\u011fi yapmak istiyorum: \"RabbitMQ kuyruk y\u00f6netimi\" "
        "hakk\u0131nda konuk yaz\u0131; 2 hafta i\u00e7inde; b\u00fct\u00e7e 5000 TL; mail: a@b.co"
    )
    details = extract_collaboration_details(ctx)

    assert details.purpose is PurposeKind.GUEST_POST
    assert details.scope == "rabbitmq kuyruk yönetimi"  # tırnak içi kapsam, aynen
    assert details.timeline is not None and "2 hafta" in details.timeline
    assert details.budget is not None and "5000" in details.budget
    assert details.contact == "a@b.co"
    assert details.missing_required() == []


def test_article_reference_binds_scope_to_real_title() -> None:
    ctx = _Ctx("Bu makaleye katk\u0131da bulunmak istiyorum")
    details = extract_collaboration_details(ctx, article_title="Kuyruk y\u00f6netimi")

    assert details.purpose is PurposeKind.OPEN_SOURCE
    # Kapsam uydurulmaz: GERÇEK makale başlığına bağlanır.
    assert details.scope == "Makale: Kuyruk yönetimi"


def test_open_source_and_translation_purposes() -> None:
    assert extract_collaboration_details(_Ctx("\u00c7eviri yaparak katk\u0131 vermek istiyorum")).purpose in (
        PurposeKind.OPEN_SOURCE,
        PurposeKind.TRANSLATION,
    )
    assert extract_collaboration_details(_Ctx("I want to translate your article")).purpose is PurposeKind.TRANSLATION
    assert extract_collaboration_details(_Ctx("Let's do a collaboration on the agent series")).purpose is PurposeKind.COLLABORATION


def test_missing_fields_stay_none_and_never_guessed() -> None:
    details = extract_collaboration_details(_Ctx("Sitenizle \u00e7al\u0131\u015fmak istiyorum"))

    assert details.purpose is None or details.purpose is PurposeKind.COLLABORATION
    missing = details.missing_required()
    assert CollabField.SCOPE in missing
    assert CollabField.TIMELINE in missing
    assert CollabField.CONTACT in missing
    # budget isteğe bağlıdır: eksikliği missing listesinde bile yer almaz.
    assert CollabField.BUDGET not in missing
    assert details.budget is None


def test_budget_absence_is_not_extracted_as_value() -> None:
    details = extract_collaboration_details(_Ctx("Konu\u015fabiliriz, b\u00fct\u00e7em yok"))
    assert details.budget is None


def test_short_questions_for_missing_fields_only() -> None:
    questions = questions_for_missing_fields(
        [CollabField.PURPOSE, CollabField.TIMELINE], language="tr"
    )
    assert len(questions) == 2
    assert all(len(q) < 120 for q in questions)  # KISA sorular
    assert any("amac\u0131" in q for q in questions)
    assert any("takvim" in q for q in questions)

    english = questions_for_missing_fields([CollabField.CONTACT], language="en")
    assert len(english) == 1
    assert "contact" in english[0].lower()


def test_unknown_answer_field_is_rejected() -> None:
    from agent_core.collab import merge_answer
    from agent_core.collab.models import CollaborationDetails

    with pytest.raises(ValueError, match="bilinmeyen"):
        merge_answer(CollaborationDetails(), "btc", "x")


def test_purpose_answer_preserves_user_text() -> None:
    from agent_core.collab import merge_answer
    from agent_core.collab.models import CollaborationDetails

    details = merge_answer(CollaborationDetails(), "purpose", "Podcast'e \u00e7\u0131kmak istiyorum")
    assert details.purpose is PurposeKind.OTHER
    assert details.purpose_note == "Podcast'e \u00e7\u0131kmak istiyorum"
    # Amaç tamamlandı; diğer zorunlu alanlar hâlâ eksiktir (sırayla sorulur).
    missing = details.missing_required()
    assert CollabField.PURPOSE not in missing
    assert set(missing) == {CollabField.SCOPE, CollabField.TIMELINE, CollabField.CONTACT}
