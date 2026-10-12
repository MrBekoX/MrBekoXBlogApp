"""İş modeli doğrulama testleri: hatalı veri reddedilir.

Kabul ölçütü: "İş modelleri serileştirilebilir ve hatalı veriyi reddeder."
Alan zorunluluğu ve ek-alan politikası açık biçimde uygulanır
[PYDANTIC-MODELS#C2]; pydantic yapılandırılmış ValidationError üretir
[PYDANTIC-MODELS#C1].
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_core.errors import AgentErrorCode
from agent_core.models import AgentOutcome, BudgetProfile, ExecutionContext, RunStatus

import conftest


def test_extra_field_is_rejected() -> None:
    payload = conftest.make_context().model_dump(mode="json")
    payload["delivery_state"] = "queued"  # teslim durumu iş modeline sızamaz

    with pytest.raises(ValidationError, match="delivery_state"):
        ExecutionContext.model_validate(payload)


def test_unknown_run_status_value_is_rejected() -> None:
    payload = conftest.make_outcome().model_dump(mode="json")
    payload["status"] = "queued_for_delivery"

    with pytest.raises(ValidationError):
        AgentOutcome.model_validate(payload)


def test_empty_question_is_rejected() -> None:
    with pytest.raises(ValidationError):
        conftest.make_context(question="   ")


def test_invalid_language_code_is_rejected() -> None:
    with pytest.raises(ValidationError):
        conftest.make_context(language="türkçe")


def test_invalid_content_hash_format_is_rejected() -> None:
    with pytest.raises(ValidationError):
        conftest.make_context(article_content_hash="DEADBEEF")


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        conftest.make_usage(recorded_at=datetime(2026, 10, 11, 12, 0, 0))


def test_aware_datetime_is_normalized_to_utc() -> None:
    utc_plus_three = timezone(timedelta(hours=3))
    usage = conftest.make_usage(recorded_at=datetime(2026, 10, 11, 15, 0, 0, tzinfo=utc_plus_three))

    assert usage.recorded_at.tzinfo == timezone.utc
    assert usage.recorded_at.hour == 12


def test_snapshot_with_mismatched_identity_is_rejected() -> None:
    snapshot = conftest.make_snapshot(article_id="post-2")

    with pytest.raises(ValidationError, match="article_id"):
        conftest.make_context(article_snapshot=snapshot, article_id="post-1")


def test_snapshot_without_content_reference_is_rejected() -> None:
    snapshot = conftest.make_snapshot()

    with pytest.raises(ValidationError, match="article_content_hash"):
        conftest.make_context(article_snapshot=snapshot, article_id=snapshot.article_id,
                              article_revision=snapshot.article_revision, article_content_hash=None)


def test_completed_outcome_requires_answer_or_report() -> None:
    with pytest.raises(ValidationError, match="answer veya report"):
        conftest.make_outcome(answer=None)


def test_outcome_cannot_carry_both_answer_and_report() -> None:
    with pytest.raises(ValidationError, match="aynı anda"):
        conftest.make_outcome(report="rapor")


def test_failed_outcome_requires_error_code() -> None:
    with pytest.raises(ValidationError, match="error_code"):
        conftest.make_outcome(status=RunStatus.FAILED, answer=None)


def test_failed_outcome_carries_common_error_code() -> None:
    outcome = conftest.make_outcome(
        status=RunStatus.FAILED, answer=None,
        error_code=AgentErrorCode.PROVIDER_ERROR, error_message="sağlayıcı arızası",
    )

    assert outcome.error_code is AgentErrorCode.PROVIDER_ERROR


def test_needs_input_requires_unresolved_questions() -> None:
    with pytest.raises(ValidationError, match="unresolved_questions"):
        conftest.make_outcome(status=RunStatus.NEEDS_INPUT, answer=None)


def test_action_proposal_run_mismatch_is_rejected() -> None:
    proposal = conftest.make_action_proposal(run_id="run-2")

    with pytest.raises(ValidationError, match="run_id"):
        conftest.make_outcome(action_proposal=proposal)


def test_chunk_with_reversed_offsets_is_rejected() -> None:
    with pytest.raises(ValidationError, match="char_end"):
        conftest.make_chunk(char_start=50, char_end=10)


def test_article_reference_requires_full_triple() -> None:
    with pytest.raises(ValidationError, match="chunk_index"):
        conftest.make_article_reference(chunk_index=None)


def test_web_reference_requires_url_and_access_time() -> None:
    with pytest.raises(ValidationError, match="url"):
        conftest.make_web_reference(url=None)


def test_web_reference_cannot_carry_article_fields() -> None:
    with pytest.raises(ValidationError, match="makale alanları"):
        conftest.make_web_reference(article_id="post-1")


def test_accepted_action_result_requires_applied_revision() -> None:
    with pytest.raises(ValidationError, match="applied_article_revision"):
        conftest.make_validated_result(applied_article_revision=None)


def test_rejected_action_result_allows_missing_revision() -> None:
    result = conftest.make_validated_result(outcome="rejected", applied_article_revision=None, reason="çakışma")

    assert result.applied_article_revision is None


def test_route_decision_web_flag_only_for_deep_research() -> None:
    with pytest.raises(ValidationError, match="deep_research"):
        conftest.make_route(selected_mode="fast", requires_web_search=True)


def test_budget_profile_rejects_zero_limits() -> None:
    with pytest.raises(ValidationError):
        BudgetProfile(name="default", max_model_calls=0, max_total_tokens=100, max_duration_seconds=60.0)


def test_conversation_history_role_is_constrained() -> None:
    with pytest.raises(ValidationError):
        conftest.make_context(
            conversation_history=[
                {"role": "system", "content": "yasak rol", "created_at": conftest.NOW}
            ]
        )


def test_action_proposal_requires_valid_base_hash() -> None:
    with pytest.raises(ValidationError):
        conftest.make_action_proposal(base_content_hash="short")
