"""Checkpoint zarfı, şema sürümü ve resume kapsam modelleri (plan A8).

A8 yapıları iki katmana ayırır [LG-PERSISTENCE#C1]:

- **Depo (``CheckpointStore`` portu):** opak bayt yazar/okur; içeriği
  çözümlemez. Kalıcı gerçekleştirim ``checkpoint.store.FileCheckpointStore``.
- **Zarf (bu modül):** payload'ın KİME ve HANGİ SÖZLEŞMEYE ait olduğunu
  taşıyan sürümlü sarmalayıcı. Run bağı, kararlı yürütme kimliği
  (``execution_id`` — dış çalışma adaptörü atar ve doğrular), state şema
  sürümü ve içerik revizyon bağlamı zarftadır; böylece uyumsuz/başka
  çalışmaya ait checkpoint anlaşılır sonuçla reddedilir (plan A8:
  "State ve checkpoint şema sürümlerini tanımla", "uyumsuz eski checkpoint
  için anlaşılır sonuç").

``execution_id`` sözleşmesi: bir çalıştırma zincirinin (ilk yürütme +
tüm devam ettirmeler) checkpoint'leri AYNI kararlı kimliğe bağlanır. Kimliği
dış adaptör üretir ve doğrular; çekirdek biçimi denetler ve resume'da
bağlamayı zorunlu kılar. İstemci kaynaklı bu alan yetki kaynağı değildir
(A0 §7.4 ``run_id`` ilkesiyle aynı gerekçe).
"""

from __future__ import annotations

import base64
import binascii
import secrets
from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints, field_validator

from ..models import BusinessModel, ExecutionContext, HashHex, Identifier, UtcDatetime
from ..state.state import STATE_SCHEMA_VERSION, SubtaskInput

__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "EXECUTION_ID_PATTERN",
    "CheckpointEnvelope",
    "CheckpointKind",
    "ExecutionId",
    "ResumeEvaluation",
    "ResumePartition",
    "ResumeScope",
    "new_execution_id",
    "validate_execution_id",
]

#: Checkpoint ZARF şema sürümü. Zarf alan kümesi değişip geri okunamaz hale
#: geldiğinde artar; uyumsuz sürüm ``validation_error`` ile anlaşılır biçimde
#: reddedilir (plan A8). ``STATE_SCHEMA_VERSION`` (state/state.py) ise ortak
#: graph state payload'ının sürümüdür — iki sürüm ayrı sorumluluktur.
CHECKPOINT_SCHEMA_VERSION = 1

#: Kararlı yürütme kimliği biçimi; dış adaptör bu biçimi doğrulayarak atar.
EXECUTION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$"

ExecutionId = Annotated[str, StringConstraints(pattern=EXECUTION_ID_PATTERN)]


def validate_execution_id(value: str) -> str:
    """Yürütme kimliğini zarf biçimine göre doğrular; dış adaptörün denetim noktası.

    Raises:
        PortError: ``validation_error`` — boş/karalara uymayan kimlik.
    """
    from ..errors import AgentErrorCode, PortError

    stripped = value.strip()
    if not stripped or len(stripped) > 128:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "yürütme kimliği 1-128 karakter olmalıdır",
            port="CheckpointEnvelope",
        )
    import re

    if re.match(EXECUTION_ID_PATTERN, stripped) is None:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            f"yürütme kimliği biçimi geçersiz: {value!r} (kalıp: {EXECUTION_ID_PATTERN})",
            port="CheckpointEnvelope",
        )
    return stripped


def new_execution_id(run_id: str) -> str:
    """Yeni kararlı yürütme kimliği üretir; bir kez atanır, zincir boyunca değişmez."""
    prefix = "".join(ch if ch.isalnum() or ch in "._:@-" else "-" for ch in run_id)[:32]
    return f"exec-{prefix}-{secrets.token_hex(8)}"


class CheckpointKind(StrEnum):
    """Zarflı payload türü; içeriği depo değil çekirdek çözümler."""

    #: ``PreparedRun`` payload'ı (A1 hazırlık girişinin checkpoint'i).
    PREPARED = "prepared"
    #: ``AgentState`` payload'ı (A2 ortak graph state'inin checkpoint'i).
    STATE = "state"


class CheckpointEnvelope(BusinessModel):
    """Checkpoint payload'ını sarmalayan sürümlü zarf.

    Depo bu zarfı da opak bayt olarak saklar; zarf çözümlemesi resume
    tarafının (``checkpoint.resume``) işidir. ``schema_version`` zarf
    sözleşmesinin, ``state_schema_version`` içteki ``AgentState`` payload'ının
    sürümüdür (yalnız ``kind=state`` için anlamlıdır).

    Revizyon bağlamı alanları (``article_*``) yazım anındaki içerik
    referansının kopyasıdır; resume'da güncel bağlamla karşılaştırılarak
    checkpoint'in hangi kapsamda sürdürülebileceği değerlendirilir (plan A8).
    """

    schema_version: int = CHECKPOINT_SCHEMA_VERSION
    checkpoint_id: Identifier
    run_id: Identifier
    execution_id: ExecutionId
    kind: CheckpointKind
    state_schema_version: int | None = None
    article_id: Identifier | None = None
    article_revision: int | None = None
    article_content_hash: HashHex | None = None
    payload_b64: str
    saved_at: UtcDatetime

    @field_validator("schema_version")
    @classmethod
    def _positive_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("schema_version pozitif olmalıdır")
        return value

    @classmethod
    def wrap(
        cls,
        *,
        checkpoint_id: str,
        run_id: str,
        execution_id: str,
        kind: CheckpointKind,
        payload: bytes,
        saved_at: UtcDatetime,
        state_schema_version: int | None = None,
        context: ExecutionContext | None = None,
    ) -> "CheckpointEnvelope":
        """Payload'ı zarflar; revizyon bağlamını verilen ExecutionContext'ten kopyalar."""
        return cls(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            checkpoint_id=checkpoint_id,
            run_id=run_id,
            execution_id=execution_id,
            kind=kind,
            state_schema_version=state_schema_version,
            article_id=context.article_id if context is not None else None,
            article_revision=context.article_revision if context is not None else None,
            article_content_hash=context.article_content_hash if context is not None else None,
            payload_b64=base64.b64encode(payload).decode("ascii"),
            saved_at=saved_at,
        )

    def payload_bytes(self) -> bytes:
        """Zarflı payload'ın baytlarını döndürür.

        Raises:
            PortError: ``validation_error`` — base64 gövde bozuk.
        """
        from ..errors import AgentErrorCode, PortError

        try:
            return base64.b64decode(self.payload_b64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"checkpoint payload gövdesi çözümlenemedi: {error}",
                port="CheckpointEnvelope",
            ) from error


class ResumeScope(StrEnum):
    """Checkpoint'ten devamın kapsamı (plan A8: revizyon değişirse kapsam değerlendirmesi).

    - ``FULL_REUSE``: aynı revizyon; tamamlanmış kaynak/araç sonuçları
      yeniden kullanılır.
    - ``EVIDENCE_STALE``: içerik revizyonu ilerledi; karar/plan ve makaleden
      bağımsız sonuçlar sürdürülebilir AMA checkpoint'teki makale kanıtı ve
      bulguları bayattır — yeniden toplanmak zorundadır.
    - ``NOT_RESUMABLE``: içerik kaldırma, revizyon gerilemesi veya başka
      makale; checkpoint'ten devam anlaşılır hatayla reddedilir.
    """

    FULL_REUSE = "full_reuse"
    EVIDENCE_STALE = "evidence_stale"
    NOT_RESUMABLE = "not_resumable"


class ResumeEvaluation(BusinessModel):
    """Revizyon kapsam değerlendirmesinin sonucu; gerekçeler insan-okurdur."""

    scope: ResumeScope
    reasons: list[str] = []
    checkpoint_article_revision: int | None = None
    current_article_revision: int | None = None

    @property
    def resumable(self) -> bool:
        """Devam edilebilir mi? ``NOT_RESUMABLE`` için ``False``."""
        return self.scope is not ResumeScope.NOT_RESUMABLE


class ResumePartition(BusinessModel):
    """Resume'da adımların önceki sonuçlardan AYRIMI (plan A8).

    - ``reusable_*``: tamamlanmış kaynak/araç sonuçları; yeniden KULLANILIR,
      yeni model/araç çağrısı gerektirmez.
    - ``stale_*``: revizyon bayatlığı nedeniyle yeniden toplanması gerekenler.
    - ``pending_subtasks``: araç çağrısı gerektiren (henüz tamamlanmamış)
      alt görevler.
    - ``model_steps``: YENİ model çağrısı gerektiren adımlar (rapor/yanıt
      üretimi); önceki sonuçlardan üretilir, checkpoint'ten gelmez.

    ``event_id``/``action_id`` idempotentliği (state/events.py) sayesinde
    yeniden yürütülen adımların kullanım kayıtları çift sayılmaz.
    """

    reusable_evidence_ids: list[Identifier] = []
    stale_evidence_ids: list[Identifier] = []
    reusable_finding_ids: list[str] = []
    stale_finding_ids: list[str] = []
    pending_subtasks: list[SubtaskInput] = []
    model_steps: list[str] = []
    state_schema_version: int = STATE_SCHEMA_VERSION
