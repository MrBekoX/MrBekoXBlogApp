"""Agent outbox relay (B4): kabul edilen işin accepted olayını broker'a taşır.

Desen: [ENG-OUTBOX#C1] iş verisiyle aynı transaction'da saklanan mesajı ayrı
relay broker'a yayınlar — DB commit'i ile broker yayını arasındaki çift yazma
problemi ele alınır. Kayıt yayınlanamadıysa beklemede kalır; relay tekrar
yayınlayabilir ([ENG-OUTBOX#C2]) — karşı taraftaki projection idempotentliği
B5'in sorumluluğudur.

Kurallar:
- Yayın confirm bekleyerek yapılır ([RMQ-CONFIRMS#C1]: confirm broker kabulü,
  işin bitmesi değildir); confirm geldiğinde kayıt published işaretlenir.
- Confirm kaybı/bağlantı hatasında kayıt beklemede kalır (``published_at``
  yazılmaz), hata ``last_error`` alanında görünür olur; lease bitiminde yeniden
  denenir.
- ``claim_outbox_batch`` FOR UPDATE SKIP LOCKED + ``claimed_until`` lease
  kullandığından aynı kaydı birden fazla relay kontrolsüz almaz.

NOT: Relay türden bağımsızdır — B4 accepted olayını, B5 progress/mode_selected/
needs_input/terminal olaylarını AYNI tablo ve relay üzerinden taşır; tür
politikası publisher'ın ``publish_envelope`` yön/üretici denetimindedir.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .contracts import AgentEnvelope
from .job_store import JobStore
from .publisher import BrokerPublisher

__all__ = ["OutboxRelay", "RelayBatchResult"]


def _decode_envelope(raw: Any) -> AgentEnvelope:
    """asyncpg jsonb kolonlarını str döndürür; hem dict hem str kabul edilir."""

    if isinstance(raw, (str, bytes, bytearray)):
        data = json.loads(raw)
    else:
        data = raw
    return AgentEnvelope.model_validate(data)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelayBatchResult:
    """Tek ``run_once`` çevriminin sonucu."""

    claimed: int
    published: int
    failed: int


class OutboxRelay:
    """Bekleyen outbox kayıtlarını confirm'lu yayınlar; ömür: ``run_once``/``run_forever``."""

    def __init__(
        self,
        store: JobStore,
        publisher: BrokerPublisher,
        *,
        batch_size: int = 32,
        lease_seconds: float = 30.0,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds

    async def run_once(self) -> RelayBatchResult:
        """Bir batch bekleyen kaydı yayınlar; çağıran döngüyü kurar."""

        rows = await self._store.claim_outbox_batch(
            limit=self._batch_size, lease_seconds=self._lease_seconds
        )
        published = 0
        failed = 0
        for row in rows:
            if await self._publish_row(row):
                published += 1
            else:
                failed += 1
        return RelayBatchResult(claimed=len(rows), published=published, failed=failed)

    async def _publish_row(self, row: Any) -> bool:
        try:
            envelope = _decode_envelope(row["envelope"])
            result = await self._publisher.publish_envelope(envelope)
        except Exception as exc:  # yapılandırma/çözümleme hatası: beklemede bırak
            logger.exception(
                "outbox kaydı yayınlanamadı: outbox_id=%s", row["outbox_id"]
            )
            await self._store.record_outbox_failure(row["outbox_id"], repr(exc))
            return False
        if result.confirmed:
            await self._store.mark_outbox_published(row["outbox_id"])
            logger.info(
                "outbox olayı yayınlandı: outbox_id=%s message_id=%s type=%s",
                row["outbox_id"],
                row["message_id"],
                row["message_type"],
            )
            return True
        # returned (unroutable) veya beklenmeyen onay: confirm yok → beklemede kalır.
        await self._store.record_outbox_failure(row["outbox_id"], result.detail or "confirm alınamadı")
        logger.warning(
            "outbox kaydı confirm almadı: outbox_id=%s detail=%s",
            row["outbox_id"],
            result.detail,
        )
        return False
