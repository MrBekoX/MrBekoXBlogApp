"""OpenAI-uyumlu chat completions sağlayıcı adaptörü (streaming sözleşmesi).

``stream_complete`` SSE akışını okur: ``stream:true`` +
``stream_options:{"include_usage":true}``. Her content delta ~0.4 sn'lik zaman
bazlı birleştirmeden sonra ``on_delta``'ya bildirilir — token-başına bildirim
YOKTUR (events.py sözleşmesi: parçalar birleştirilmiş chunk olarak akar; üst
sınırı aşan chunk'ı bölmek çağıranın işidir). Son kullanım chunk'ındaki gerçek
usage ile TAM ``ModelResponse`` döner.

``complete`` uses the same SSE path without emitting deltas. Production always
calls the configured remote provider; no scripted model responses are bundled.

Hata sözleşmesi (ports.model): ``config_error`` — anahtar/model eksik (ayar
katmanında); ``provider_error`` — HTTP/akış arızası (5xx/429 ``retryable``);
``timeout`` — ağ zaman aşımı; ``cancelled`` — iptal sinyali.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from ..errors import AgentErrorCode, PortError
from ..budget.guard import estimate_model_input_tokens
from ..ports import CancellationToken, ModelRequest, ModelResponse, ModelUsage
from .config import LlmProviderSettings
from ..telemetry import set_span_attributes, trace_operation

__all__ = ["OpenAiModelProvider"]

#: Varsayılan delta birleştirme penceresi (saniye): token-başına bildirim yerine
#: zaman bazlı kaba birleştirme (streaming sözleşmesi: ~0.4 sn).
DEFAULT_DELTA_FLUSH_INTERVAL_SECONDS = 0.4

#: A missing usage chunk is replaced with a marked estimate from the actual
#: system/prompt/output text after a complete stream has been established.
_ZERO_USAGE = ModelUsage(prompt_tokens=0, completion_tokens=0)
MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 256 * 1024


def _stream_error(message: str) -> PortError:
    # Provider bodies may contain private prompts or credentials. Never copy
    # untrusted error messages, JSON fragments, or request URLs into failures.
    return PortError(AgentErrorCode.PROVIDER_ERROR, message, port="OpenAiModelProvider",
                     retryable=False, usage_uncertain=True)


async def _sse_events(response: httpx.Response):
    """Read bounded UTF-8 SSE events, including multi-line data fields."""
    pending = bytearray()
    data_lines: list[bytes] = []
    total = event_bytes = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_STREAM_BYTES:
            raise _stream_error("Provider stream exceeds the response size limit")
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending = bytearray(rest)
            line = line.removesuffix(b"\r")
            event_bytes += len(line)
            if event_bytes > MAX_EVENT_BYTES:
                raise _stream_error("Provider SSE event exceeds the size limit")
            if not line:
                if data_lines:
                    try:
                        yield b"\n".join(data_lines).decode("utf-8")
                    except UnicodeError:
                        raise _stream_error("Provider stream is not valid UTF-8") from None
                    data_lines.clear()
                event_bytes = 0
            elif line.startswith(b"data:"):
                data_lines.append(bytes(line[5:]).removeprefix(b" "))
        if len(pending) + event_bytes > MAX_EVENT_BYTES:
            raise _stream_error("Provider SSE event exceeds the size limit")
    if pending or data_lines:
        raise _stream_error("Provider stream ended inside an SSE event")


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
        with trace_operation("chat", kind="client", attributes={
            "gen_ai.provider.name": "openai_compatible", "gen_ai.request.model": self._settings.model,
        }) as span:
            response = await self._stream_complete(request, cancel=cancel, on_delta=on_delta)
            set_span_attributes(span, {
                "gen_ai.usage.input_tokens": response.usage.prompt_tokens,
                "gen_ai.usage.output_tokens": response.usage.completion_tokens,
                "blogapp.usage.basis": "estimated" if response.usage_estimated else "reported",
            })
            return response

    async def _stream_complete(
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
        pending = asyncio.create_task(self._read_stream(request, cancel=cancel, on_delta=on_delta))
        try:
            # A read timeout alone is reset by keepalives. Bound the whole
            # request and observe cancellation even when no content arrives.
            async with asyncio.timeout(self._settings.request_timeout_seconds):
                while not pending.done():
                    await asyncio.wait({pending}, timeout=0.1)
                    if cancel is not None:
                        cancel.raise_if_cancelled()
                return await pending
        except TimeoutError:
            raise PortError(AgentErrorCode.TIMEOUT, "Provider request timed out",
                            port="OpenAiModelProvider", retryable=False, usage_uncertain=True) from None
        finally:
            if not pending.done():
                pending.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(pending, return_exceptions=True)

    async def _read_stream(
        self, request: ModelRequest, *, cancel: CancellationToken | None,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:

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
        done = finished = False

        try:
            client = self._ensure_client()
            async with client.stream(
                "POST",
                f"{self._settings.base_url.rstrip('/')}/chat/completions",
                json=body,
                headers=headers,
                timeout=timeout,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise PortError(
                        AgentErrorCode.PROVIDER_ERROR,
                        f"Provider returned HTTP {response.status_code}",
                        port="OpenAiModelProvider",
                        retryable=response.status_code == 429 or response.status_code >= 500,
                    )
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
                    raise _stream_error("Provider did not return an SSE response")
                async for data in _sse_events(response):
                    if cancel is not None:
                        cancel.raise_if_cancelled()
                    if data.strip() == "[DONE]":
                        done = True
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        raise _stream_error("Provider stream contains invalid JSON") from None
                    if not isinstance(chunk, dict) or "error" in chunk:
                        raise _stream_error("Provider returned an invalid or failed stream event")
                    model_name = str(chunk.get("model") or model_name)
                    chunk_usage = _extract_usage(chunk)
                    if chunk_usage is not None:
                        usage = chunk_usage
                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or len(choices) > 1:
                        raise _stream_error("Provider returned an invalid choice collection")
                    if choices:
                        choice = choices[0]
                        if not isinstance(choice, dict) or not isinstance(choice.get("delta"), dict):
                            raise _stream_error("Provider returned an invalid choice")
                        reason = choice.get("finish_reason")
                        if reason is not None:
                            if finished or reason != "stop":
                                raise _stream_error("Provider completion was truncated, filtered, or unsupported")
                            finished = True
                        elif finished:
                            raise _stream_error("Provider returned content after completion")
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
                "Provider request timed out",
                port="OpenAiModelProvider",
                retryable=not pieces,
                usage_uncertain=True,
            ) from None
        except httpx.HTTPError as error:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "Provider transport request failed",
                port="OpenAiModelProvider",
                retryable=not pieces,
                usage_uncertain=True,
            ) from None

        if not done or not finished:
            raise _stream_error("Provider stream ended before a complete stop event and DONE marker")
        text = "".join(pieces)
        if not text.strip():
            raise _stream_error("Provider returned an empty completion")
        if buffer:
            await on_delta("".join(buffer))
            buffer.clear()

        estimated = usage.total_tokens == 0
        if estimated:
            usage = ModelUsage(prompt_tokens=estimate_model_input_tokens(request),
                               completion_tokens=len(text.encode("utf-8")))
        return ModelResponse(
            text=text,
            model_name=model_name,
            usage=usage,
            usage_estimated=estimated,
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
        }
        if self._settings.include_stream_usage:
            body["stream_options"] = {"include_usage": True}
        if request.max_output_tokens is not None:
            body[self._settings.output_token_parameter] = request.max_output_tokens
        if request.temperature is not None:
            if not self._settings.supports_temperature:
                raise PortError(
                    AgentErrorCode.CONFIG_ERROR,
                    "The configured provider/model does not support temperature.",
                    port="OpenAiModelProvider",
                )
            body["temperature"] = request.temperature
        return body


def _extract_delta_text(chunk: dict[str, Any]) -> str:
    """Chat completions chunk'ındaki content delta metnini döndürür (yoksa boş)."""

    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    if delta.get("tool_calls") or delta.get("function_call") or delta.get("refusal"):
        raise _stream_error("Provider returned an unsupported tool call or refusal")
    content = delta.get("content")
    if content is not None and not isinstance(content, str):
        raise _stream_error("Provider returned a nontext content delta")
    return content if isinstance(content, str) else ""


def _extract_usage(chunk: dict[str, Any]) -> ModelUsage | None:
    """Kullanım chunk'ını (``include_usage``) ``ModelUsage``'a çevirir; yoksa ``None``."""

    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        if usage is None:
            return None
        raise _stream_error("Provider returned invalid usage")
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in ("prompt_tokens", "completion_tokens")):
        raise _stream_error("Provider returned invalid token counts")
    return ModelUsage(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )
