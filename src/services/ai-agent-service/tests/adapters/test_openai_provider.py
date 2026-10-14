"""OpenAI-uyumlu sağlayıcı adaptörünün OFFLINE testleri.

Tüm akışlar ``httpx.MockTransport`` ile scripted SSE üzerinden koşar — GERÇEK
AĞ ÇAĞRISI YAPILMAZ. Kanıtlananlar: parça sırası, zaman bazlı birleştirme
(~0.4 sn, inject edilebilir saat), son usage ile tam ModelResponse, istek
gövdesinin streaming sözleşmesi (``stream:true`` +
``stream_options:{"include_usage":true}``), iptal/zaman aşımı/HTTP arızası
eşlemesi, ortam fabrikası (``AGENT_LLM_API_KEY`` doluysa gerçek sağlayıcı,
boşsa ``None`` — mevcut davranış).
"""

from __future__ import annotations

import json

import httpx
import pytest

from agent_core.adapters import LlmProviderSettings, OpenAiModelProvider, build_model_provider_from_env
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import ModelProvider, ModelRequest

pytest.importorskip("httpx")


def make_settings(**overrides) -> LlmProviderSettings:
    defaults = dict(api_key="test-key", model="gpt-test", base_url="http://llm.test/v1")
    defaults.update(overrides)
    return LlmProviderSettings(**defaults)


def sse_body(events: list[dict]) -> bytes:
    raw = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return (raw + "data: [DONE]\n\n").encode("utf-8")


def make_provider(events: list[dict], *, clock=None, captured: list[httpx.Request] | None = None, settings=None):
    body = sse_body(events)

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(200, content=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAiModelProvider(settings or make_settings(), client=client, clock=clock)


async def collect(provider: OpenAiModelProvider, request: ModelRequest | None = None):
    received: list[str] = []
    async def on_delta(chunk: str) -> None:
        received.append(chunk)
    response = await provider.stream_complete(request or ModelRequest(prompt="selam"), on_delta=on_delta)
    return received, response


# ------------------------------------------------------------------ parça sırası


def test_stream_complete_reports_scripted_deltas_in_order() -> None:
    events = [
        {"choices": [{"delta": {"content": "Bir "}}]},
        {"choices": [{"delta": {"content": "İki "}}]},
        {"choices": [{"delta": {"content": "Üç"}}]},
    ]
    ticks = iter([0.0, 0.0, 0.5, 0.5, 1.0])

    def clock() -> float:
        return next(ticks, 10.0)

    provider = make_provider(events, clock=clock)

    import asyncio

    received, response = asyncio.run(collect(provider))

    # Saat 0.5s ilerledikçe ara flush: ilk iki parça birleşir, üçüncü kuyrukta.
    assert received == ["Bir İki ", "Üç"]
    assert response.text == "Bir İki Üç"  # TAM yanıt parçaların birleşimidir


def test_stream_complete_coalesces_within_flush_window() -> None:
    events = [
        {"choices": [{"delta": {"content": "parça1"}}]},
        {"choices": [{"delta": {"content": "parça2"}}]},
    ]
    provider = make_provider(events, clock=lambda: 0.0)  # saat duruyor: tek flush

    import asyncio

    received, response = asyncio.run(collect(provider))
    assert received == ["parça1parça2"]  # token-başına DEĞİL, birleştirilmiş chunk
    assert response.text == "parça1parça2"


# ------------------------------------------------------------------ usage + gövde


def test_stream_complete_extracts_final_usage_and_model() -> None:
    events = [
        {"choices": [{"delta": {"content": "yanıt"}}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}},
    ]
    provider = make_provider(events)

    import asyncio

    received, response = asyncio.run(collect(provider))
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 3
    assert response.usage.total_tokens == 15
    assert response.model_name == "gpt-test"


def test_request_body_carries_streaming_contract() -> None:
    captured: list[httpx.Request] = []
    provider = make_provider(
        [{"choices": [{"delta": {"content": "ok"}}]}],
        captured=captured,
        settings=make_settings(base_url="http://llm.test/v1/"),
    )

    import asyncio

    asyncio.run(collect(provider, ModelRequest(prompt="gövde", system="sistem", temperature=0.2)))

    request = captured[0]
    assert request.url == "http://llm.test/v1/chat/completions"  # sondaki / düzeltilir
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "gpt-test"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["messages"] == [
        {"role": "system", "content": "sistem"},
        {"role": "user", "content": "gövde"},
    ]
    assert body["temperature"] == 0.2


def test_complete_runs_stream_path_without_delta_sink() -> None:
    """``complete`` aynı streaming yolunu deltasız yürütür (tek kod yolu)."""

    events = [
        {"choices": [{"delta": {"content": "router" " yanıtı"}}]},
        {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}},
    ]
    provider = make_provider(events)

    import asyncio

    response = asyncio.run(provider.complete(ModelRequest(prompt="selam")))
    assert response.text == "router yanıtı"
    assert response.usage.total_tokens == 6


