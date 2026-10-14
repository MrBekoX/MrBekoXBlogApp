"""DomainProgress iş modeli.

Ara (terminal olmayan) ilerleme olayıdır; ``event_sequence`` transport
tarafındadır, iş modelinde değildir (W0 Ç6). ``ProgressSink`` portundan
dışarı akar (agent-architecture §5).
"""

from __future__ import annotations

from pydantic import Field

from .action import ActionProposal
from .base import BusinessModel, Identifier, NonEmptyText, UtcDatetime
from .enums import ProgressKind

__all__ = ["DomainProgress", "MAX_GENERATION_DELTA_CHARS", "split_generation_delta"]

#: Tek ``generation_delta`` chunk'ının üst sınırı: taşıyıcı ``message`` alanı
#: max 2000'dir; chunk üretimi 1500'ü ASLA aşmaz (streaming sözleşmesi).
#: Transport tarafındaki kopyası (``messaging.events``) ile aynı değerdedir;
#: eşlik testiyle sabitlenir.
MAX_GENERATION_DELTA_CHARS = 1500


def split_generation_delta(text: str) -> list[str]:
    """Parçalı üretim metnini üst sınıra göre böler; boş metin parça ÜRETMEZ.

    Token-başına broker mesajı yasaktır (events.py sözleşmesi): çağıran
    birleştirilmiş chunk gönderir; bu yardımcı yalnız taşıyıcı sınırını aşan
    chunk'ı soldan sağa eşit parçalara böler.
    """

    if not text:
        return []
    if len(text) <= MAX_GENERATION_DELTA_CHARS:
        return [text]
    return [
        text[start : start + MAX_GENERATION_DELTA_CHARS]
        for start in range(0, len(text), MAX_GENERATION_DELTA_CHARS)
    ]


class DomainProgress(BusinessModel):
    """Sıralı ilerleme olayı; terminal sonuç AgentOutcome'tur, bu değildir.

    ``proposal`` (W6 F1, additive): ``kind=ACTION_PROPOSED`` olayında önerinin
    TAMAMINI taşır; transport sink (worker ``_WorkerProgressSink``) bu alanı
    sözleşmedeki ``agent.action.proposed`` payload'ına çevirir. Diğer tüm
    kind'larda ``None`` kalır (varsayılan; mevcut üreticiler değişmez).
    """

    run_id: Identifier
    kind: ProgressKind
    message: NonEmptyText = Field(max_length=2000)
    detail: dict[str, str] = {}
    occurred_at: UtcDatetime
    proposal: ActionProposal | None = None
