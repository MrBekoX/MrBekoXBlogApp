"""Deadline reaper (B7, plan satır 434): süresi geçen işleri KAPATAN agent tarafı servis.

Neden gerekli: broker TTL'i ile düşen bir mesaj işi BELİRSİZ bırakmamalı.
Deadline backend tarafından işe yazılır (K6); intake, retry ve worker
başlangıcında kontrol edilir, ancak hiçbir bileşen dokunmazsa aktif iş
deadline'tan sonra sonsuza dek backlog'ta kalır. Reaper periyodik olarak:

1. ``deadline_at < now()`` olan aktif (queued|running) işleri kapatır:
   - cancel intent YOKSA → failed + ``agent.run.failed(error_code=timeout)``;
   - cancel intent VARSA → cancelled + ``agent.run.cancelled`` (kullanıcı
     isteği deadline'la yarışırsa kullanıcının istediği kazanır).
   Her iş kendi transaction'ında koşullu UPDATE ile kapatılır: bu arada
   worker terminal yazdıysa UPDATE satır bulamaz, olay ÜRETİLMEZ (terminal
   kazanır).
2. Cancel intent'i olan yürütme BAŞLAMAMIŞ işleri finalize eder ('accepted' |
   'queued'; execute-öncesi cancel engeli): üretim kabulü 'accepted' yazdığı
   için sorgu yalnız 'queued' sayarsa niyetli kabul işi sonsuz açık kalır
   (W5 bulgusu 1a) — pending→cancelled + terminal olay.

Durum değişikliği ile outbox olayı AYNI transaction'dadır
(``ControlStore.close_expired_job``); olayları B4 ``OutboxRelay`` taşır.

Backend tarafında aynı sorumluluğun karşılığı Application katmanındaki
``AgentRunDeadlineReaper`` (.NET) servisidir; iki tarafın reaper'ı bağımsız
çalışabilir (idempotent terminal koşullu güncellemelerle).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .contracts import AgentErrorCode
from .control_store import ControlStore

__all__ = ["DeadlineReaper", "ReapResult"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReapResult:
    """Tek ``run_once`` çeviriminin sonucu."""

    expired_failed: int  # deadline dolumuyla failed kapatılanlar
    expired_cancelled: int  # deadline + cancel intent ile cancelled kapatılanlar
    queued_cancelled: int  # cancel intent'li yürütme-başlamamış (accepted|queued) işlerin finalize'ı
    skipped: int  # bu arada terminalleşen (koşul tutmayan) işler


class DeadlineReaper:
    """Süresi geçen işleri ve cancel intent'li yürütme-başlamamış işleri kapatır."""

    def __init__(
        self,
        store: ControlStore,
        *,
        batch_limit: int = 50,
        interval_seconds: float = 30.0,
    ) -> None:
        self._store = store
        self._batch_limit = batch_limit
        self._interval = interval_seconds

    async def run_once(self) -> ReapResult:
        """Tek çevrim: deadline dolanları + niyetli yürütme-başlamamış işleri kapatır."""

        expired_failed = expired_cancelled = skipped = 0
        for job in await self._store.expired_active_jobs(limit=self._batch_limit):
            run_id = str(job["run_id"])
            cancel_pending = await self._store.has_cancel_intent(run_id)
            if cancel_pending:
                terminal_status = "cancelled"
                payload: dict[str, object] = {"event_sequence": 0}
            else:
                terminal_status = "failed"
                payload = {
                    "event_sequence": 0,
                    "error_code": AgentErrorCode.TIMEOUT.value,
                    "error_message": "İş deadline süresi içinde terminalleşmedi; reaper kapattı.",
                }
            closed = await self._store.close_expired_job(
                run_id,
                conversation_id=str(job["conversation_id"]),
                correlation_id=str(job["correlation_id"]),
                terminal_status=terminal_status,
                payload=payload,  # type: ignore[arg-type]
            )
            if not closed:
                skipped += 1  # worker bu arada terminal yazdı: terminal kazanır
            elif terminal_status == "cancelled":
                expired_cancelled += 1
            else:
                expired_failed += 1

        queued_cancelled = await self.finalize_cancelled_pending()
        result = ReapResult(
            expired_failed=expired_failed,
            expired_cancelled=expired_cancelled,
            queued_cancelled=queued_cancelled,
            skipped=skipped,
        )
        if any((expired_failed, expired_cancelled, queued_cancelled)):
            logger.info("reaper çevrimi: %s", result)
        return result

    async def finalize_cancelled_pending(self) -> int:
        """Cancel intent'i olan yürütme-başlamamış (accepted|queued) işleri kapatır.

        Engel finalizer'ı: niyetli iş claim edilemez (claim koşulu intent'i
        engeller); burada terminali üretilmeden iş açık kalırdı (W5 bulgusu 1a).
        """

        count = 0
        for job in await self._store.pending_jobs_with_cancel_intent(limit=self._batch_limit):
            closed = await self._store.close_expired_job(
                str(job["run_id"]),
                conversation_id=str(job["conversation_id"]),
                correlation_id=str(job["correlation_id"]),
                terminal_status="cancelled",
                payload={"event_sequence": 0},
            )
            if closed:
                count += 1
        return count

    async def run_forever(self, *, stop: asyncio.Event | None = None) -> None:
        """Periyodik çevrim; ``stop`` verilirse onunla çıkar."""

        while stop is None or not stop.is_set():
            try:
                await self.run_once()
            except Exception:  # çevrim hatası servisi öldürmez; sonraki çevrim dener
                logger.exception("reaper çevrimi başarısız oldu")
            if stop is not None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._interval)
                    return
                except TimeoutError:
                    continue
            await asyncio.sleep(self._interval)
