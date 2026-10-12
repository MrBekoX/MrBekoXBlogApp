"""W6 F3: ``CollaborationResumeDriver`` birim testleri (broker'sız).

Sürücü, kontrol tüketici ile graph devamı arasındaki sözcüdür. Bu dosya
sözleşmesini sabitler:

- ``agent.action.result`` payload'ı domain ``ValidatedActionResult``'a çözülür
  (validated_at ISO→UTC) ve worker girdisiyle devam edilir.
- Park edilmiş iş yoksa (running/queued) geçici meşguliyet: ContinuationBusy
  → teslim ACK'sız (transport retry yeniden dener).
- İş terminalse idempotent "already_terminal" ACK'ı (çift graph etkisi yok).
- ``agent.resume.requested`` girdisiz checkpoint devamıdır.
"""

from __future__ import annotations

from typing import Any

from messaging.control_driver import CollaborationResumeDriver, ContinuationBusy
from messaging.contracts.payloads import AgentActionResultV1

from .conftest import run


class _StubWorker:
    """``execute_claimed`` girdisini kaydeden double (sürücü sözleşmesi)."""

    is_test_double = True

    def __init__(self, action: str = "completed") -> None:
        self.calls: list[dict[str, Any]] = []
        self.action = action

    async def execute_claimed(self, claimed: Any, *, collab_input: Any = None, validated_result: Any = None) -> Any:
        self.calls.append(
            {"claimed": claimed, "collab_input": collab_input, "validated_result": validated_result}
        )
        return _CycleResult(action=self.action, detail="ok", execution_attempt=2)


class _CycleResult:
    def __init__(self, *, action: str, detail: str, execution_attempt: int) -> None:
        self.action = action
        self.detail = detail
        self.execution_attempt = execution_attempt


class _StubStore:
    """Claim + durum okuma double'ı; senaryo kurucu parametrelerle çalışır."""

    is_test_double = True

    def __init__(self, *, claim: Any, status: str | None = "accepted") -> None:
        self._claim = claim
        self._status = status

    async def claim_job_for_continuation(self, run_id: str, worker_id: str, *, lease_seconds: float) -> Any:
        return self._claim

    async def fetch_job_full(self, run_id: str) -> Any:
        return None if self._status is None else {"status": self._status}


class _Claimed:
    run_id = "2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2"


def _driver(store: Any, worker: Any) -> CollaborationResumeDriver:
    return CollaborationResumeDriver(worker, store, worker_id="drv-1", lease_seconds=30.0)


def test_action_result_payload_binds_validated_result_to_worker() -> None:
    worker = _StubWorker()
    store = _StubStore(claim=_Claimed())
    driver = _driver(store, worker)
    payload = AgentActionResultV1(
        proposal_id="7b9c0000-0000-0000-0000-00000000c0de",
        outcome="accepted",
        applied_article_revision=3,
        validated_at="2026-10-12T09:30:00Z",
    )

    result = run(driver.action_result(run_id="2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2", payload=payload))

    assert result["outcome"] == "completed"
    assert len(worker.calls) == 1
    assert worker.calls[0]["collab_input"] is None
    validated = worker.calls[0]["validated_result"]
    assert validated.proposal_id == "7b9c0000-0000-0000-0000-00000000c0de"
    assert validated.run_id == "2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2"
    assert validated.outcome == "accepted"
    assert validated.applied_article_revision == 3
    assert validated.validated_at.tzinfo is not None
    assert validated.validated_at.hour == 9


def test_resume_requested_continues_without_input() -> None:
    worker = _StubWorker(action="needs_input")
    store = _StubStore(claim=_Claimed())
    driver = _driver(store, worker)

    result = run(driver.resume_requested(
        run_id="2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2",
        payload=AgentActionResultV1.model_validate({
            "proposal_id": "x",
            "outcome": "accepted",
            "validated_at": "2026-10-12T09:30:00Z",
        }),
    ))

    # resume_requested payload'ı YOK SAYILIR (girdisiz checkpoint devamı);
    # burada yalnız double'ın protokol imzası denetlenir.
    assert result["outcome"] == "needs_input"
    assert worker.calls[0]["validated_result"] is None
    assert worker.calls[0]["collab_input"] is None


def test_busy_parked_job_raises_transient_error_without_worker_call() -> None:
    worker = _StubWorker()
    store = _StubStore(claim=None, status="running")
    driver = _driver(store, worker)

    try:
        run(driver.resume_requested(run_id="2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2", payload=None))
    except ContinuationBusy:
        pass
    else:  # pragma: no cover
        raise AssertionError("running iş için ContinuationBusy beklenirdi")
    assert worker.calls == []  # ACK'sız yol: worker hiç çağrılmaz


def test_terminal_job_acknowledges_idempotently_without_claim() -> None:
    worker = _StubWorker()
    store = _StubStore(claim=None, status="completed")
    driver = _driver(store, worker)

    result = run(driver.action_result(
        run_id="2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2",
        payload=AgentActionResultV1(
            proposal_id="7b9c0000-0000-0000-0000-00000000c0de",
            outcome="accepted",
            validated_at="2026-10-12T09:30:00Z",
        ),
    ))

    # Sonuçlanmış devamın tekrar teslimi: etkisiz + ACK (çift graph etkisi yok).
    assert result == {"outcome": "already_terminal"}
    assert worker.calls == []
