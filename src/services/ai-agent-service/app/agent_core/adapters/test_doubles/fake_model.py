"""ModelProvider test double'ları."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from ...ports import CancellationToken, ModelRequest, ModelResponse, ModelUsage

__all__ = ["ExplodingModelProvider", "FakeModelProvider"]


class FakeModelProvider:
    """Sabit yanıt döndüren, çağrıları kaydeden test double.

    ``stream_delta_chunks`` (additive): ``stream_complete``'in ``on_delta``'ya
    bildirdiği scripted parçalar; ctor'dan inject edilebilir. Verilmediğinde TEK
    parça (``response_text``) bildirilir — mevcut tek-çağrı davranışı birebir
    korunur ve ``complete`` çıktısıyla birleşim eşleşir.
    """

    is_test_double = True

    def __init__(
        self,
        response_text: str = "test yanıtı",
        *,
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
        stream_delta_chunks: list[str] | None = None,
    ) -> None:
        self.response_text = response_text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.stream_delta_chunks = (
            list(stream_delta_chunks) if stream_delta_chunks is not None else None
        )
        self.requests: list[ModelRequest] = []
        self.call_count = 0
        self.stream_call_count = 0
        self.deltas: list[str] = []

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        if cancel is not None:
            cancel.raise_if_cancelled()
        self.requests.append(request)
        self.call_count += 1
        return self._response()

    async def stream_complete(
        self,
        request: ModelRequest,
        *,
        cancel: CancellationToken | None = None,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        if cancel is not None:
            cancel.raise_if_cancelled()
        self.stream_call_count += 1
        chunks = (
            self.stream_delta_chunks
            if self.stream_delta_chunks is not None
            else [self.response_text]
        )
        for chunk in chunks:
            self.deltas.append(chunk)
            await on_delta(chunk)
        # Tam yanıt complete ile AYNI kaynaktan: complete'i override eden alt
        # sınıfların (arıza senaryoları) akış yolunda da etkili olması için.
        return await self.complete(request, cancel=cancel)

    def _response(self) -> ModelResponse:
        return ModelResponse(
            text=self.response_text,
            model_name="fake-model",
            usage=ModelUsage(prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens),
            finished_at=datetime.now(timezone.utc),
        )


class ExplodingModelProvider:
    """Hiç çağrılmaması gereken yerlerde kullanılan test double; her çağrı testi kırar."""

    is_test_double = True

    def __init__(self) -> None:
        self.call_count = 0
        self.stream_call_count = 0

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        self.call_count += 1
        raise AssertionError(
            "ExplodingModelProvider çağrıldı: router kararının model çağrısıyla hesaplanmaması gerekir"
        )

    async def stream_complete(
        self,
        request: ModelRequest,
        *,
        cancel: CancellationToken | None = None,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        self.stream_call_count += 1
        raise AssertionError(
            "ExplodingModelProvider.stream_complete çağrıldı: router kararının model "
            "çağrısıyla hesaplanmaması gerekir"
        )
