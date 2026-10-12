"""B7 birim testleri: hata sınıflandırması, kademe merdiveni, zarf kimlik koruması.

Broker'sız hızlı kontroller; gerçek broker akışları test_retry_tiers_broker.py
ve test_poison_dlq.py içindedir.
"""

from __future__ import annotations

import pytest

from messaging.contracts.errors import AgentContractError, ContractErrorCategory
from messaging.intake import IntakePolicyError
from messaging.job_store import JobPayloadConflict
from messaging.retry import (
    DEFAULT_RETRY_TIERS,
    GraphExecutionError,
    RetryAction,
    RetryTierPolicy,
    TransportError,
    classify_exception,
    next_retry_tier,
)
from .conftest import envelope_bytes, make_envelope


def _contract_error() -> AgentContractError:
    return AgentContractError(ContractErrorCategory.BAD_FORMAT, "body", "geçersiz")


# ------------------------------------------------------- hata sınıflandırması


def test_transport_error_is_transport_class():
    assert classify_exception(TransportError("db bağlantısı koptu")) == "transport"


def test_contract_errors_are_permanent_class():
    assert classify_exception(_contract_error()) == "contract"
    assert classify_exception(IntakePolicyError("yanlış tür")) == "contract"
    assert classify_exception(JobPayloadConflict("run", "a", "b")) == "contract"


def test_graph_execution_error_is_its_own_class():
    assert classify_exception(GraphExecutionError("graph node patladı")) == "graph"


def test_unknown_exception_is_treated_as_permanent_not_transport():
    # Bilinmeyen hata kör retry üretmemeli: DLQ'da görünür olur (plan:
    # "Sürekli nack/requeue döngüsü oluşturma").
    assert classify_exception(ValueError("beklenmeyen")) == "contract"


# ------------------------------------------------------------ kademe merdiveni


def test_default_tiers_are_10s_30s_2min():
    assert DEFAULT_RETRY_TIERS == (10, 30, 120)


def test_tier_ladder_matches_plan_proposal():
    policy = RetryTierPolicy()
    # 0. deneme (ilk teslim) → 10s; 1. → 30s; 2. → 2dk; 3. başarısızlık → DLQ.
    assert policy.next_tier(0) == 10
    assert policy.next_tier(1) == 30
    assert policy.next_tier(2) == 120
    assert policy.next_tier(3) is None
    assert policy.max_attempts == 4


def test_short_tier_ladder_for_tests():
    assert [next_retry_tier(i, tiers=(1, 2, 3)) for i in range(4)] == [1, 2, 3, None]


def test_negative_attempt_rejected():
    with pytest.raises(ValueError):
        RetryTierPolicy().next_tier(-1)


# ----------------------------------------------- zarf kimliği delivery_attempt


def test_retry_body_keeps_identity_and_bumps_attempt():
    from messaging.retry import _with_delivery_attempt
    from messaging.contracts import parse_envelope

    envelope = make_envelope(message_id="11111111-1111-1111-1111-111111111111", delivery_attempt=1)
    raw = envelope_bytes(envelope)
    parsed = parse_envelope(raw)

    retry_body = _with_delivery_attempt(parsed, 2)
    reparsed = parse_envelope(retry_body)

    assert reparsed.envelope.message_id == envelope.message_id  # AYNI mantıksal kimlik
    assert reparsed.envelope.delivery_attempt == 2  # yalnız transport sayacı ilerledi
    assert reparsed.envelope.payload == envelope.payload
    assert reparsed.envelope.correlation_id == envelope.correlation_id


# ------------------------------------------------ karar sabitleri sözleşmesi


def test_retry_actions_are_the_three_wire_decisions():
    assert (RetryAction.ACK, RetryAction.NACK, RetryAction.HOLD) == ("ack", "nack", "hold")
