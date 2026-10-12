"""State içi kullanım ve hata kayıtları.

``UsageEvent`` tek dış çağrının (model/araç/arama/kaynak sayfası/araştırma
turı) kullanım izidir; ``event_id`` tekrar yürütmede kopya kullanım kaydını
engelleyen birleştirme anahtarıdır (plan A2: "Kullanım kayıtları tekrar
yürütmede kopya sonuç oluşturmuyor"). ``NodeErrorRecord`` node hata türlerini
state içinde saklar.

İşaretler (plan A2):
- ``estimated=True``: sağlayıcı kullanım bilgisi vermedi; token tahminidir.
- ``uncertain=True``: kesinti/iptal anında dış çağrının gerçekleşip
  gerçekleşmediği bilinmiyor; belirsiz kullanım olarak kaydedilir.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, NonNegativeInt

from ..models import BusinessModel, Identifier, UsageRecord, UtcDatetime

__all__ = ["NodeErrorRecord", "UsageEvent", "UsageEventKind", "usage_record_from_events"]


class UsageEventKind(StrEnum):
    """Kullanım olayının dayandığı bütçe birimi; ``BudgetKind`` ile hizalıdır."""

    MODEL_CALL = "model_call"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    WEB_SEARCH_CALL = "web_search_call"
    SOURCE_PAGE_READ = "source_page_read"
    RESEARCH_ROUND = "research_round"


class UsageEvent(BusinessModel):
    """Tek dış çağrının kullanım izi; ``event_id`` = ``action_id#attempt``.

    ``action_id`` node ve eylemi tanımlayan kararlı kimliktir (ör.
    ``subtask:2:search``); aynı eylemin tekrar yürütülmesi aynı ``event_id``'yi
    üretir ve reducer kopyayı düşürür. Retry ise aynı ``action_id`` ile yeni
    ``attempt`` açar ve bütçeye ayrı deneme olarak yazılır (plan A2: retry'lar
    bütçeye dahil).
    """

    event_id: Identifier
    run_id: Identifier
    action_id: Identifier
    kind: UsageEventKind
    attempt: NonNegativeInt = 1
    outcome: str = Field(default="success", pattern=r"^(success|failed|uncertain)$")
    prompt_tokens: NonNegativeInt = 0
    completion_tokens: NonNegativeInt = 0
    total_tokens: NonNegativeInt = 0
    estimated: bool = False
    uncertain: bool = False
    recorded_at: UtcDatetime


class NodeErrorRecord(BusinessModel):
    """Node düzeyinde karşılaşılan hatanın state izi; terminal sonucun girdisi."""

    error_id: Identifier
    node: Identifier
    code: str = Field(max_length=64)
    message: str = Field(max_length=2000)
    attempt: NonNegativeInt = 1
    retryable: bool = False
    occurred_at: UtcDatetime


def usage_record_from_events(
    run_id: str, events: list[UsageEvent], *, duration_seconds: float = 0.0
) -> UsageRecord:
    """Tekrar eden olayları düşürerek run'ın kullanım görünümünü hesaplar.

    Çağrı sayımları yalnız tamamlanan (success) çağrılardan gelir; başarısız
    denemeler bütçede kalır ama ``model_calls``/``tool_calls`` sayımına
    girmez. Bu ayrım retry'ın bütçeyi tüketirken kullanım görünümünü şişir
    mememesi içindir.
    """
    seen: set[str] = set()
    model_calls = tool_calls = web_search_calls = 0
    prompt = completion = 0
    for event in events:
        if event.event_id in seen or event.uncertain:
            # Belirsiz olay çağrı sayımı üretemez; yalnız bütçe tarafında kalır.
            continue
        seen.add(event.event_id)
        prompt += event.prompt_tokens
        completion += event.completion_tokens
        if event.outcome != "success":
            continue
        if event.kind is UsageEventKind.MODEL_CALL:
            model_calls += 1
        elif event.kind is UsageEventKind.TOOL_CALL:
            tool_calls += 1
        elif event.kind is UsageEventKind.WEB_SEARCH_CALL:
            web_search_calls += 1
    return UsageRecord(
        run_id=run_id,
        model_calls=model_calls,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        tool_calls=tool_calls,
        web_search_calls=web_search_calls,
        duration_seconds=max(duration_seconds, 0.0),
        recorded_at=events[-1].recorded_at if events else _now(),
    )


def _now() -> UtcDatetime:  # pragma: no cover - yalnız boş olay listesi yolunda
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