def test_provider_satisfies_model_provider_protocol() -> None:
    provider = make_provider([])
    assert isinstance(provider, ModelProvider)


# ------------------------------------------------------------------ iptal/arıza


class _CancelAfterFirstToken:
    """İlk SSE satırına kadar geçer, sonra iptal eder (CancelAfterEntryToken deseni)."""

    def __init__(self) -> None:
        self._checks = 0

    def is_cancelled(self) -> bool:
        return self._checks >= 2

    def reason(self) -> str | None:
        return "kullanıcı iptal etti"

    def raise_if_cancelled(self) -> None:
        self._checks += 1
        if self._checks >= 2:
            raise PortError(
                AgentErrorCode.CANCELLED, "çalışma iptal edildi", port="CancellationToken"
            )


def test_cancel_mid_stream_aborts_with_cancelled_code() -> None:
    events = [
        {"choices": [{"delta": {"content": "ilk"}}]},
        {"choices": [{"delta": {"content": "ikinci"}}]},
    ]
    provider = make_provider(events)

    import asyncio

    async def scenario():
        received: list[str] = []

        async def on_delta(chunk: str) -> None:
            received.append(chunk)

        response = await provider.stream_complete(
            ModelRequest(prompt="selam"), cancel=_CancelAfterFirstToken(), on_delta=on_delta
        )
        return received, response

    try:
        asyncio.run(scenario())
    except PortError as error:
        assert error.code is AgentErrorCode.CANCELLED
    else:  # pragma: no cover - iptal bekleniyordu
        raise AssertionError("iptal sinyali üretmedi")


def test_timeout_maps_to_port_error_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAiModelProvider(make_settings(), client=client)

    import asyncio

    async def scenario():
        async def on_delta(_chunk: str) -> None:
            return None

        await provider.stream_complete(ModelRequest(prompt="selam"), on_delta=on_delta)

    try:
        asyncio.run(scenario())
    except PortError as error:
        assert error.code is AgentErrorCode.TIMEOUT
        assert error.retryable is True
    else:  # pragma: no cover
        raise AssertionError("zaman aşımı eşlenmedi")


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(500, True), (429, True), (400, False)],
)
def test_http_error_maps_to_provider_error_with_retryable_flag(status: int, retryable: bool) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=b'{"error": "x"}'))
    )
    provider = OpenAiModelProvider(make_settings(), client=client)

    import asyncio

    async def scenario():
        async def on_delta(_chunk: str) -> None:
            return None

        await provider.stream_complete(ModelRequest(prompt="selam"), on_delta=on_delta)

    try:
        asyncio.run(scenario())
    except PortError as error:
        assert error.code is AgentErrorCode.PROVIDER_ERROR
        assert error.retryable is retryable
    else:  # pragma: no cover
        raise AssertionError(f"HTTP {status} PortError'a eşlenmedi")


# ------------------------------------------------------------------ ortam fabrikası


def test_llm_settings_from_env_empty_key_is_unconfigured() -> None:
    assert LlmProviderSettings.from_env({"AGENT_LLM_API_KEY": ""}) is None
    assert LlmProviderSettings.from_env({}) is None


def test_llm_settings_missing_model_with_key_raises_config_error() -> None:
    with pytest.raises(PortError) as excinfo:
        LlmProviderSettings.from_env({"AGENT_LLM_API_KEY": "sk"})
    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    assert "AGENT_LLM_MODEL" in excinfo.value.message


def test_llm_settings_from_env_defaults_and_timeouts() -> None:
    settings = LlmProviderSettings.from_env(
        {
            "AGENT_LLM_API_KEY": "sk",
            "AGENT_LLM_MODEL": "m1",
        }
    )
    assert settings is not None
    assert settings.base_url == "https://api.openai.com/v1"  # default uç nokta
    assert settings.connect_timeout_seconds == 10.0
    assert settings.request_timeout_seconds == 120.0

    custom = LlmProviderSettings.from_env(
        {
            "AGENT_LLM_API_KEY": "sk",
            "AGENT_LLM_MODEL": "m1",
            "AGENT_LLM_BASE_URL": "http://ozel/v1",
            "AGENT_LLM_CONNECT_TIMEOUT": "3.5",
            "AGENT_LLM_REQUEST_TIMEOUT": "45",
        }
    )
    assert custom is not None
    assert custom.base_url == "http://ozel/v1"
    assert custom.connect_timeout_seconds == 3.5
    assert custom.request_timeout_seconds == 45.0


def test_build_model_provider_from_env_switch() -> None:
    # Anahtar boş: None — çağıran MEVCUT davranışıyla sürer (birebir korunur).
    assert build_model_provider_from_env({}) is None

    provider = build_model_provider_from_env({"AGENT_LLM_API_KEY": "sk", "AGENT_LLM_MODEL": "m1"})
    assert isinstance(provider, OpenAiModelProvider)
