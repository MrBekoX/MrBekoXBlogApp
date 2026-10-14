"""ModelProvider portu ve veri tipleri.

Veri: cevap/özet/plan üretimi (istek + kullanım metrikleri) — A0 §5.
Somut sağlayıcı adaptörü ayrı karara bağlıdır (A0 §10.3); A1 yalnız sözleşme
ve test double üretir.

Hata türleri: ``config_error`` (sağlayıcı yapılandırılmamış/eksik anahtar),
``provider_error`` (dış sağlayıcı arızası, tekrarlanabilirlik bilgisiyle),
``timeout``, ``cancelled`` (verilen token iptal edilirse).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from pydantic import Field, NonNegativeInt, PositiveInt

from ..models import BusinessModel, NonEmptyText, UtcDatetime
from .cancellation import CancellationToken

__all__ = ["ModelProvider", "ModelRequest", "ModelResponse", "ModelUsage"]


class ModelUsage(BusinessModel):
    """Tek model çağrısının token metrikleri; UsageRecord'a biriktirilir."""

    prompt_tokens: NonNegativeInt = 0
    completion_tokens: NonNegativeInt = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ModelRequest(BusinessModel):
    """Tek tamamlama isteği; A1 minimal sözleşme, streaming A2+ ile gelir."""

    prompt: NonEmptyText = Field(max_length=100000)
    system: str | None = Field(default=None, max_length=20000)
    max_output_tokens: PositiveInt | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    metadata: dict[str, str] = {}


class ModelResponse(BusinessModel):
    """Model çıktısı ve kullanım metrikleri."""

    text: str
    model_name: str | None = None
    usage: ModelUsage
    finished_at: UtcDatetime


@runtime_checkable
class ModelProvider(Protocol):
    """Cevap/özet/plan üreten model port."""

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        """İsteği tamamlayarak yanıt döndürür.

        Raises:
            PortError: ``config_error`` — sağlayıcı yapılandırması eksik;
                ``provider_error`` — dış arıza (``retryable=True`` tekrar
                denenebilir); ``timeout``; ``cancelled`` — iptal sinyali.
        """
        ...

    async def stream_complete(
        self,
        request: ModelRequest,
        *,
        cancel: CancellationToken | None = None,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        """İsteği akışla tamamlar; parçaları ``on_delta`` ile bildirir.

        ``on_delta`` çağrıları SADECE birleştirilmiş chunk taşır (token-başına
        bildirim yok); chunk sınırlaması çağıran (node publish yardımcısı)
        tarafındadır. Dönüş TAM ``ModelResponse``'dur: gerçek usage metrikleriyle
        — ``complete`` ile aynı sözleşme. Bütçe/guard muhasebesi değişmez: node
        ``guarded`` içinde bu metodu çağırıp ``CallResult(value=response)``
        döndürür.

        Raises:
            PortError: ``complete`` ile aynı kodlar; akış ortasında kesilirse
                ``provider_error``/``timeout``/``cancelled``.
        """
        ...
