"""OpenAI-uyumlu chat completions sağlayıcı adaptörü (streaming sözleşmesi).

``stream_complete`` SSE akışını okur: ``stream:true`` +
``stream_options:{"include_usage":true}``. Her content delta ~0.4 sn'lik zaman
bazlı birleştirmeden sonra ``on_delta``'ya bildirilir — token-başına bildirim
YOKTUR (events.py sözleşmesi: parçalar birleştirilmiş chunk olarak akar; üst
sınırı aşan chunk'ı bölmek çağıranın işidir). Son kullanım chunk'ındaki gerçek
usage ile TAM ``ModelResponse`` döner.

``complete`` aynı yolu deltasız yürütür (tek kod yolu; router dahil her çağrı
aynı SSE sözleşmesinden geçer). Saat inject edilebilir (``clock``); testler
``httpx.MockTransport`` ile scripted SSE kullanır — GERÇEK AĞ ÇAĞRISI YAPILMAZ.

Hata sözleşmesi (ports.model): ``config_error`` — anahtar/model eksik (ayar
katmanında); ``provider_error`` — HTTP/akış arızası (5xx/429 ``retryable``);
``timeout`` — ağ zaman aşımı; ``cancelled`` — iptal sinyali.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from ..errors import AgentErrorCode, PortError
from ..ports import CancellationToken, ModelRequest, ModelResponse, ModelUsage
from .config import LlmProviderSettings

__all__ = ["OpenAiModelProvider"]

#: Varsayılan delta birleştirme penceresi (saniye): token-başına bildirim yerine
#: zaman bazlı kaba birleştirme (streaming sözleşmesi: ~0.4 sn).
DEFAULT_DELTA_FLUSH_INTERVAL_SECONDS = 0.4

#: Kullanım chunk'ı gelmediğinde (sağlayıcı ``include_usage`` desteklemiyorsa)
#: sıfır kullanım yazılır; BudgetGuard bunu tahmin olarak işaretler.
_ZERO_USAGE = ModelUsage(prompt_tokens=0, completion_tokens=0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OpenAiModelProvider:
    """OpenAI-uyumlu chat completions istemcisi; ``ModelProvider`` portunu karşılar."""

    def __init__(
        self,
        settings: LlmProviderSettings,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] | None = None,
        delta_flush_interval: float = DEFAULT_DELTA_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None
        self._clock = clock or time.monotonic
        self._delta_flush_interval = delta_flush_interval

    async def aclose(self) -> None:
        """Kendi kurduğu istemciyi kapatır; enjekte edilen istemciye dokunmaz."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ port

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        """Tamamlanmış yanıt; akış yolu deltasız yürütülür (tek kod yolu)."""

        async def _noop(_chunk: str) -> None:
            return None

        return await self.stream_complete(request, cancel=cancel, on_delta=_noop)

    async def stream_complete(
        self,
        request: ModelRequest,
        *,
        cancel: CancellationToken | None = None,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        """SSE akışını okur; birleştirilmiş chunk'ları ``on_delta`` ile bildirir.

        Raises:
            PortError: ``cancelled`` — iptal sinyali; ``timeout`` — ağ zaman
                aşımı; ``provider_error`` — HTTP/akış arızası (5xx/429
                ``retryable=True``).
        """
        if cancel is not None:
            cancel.raise_if_cancelled()

        body = self._build_body(request)
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(
            connect=self._settings.connect_timeout_seconds,
            read=self._settings.request_timeout_seconds,
            write=self._settings.request_timeout_seconds,
            pool=self._settings.connect_timeout_seconds,
        )

        pieces: list[str] = []
        buffer: list[str] = []
        last_flush = self._clock()
        usage = _ZERO_USAGE
        model_name = self._settings.model

        try:
            client = self._ensure_client()
            async with client.stream(
                "POST",
                f"{self._settings.base_url.rstrip('/')}/chat/completions",
                json=body,
                headers=headers,
                timeout=timeout,
            ) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                    raise PortError(
                        AgentErrorCode.PROVIDER_ERROR,
                        f"sağlayıcı HTTP {response.status_code} döndürdü: {detail}",
                        port="OpenAiModelProvider",
                        retryable=response.status_code == 429 or response.status_code >= 500,
                    )
                async for line in response.aiter_lines():
                    if cancel is not None:
                        cancel.raise_if_cancelled()
                    data = _sse_data(line)
                    if data is None:
                        continue
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError as error:
                        raise PortError(
                            AgentErrorCode.PROVIDER_ERROR,
                            f"sağlayıcı akışı ayrıştırılamadı: {error}",
                            port="OpenAiModelProvider",
                            retryable=True,
                        ) from error
                    model_name = str(chunk.get("model") or model_name)
                    chunk_usage = _extract_usage(chunk)
                    if chunk_usage is not None:
                        usage = chunk_usage
                    piece = _extract_delta_text(chunk)
                    if piece:
                        pieces.append(piece)
                        buffer.append(piece)
                        now = self._clock()
                        if (now - last_flush) >= self._delta_flush_interval:
                            await on_delta("".join(buffer))
                            buffer.clear()
                            last_flush = now
        except httpx.TimeoutException as error:
            raise PortError(
                AgentErrorCode.TIMEOUT,
                f"sağlayıcı isteği zaman aşımına uğradı: {error}",
                port="OpenAiModelProvider",
                retryable=True,
            ) from None
        except httpx.HTTPError as error:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"sağlayıcı isteği başarısız: {error}",
                port="OpenAiModelProvider",
                retryable=True,
            ) from None

        if buffer:
            await on_delta("".join(buffer))
            buffer.clear()

        text = "".join(pieces)
        return ModelResponse(
            text=text,
            model_name=model_name,
            usage=usage,
            finished_at=_utcnow(),
        )

    # -------------------------------------------------------------- iç adımlar

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    def _build_body(self, request: ModelRequest) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        body: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        return body


def _sse_data(line: str) -> str | None:
    """SSE satırının veri gövdesini döndürür; veri satırı değilse ``None``."""

    if not line.startswith("data:"):
        return None
    return line[len("data:") :].strip()


def _extract_delta_text(chunk: dict[str, Any]) -> str:
    """Chat completions chunk'ındaki content delta metnini döndürür (yoksa boş)."""

    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def _extract_usage(chunk: dict[str, Any]) -> ModelUsage | None:
    """Kullanım chunk'ını (``include_usage``) ``ModelUsage``'a çevirir; yoksa ``None``."""

    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None
    return ModelUsage(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )
