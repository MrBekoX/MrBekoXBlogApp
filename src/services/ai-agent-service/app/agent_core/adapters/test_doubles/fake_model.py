"""ModelProvider test double'ları."""

from __future__ import annotations

from datetime import datetime, timezone

from ...ports import CancellationToken, ModelRequest, ModelResponse, ModelUsage

__all__ = ["ExplodingModelProvider", "FakeModelProvider"]


class FakeModelProvider:
    """Sabit yanıt döndüren, çağrıları kaydeden test double."""

    is_test_double = True

    def __init__(
        self,
        response_text: str = "test yanıtı",
        *,
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
    ) -> None:
        self.response_text = response_text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.requests: list[ModelRequest] = []
        self.call_count = 0

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        if cancel is not None:
            cancel.raise_if_cancelled()
        self.requests.append(request)
        self.call_count += 1
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

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        self.call_count += 1
        raise AssertionError(
            "ExplodingModelProvider çağrıldı: router kararının model çağrısıyla hesaplanmaması gerekir"
        )
