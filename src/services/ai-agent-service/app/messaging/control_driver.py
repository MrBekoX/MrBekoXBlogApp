"""Kontrol komutlarının graph devamı sürücüsü (W6 F3; ``ControlResumeDriver``).

``messaging.control`` protokolünün app-içi GERÇEKLEŞTİRİMİ: ``agent.resume.
requested`` ve ``agent.action.result`` teslimini A9 checkpoint zinciri
üzerinden graph'a bağlar. Test double'ı (``tests/collab/doubles.py``'daki
``RecordingResumeDriver``) yalnız çağrı kaydeder; bu sınıf GERÇEK devamı
üretir:

1. **Hedefli claim:** ``needs_input`` sonrası park edilmiş ('accepted') iş
   ``JobStore.claim_job_for_continuation`` ile bu sürücüye geçirilir —
   lease/fencing/deneme sözleşmesi ``claim_next_job`` ile aynıdır. İş
   running ise (başka sahibin) veya terminal ise ``None`` gelir: terminal
   idempotent ACK'tır ("already_terminal"); running geçici meşguliyettir ve
   istisna ile teslim ACK'sız kalır (transport retry yeniden dener).
2. **Girdi çözümü:** ``agent.action.result`` payload'ı B1 sözleşme modelinden
   domain ``ValidatedActionResult``'a çevrilir (``validated_at`` ISO→UTC);
   ``agent.resume.requested`` girdisiz devamdır (checkpoint'teki en güncel
   state ile). Domain model, A9 çalışma makinesinin proposal/run bağlamı
   denetimlerini aynen uygular.
3. **Graph devamı:** worker'ın ``execute_claimed`` girişi — checkpoint varsa
   ``entrypoints.resume`` (girdi A9 makinesine taşınır), checkpoint yoksa
   taze yol (sonuçsuz onay ``validation_error`` ile reddedilir — başarı
   varsayılmaz). Terminal yazımı worker'ın guard'lı ``complete_job``/
   ``fail_job`` yoluyla terminal olayla AYNI transaction'da olur.
4. **Idempotency:** sürücü hatası inbox yazmadan ACK'sız bırakır (en az bir
   kez); sonuçlanmış çalışmaya ikinci teslim ya inbox ön-okumasında
   "duplicate" görür ya da A9 makinesinin "sonuçlandı" guard'ına takılır —
   çift graph etkisi üretmez (``control.ControlConsumerService`` sözleşmesi).

Kompozisyon: ``build_control_consumer(..., resume_driver=CollaborationResume
Driver(worker, store, worker_id=..., lease_seconds=...))`` — worker ile aynı
``JobStore``/``ExecutionDependencies`` örneğini paylaşır.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agent_core.models import ValidatedActionResult

from .control import ControlResumeDriver
from .contracts.payloads import AgentActionResultV1
from .job_store import JobStore
from .retry import TransportError
from .worker import ExecutionWorker

__all__ = ["CollaborationResumeDriver", "ContinuationBusy"]

logger = logging.getLogger(__name__)


class ContinuationBusy(TransportError):
    """Park edilmiş iş şu anda devam için claim edilemedi (geçici; teslim ACK'sız).

    İş başka bir worker'ın 'running' yürütmesinde: o yürütme needs_input ile
    park edince tekrar teslim sürücüyü yeniden çağırır. Kalıcı bir ihlal
    DEĞİLDİR: ``TransportError`` sınıfı sürücüyü retry kademelerine (10s/30s/2dk)
    verir; kademeler tükenirse DLQ'da görünür olur (sessiz döngü yok).
    """


class CollaborationResumeDriver(ControlResumeDriver):
    """B9 kontrol komutunu checkpoint zinciri üzerinden graph'a bağlayan sürücü."""

    def __init__(
        self,
        worker: ExecutionWorker,
        store: JobStore,
        *,
        worker_id: str,
        lease_seconds: float,
    ) -> None:
        self._worker = worker
        self._store = store
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds

    async def resume_requested(self, *, run_id: str, payload: Any) -> dict[str, Any]:
        """``agent.resume.requested``: girdisiz checkpoint devamı.

        Komut girdisi (``checkpoint_reference``/``user_ref``) gözlemlenebilirlik
        içindir; checkpoint zinciri ``job-{run_id}`` kararlı kimliğiyle bulunur
        (A8 sözleşmesi) — zarf referansı graph adresi DEĞİLDİR, uydurulmaz.
        """

        del payload  # sözleşme alanları: checkpoint_reference + user_ref (yukarıda)
        return await self._continue(run_id)

    async def action_result(self, *, run_id: str, payload: Any) -> dict[str, Any]:
        """``agent.action.result``: doğrulanmış backend kararıyla A9 onay devamı.

        Domain ``ValidatedActionResult`` çözümü TEMBEL'dir: yalnız iş devam için
        claim edildikten sonra kurulur — terminal idempotent ACK yolu bozuk/
        eksik payload'la bile çalışır (yeniden teslimde "already_terminal"
        kararı payload doğrulamasına takılmaz).
        """

        if not isinstance(payload, AgentActionResultV1):
            payload = AgentActionResultV1.model_validate(payload)

        def _build_validated() -> ValidatedActionResult:
            return ValidatedActionResult(
                proposal_id=payload.proposal_id,
                run_id=run_id,
                outcome=payload.outcome,
                reason=payload.reason,
                applied_article_revision=payload.applied_article_revision,
                validated_at=_parse_utc(payload.validated_at),
            )

        return await self._continue(run_id, build_validated_result=_build_validated)

    # ---------------------------------------------------------------- iç adımlar

    async def _continue(
        self,
        run_id: str,
        *,
        collab_input: Any | None = None,
        build_validated_result: Any | None = None,
    ) -> dict[str, Any]:
        claimed = await self._store.claim_job_for_continuation(
            run_id, self._worker_id, lease_seconds=self._lease_seconds
        )
        if claimed is None:
            if await self._job_is_terminal(run_id):
                # Sonuçlanmış devamın tekrar teslimi: etkisiz + ACK (idempotent).
                logger.info(
                    "graph devamı atlandı (iş terminal): run_id=%s", run_id
                )
                return {"outcome": "already_terminal"}
            raise ContinuationBusy(
                f"run {run_id} park edilmiş değil (running/queued); "
                "graph devamı tekrar teslimde denenir"
            )

        validated_result = (
            build_validated_result() if build_validated_result is not None else None
        )
        result = await self._worker.execute_claimed(
            claimed,
            collab_input=collab_input,
            validated_result=validated_result,
        )
        logger.info(
            "graph devamı tamamlandı: run_id=%s action=%s attempt=%s",
            run_id,
            result.action,
            result.execution_attempt,
        )
        return {
            "outcome": result.action,
            "execution_attempt": result.execution_attempt,
            "detail": result.detail,
        }

    async def _job_is_terminal(self, run_id: str) -> bool:
        row = await self._store.fetch_job_full(run_id)
        if row is None:
            return False
        return str(row["status"]) in {
            "completed",
            "partially_completed",
            "failed",
            "cancelled",
        }


def _parse_utc(value: str) -> datetime:
    """B1 ``UtcIsoString`` → UTC datetime (``Z`` ekini aware UTC'ye çözer)."""

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
