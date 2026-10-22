"""İş modeli serileştirme sözleşmesi testleri.

Kabul ölçütü: "İş modelleri serileştirilebilir ve hatalı veriyi reddeder."
Burada serileştirme yarısı kanıtlanır: JSON gidiş-dönüş kimliği korur ve
çıktı JSON-güvenlidir [PYDANTIC-MODELS#C1].
"""

from __future__ import annotations

import json

import pytest

from agent_core.models import (
    ActionProposal,
    AgentOutcome,
    ArticleChunk,
    ArticleSnapshot,
    DomainProgress,
    ExecutionContext,
    EvidenceItem,
    ResearchFinding,
    ResearchPlan,
    RouteDecision,
    SourceReference,
    UsageRecord,
    ValidatedActionResult,
)

import conftest


SERIALIZABLE_FACTORIES = [
    (ExecutionContext, "make_context"),
    (AgentOutcome, "make_outcome"),
    (RouteDecision, "make_route"),
    (ArticleSnapshot, "make_snapshot"),
    (ArticleChunk, "make_chunk"),
    (SourceReference, "make_article_reference"),
    (SourceReference, "make_web_reference"),
    (EvidenceItem, "make_evidence"),
    (ResearchPlan, "make_plan"),
    (ResearchFinding, "make_finding"),
    (DomainProgress, "make_progress"),
    (UsageRecord, "make_usage"),
    (ActionProposal, "make_action_proposal"),
    (ValidatedActionResult, "make_validated_result"),
]


@pytest.mark.parametrize(
    ("model_cls", "factory_name"),
    SERIALIZABLE_FACTORIES,
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
def test_model_json_round_trip_preserves_identity(model_cls: type, factory_name: str) -> None:
    factory = getattr(conftest, factory_name)
    instance = factory()

    payload = instance.model_dump_json()
    restored = model_cls.model_validate_json(payload)

    assert restored == instance
    assert restored.model_dump() == instance.model_dump()


def test_context_json_uses_snake_case_and_iso_timestamps() -> None:
    context = conftest.make_context(article_snapshot=conftest.make_snapshot())

    payload = json.loads(context.model_dump_json())

    expected_keys = {
        "run_id", "conversation_id", "question", "language", "mode_preference",
        "article_id", "article_revision", "article_content_hash", "article_snapshot",
        "selected_text", "conversation_history", "budget_profile",
        # v2 (Who am I): konu ve pinlenmiş profil sürümü; v1 run'da ikisi de null.
        "conversation_topic", "profile_snapshot",
    }
    assert expected_keys == set(payload)
    assert payload["conversation_topic"] is None
    assert payload["profile_snapshot"] is None
    assert payload["mode_preference"] == "auto"
    assert payload["article_snapshot"]["fetched_at"] == conftest.NOW.isoformat().replace("+00:00", "Z")


def test_model_dump_json_mode_is_json_safe() -> None:
    outcome = conftest.make_outcome()

    as_json_types = outcome.model_dump(mode="json")

    # datetime gibi JSON-dışı tipler kalmadığından yeniden serialize edilebilir.
    json.dumps(as_json_types)
    assert as_json_types["usage"]["recorded_at"].endswith("Z") or "+" in as_json_types["usage"]["recorded_at"]


def test_source_reference_source_id_is_derived_canonically() -> None:
    article_ref = conftest.make_article_reference()
    web_ref = conftest.make_web_reference()

    assert article_ref.source_id == "article:post-1:3:0"
    assert web_ref.source_id.startswith("web:")
