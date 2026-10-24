"""Real OpenAI text-embedding-3-small adapter.

No local vectors are substituted when configuration, transport, or response
validation fails. Requests are sequential, bounded batches; cancellation stops
an in-flight request and releases its connection. Provider response bodies and
input text are never copied into exception messages.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

import httpx

from ..content.config import EmbeddingModelConfig
from ..errors import AgentErrorCode, PortError
from ..ports import CancellationToken
from .config import EmbeddingProviderSettings

__all__ = ["OpenAiEmbeddingProvider"]

# UTF-8 byte count is a conservative upper bound on byte-pair token count.
# This avoids a tokenizer dependency and keeps every input below 8192 tokens.
# With at most 32 inputs, the request also stays below the 300,000 token limit.
MAX_INPUT_BYTES = 8191
MAX_TOTAL_INPUT_BYTES = 1024 * 1024
MAX_INPUT_COUNT = 2048
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _provider_error(message: str, *, retryable: bool = False) -> PortError:
    return PortError(
        AgentErrorCode.PROVIDER_ERROR,
        message,
        port="OpenAiEmbeddingProvider",
        retryable=retryable,
    )


def _split_utf8(text: str) -> list[tuple[str, int]]:
    """Split without cutting a Unicode code point; byte counts weight pooling."""
    raw = text.encode("utf-8")
    parts: list[tuple[str, int]] = []
    offset = 0
    while offset < len(raw):
        end = min(offset + MAX_INPUT_BYTES, len(raw))
        # A continuation byte cannot start the next UTF-8 segment.
        while end < len(raw) and raw[end] & 0xC0 == 0x80:
            end -= 1
        parts.append((raw[offset:end].decode("utf-8"), end - offset))
        offset = end
    return parts


def _pool_weighted_vectors(parts: list[tuple[list[float], int]]) -> list[float]:
    """L2-normalize a byte-weighted mean of real provider segment vectors."""
    dimensions = len(parts[0][0])
    total_weight = sum(weight for _, weight in parts)
    mean = [0.0] * dimensions
    for vector, weight in parts:
        ratio = weight / total_weight
        for index, value in enumerate(vector):
            mean[index] += value * ratio
    norm = math.sqrt(sum(value * value for value in mean))
    if not math.isfinite(norm) or norm <= 0:
        raise _provider_error("Embedding segment pooling produced an invalid vector.")
    return [value / norm for value in mean]


def _decode_embeddings(payload: Any, *, count: int, dimensions: int, model: str) -> list[list[float]]:
    """Validate the remote response before vectors can reach persistent storage."""
    if not isinstance(payload, dict) or payload.get("model") != model:
        raise _provider_error("Embedding response model does not match the configured model.")
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != count:
        raise _provider_error("Embedding response vector count does not match the input count.")
    ordered: list[list[float] | None] = [None] * count
    for row in rows:
        if not isinstance(row, dict):
            raise _provider_error("Embedding response contains an invalid vector record.")
        index = row.get("index")
        if type(index) is not int or not 0 <= index < count or ordered[index] is not None:
            raise _provider_error("Embedding response contains missing, duplicate, or invalid indexes.")
        raw_vector = row.get("embedding")
        if not isinstance(raw_vector, list) or len(raw_vector) != dimensions:
            raise _provider_error("Embedding response vector dimensions do not match the configured index.")
        vector: list[float] = []
        for value in raw_vector:
            if type(value) not in (int, float):
                raise _provider_error("Embedding response contains a nonnumeric vector component.")
            try:
                component = float(value)
            except (OverflowError, ValueError):
                raise _provider_error("Embedding response contains a nonfinite vector component.") from None
            if not math.isfinite(component):
                raise _provider_error("Embedding response contains a nonfinite vector component.")
            vector.append(component)
        if not any(vector):
            raise _provider_error("Embedding response contains a zero vector.")
        ordered[index] = vector
    # A complete permutation of [0, count) has been established above.
    return [vector for vector in ordered if vector is not None]


class OpenAiEmbeddingProvider:
    """OpenAI HTTP embeddings provider implementing the EmbeddingProvider port."""

    def __init__(self, settings: EmbeddingProviderSettings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    @property
    def index_config(self) -> EmbeddingModelConfig:
        return self.settings.index_config

    @property
    def dimensions(self) -> int:
        return self.settings.dimensions

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def embed(self, texts: Sequence[str], *, cancel: CancellationToken | None = None) -> list[list[float]]:
        if cancel is not None:
            cancel.raise_if_cancelled()
        if isinstance(texts, (str, bytes)) or not texts or len(texts) > MAX_INPUT_COUNT:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"Embedding input must contain from 1 to {MAX_INPUT_COUNT} nonempty strings.",
                port="OpenAiEmbeddingProvider",
            )
        total_input_bytes = 0
        expanded: list[tuple[int, str, int]] = []
        for original_index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                raise PortError(
                    AgentErrorCode.VALIDATION_ERROR,
                    "Embedding input contains a blank or nonstring value.",
                    port="OpenAiEmbeddingProvider",
                )
            try:
                input_bytes = len(text.encode("utf-8"))
            except UnicodeError:
                raise PortError(
                    AgentErrorCode.VALIDATION_ERROR,
                    "Embedding input must contain valid UTF-8 text.",
                    port="OpenAiEmbeddingProvider",
                ) from None
            total_input_bytes += input_bytes
            if total_input_bytes > MAX_TOTAL_INPUT_BYTES:
                raise PortError(
                    AgentErrorCode.VALIDATION_ERROR,
                    f"Embedding input exceeds the {MAX_TOTAL_INPUT_BYTES}-byte total request budget.",
                    port="OpenAiEmbeddingProvider",
                )
            expanded.extend((original_index, part, weight) for part, weight in _split_utf8(text))

        grouped: list[list[tuple[list[float], int]]] = [[] for _ in texts]
        for offset in range(0, len(expanded), self.settings.batch_size):
            if cancel is not None:
                cancel.raise_if_cancelled()
            batch = expanded[offset : offset + self.settings.batch_size]
            pending = asyncio.create_task(self._request([text for _, text, _ in batch]))
            try:
                while not pending.done():
                    await asyncio.wait({pending}, timeout=0.1)
                    if cancel is not None:
                        cancel.raise_if_cancelled()
                vectors = await pending
                for (original_index, _, weight), vector in zip(batch, vectors, strict=True):
                    grouped[original_index].append((vector, weight))
            finally:
                if not pending.done():
                    pending.cancel()
                # Retrieve any exception even when cancellation and an HTTP
                # error arrive in the same event-loop iteration.
                with suppress(asyncio.CancelledError):
                    await asyncio.gather(pending, return_exceptions=True)
        if cancel is not None:
            cancel.raise_if_cancelled()
        return [parts[0][0] if len(parts) == 1 else _pool_weighted_vectors(parts) for parts in grouped]

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self.settings.request_timeout_seconds,
                    connect=self.settings.connect_timeout_seconds,
                ),
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
                follow_redirects=False,
            )
        return self._client

    async def _request(self, texts: list[str]) -> list[list[float]]:
        try:
            # Bound the entire operation as well as individual socket phases.
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                async with self._ensure_client().stream(
                    "POST",
                    f"{self.settings.base_url.rstrip('/')}/embeddings",
                    json={
                        "model": self.settings.model,
                        "input": texts,
                        "dimensions": self.settings.dimensions,
                        "encoding_format": "float",
                    },
                    headers={"Authorization": f"Bearer {self.settings.api_key}"},
                ) as response:
                    if not 200 <= response.status_code < 300:
                        raise _provider_error(
                            f"Embedding provider returned HTTP {response.status_code}.",
                            retryable=response.status_code in (408, 429) or response.status_code >= 500,
                        )
                    body = bytearray()
                    async for part in response.aiter_bytes(chunk_size=65536):
                        if len(body) + len(part) > MAX_RESPONSE_BYTES:
                            raise _provider_error("Embedding response exceeds the maximum allowed size.")
                        body.extend(part)
                    try:
                        payload = json.loads(body)
                    except (ValueError, UnicodeError):
                        raise _provider_error("Embedding provider returned invalid JSON.") from None
                    return _decode_embeddings(
                        payload,
                        count=len(texts),
                        dimensions=self.settings.dimensions,
                        model=self.settings.model,
                    )
        except (TimeoutError, httpx.TimeoutException):
            raise PortError(
                AgentErrorCode.TIMEOUT,
                "Embedding request exceeded the configured timeout.",
                port="OpenAiEmbeddingProvider",
                retryable=True,
            ) from None
        except httpx.HTTPError:
            raise _provider_error("Embedding request failed at the transport layer.", retryable=True) from None
