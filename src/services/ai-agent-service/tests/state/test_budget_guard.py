"""BudgetGuard: rezervasyon sırası, sınırlı retry, tahmin ve belirsiz kullanım.

Plan A2 kuralları: çağrı öncesi rezervasyon + sonrası kullanım kaydı;
başarısız denemeler ve retry'lar bütçeye dahil; sağlayıcı kullanım bilgisi
yoksa tahmin işaretlenir; kesintide dış çağrı belirsiz kullanım olarak
kaydedilir.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core.budget import BudgetGuard, BudgetPolicy, CallResult, PolicyBudgetStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import BudgetKind
from agent_core.ports.model import ModelUsage


def _guard(**policy_overrides) -> tuple[BudgetGuard, PolicyBudgetStore]:
    defaults: dict = dict(
        max_model_calls=4, max_total_tokens=10_000, max_tool_attempts=6,
        max_search_calls=4, max_source_pages=4, max_research_rounds=2,
        max_attempts_per_action=2,
    )
    defaults.update(policy_overrides)
    policy = BudgetPolicy(**defaults)
    store = PolicyBudgetStore(policy)
    return BudgetGuard(store, policy, "run-a2"), store


def _ok(value="sonuç", usage: ModelUsage | None = None):
    async def call(attempt: int) -> CallResult:
        return CallResult(value=value, usage=usage)

    return call


def test_reserves_before_call_and_commits_after() -> None:
    """Çağrı öncesi rezervasyon, sonrası commit + success olayı; sıra budur."""

    async def scenario() -> None:
        guard, store = _guard(max_model_calls=1)
        order: list[str] = []

        original_reserve = store.reserve

        async def spy_reserve(run_id, kind, amount):
            order.append(f"reserve:{kind.value}")
            return await original_reserve(run_id, kind, amount)

        store.reserve = spy_reserve  # type: ignore[method-assign]

        async def call(attempt: int) -> CallResult:
            order.append("call")
            return CallResult(value="metin", usage=ModelUsage(prompt_tokens=30, completion_tokens=20))

        outcome = await guard.guarded(
            action_id="answer", kind=BudgetKind.MODEL_CALL, call=call, token_estimate=100
        )

        assert order == ["reserve:model_call", "reserve:token", "call"]
        assert outcome.attempts == 1 and not outcome.estimated
        usage = await store.usage("run-a2")
        assert usage.committed[BudgetKind.TOKEN] == 50  # fiili kullanım commit edildi
        assert outcome.events[0].outcome == "success"
        assert outcome.events[0].total_tokens == 50

    asyncio.run(scenario())


def test_provider_usage_missing_is_marked_estimated() -> None:
    """Sağlayıcı kullanım bilgisi yoksa token tahmini ``estimated=True`` yazılır."""

    async def scenario() -> None:
        guard, _ = _guard()

        outcome = await guard.guarded(
            action_id="respond:answer", kind=BudgetKind.MODEL_CALL, call=_ok("metin")
        )

        assert outcome.estimated is True
        assert outcome.events[0].estimated is True
        assert outcome.events[0].total_tokens > 0  # action_id uzunluğundan tahmin

    asyncio.run(scenario())


def test_retryable_failure_retries_within_policy_and_consumes_budget() -> None:
    """Retry edilebilir arıza politikayla sınırlı tekrarlanır; başarısız deneme bütçeyi tüketir."""

    async def scenario() -> None:
        guard, store = _guard(max_search_calls=5)
        attempts: list[int] = []

        async def flaky(attempt: int) -> CallResult:
            attempts.append(attempt)
            if attempt < 2:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR, "sağlayıcı arızası",
                    port="WebSearchProvider", retryable=True,
                )
            return CallResult(value="hit")

        outcome = await guard.guarded(action_id="subtask:0:search", kind=BudgetKind.WEB_SEARCH_CALL, call=flaky)

        assert attempts == [1, 2]
        assert outcome.attempts == 2
        usage = await store.usage("run-a2")
        # Başarısız deneme + başarılı deneme: iki çağrı bütçeden düştü (retry dahil).
        assert usage.committed[BudgetKind.WEB_SEARCH_CALL] == 2
        outcomes = [event.outcome for event in outcome.events]
        assert outcomes == ["failed", "success"]
        assert outcome.events[0].event_id == "subtask:0:search#1"
        assert outcome.events[1].event_id == "subtask:0:search#2"

    asyncio.run(scenario())


def test_retry_bound_exhaustion_raises_last_error() -> None:
    """Sınırdan sonra son hata yükselir; sessiz başarı üretilmez."""

    async def scenario() -> None:
        guard, _ = _guard(max_search_calls=9, max_attempts_per_action=2)

        async def always_fails(attempt: int) -> CallResult:
            raise PortError(
                AgentErrorCode.TIMEOUT, "sağlayıcı zaman aşımı", port="WebSearchProvider", retryable=True
            )

        with pytest.raises(PortError) as excinfo:
            await guard.guarded(action_id="search", kind=BudgetKind.WEB_SEARCH_CALL, call=always_fails)
        assert excinfo.value.code is AgentErrorCode.TIMEOUT

    asyncio.run(scenario())


def test_non_retryable_failure_stops_immediately() -> None:
    """``retryable=False`` arıza tek denemede terminaldir."""

    async def scenario() -> None:
        guard, store = _guard()
        attempts: list[int] = []

        async def broken(attempt: int) -> CallResult:
            attempts.append(attempt)
            raise PortError(AgentErrorCode.CONFIG_ERROR, "anahtar yok", port="ModelProvider")

        with pytest.raises(PortError) as excinfo:
            await guard.guarded(action_id="answer", kind=BudgetKind.MODEL_CALL, call=broken)
        assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
        assert attempts == [1]
        usage = await store.usage("run-a2")
        assert usage.committed[BudgetKind.MODEL_CALL] == 1  # deneme bütçeyi tüketti

    asyncio.run(scenario())


def test_budget_exhaustion_rejects_before_call() -> None:
    """Rezervasyon reddinde çağrı hiç başlamaz; olay üretilmez."""

    async def scenario() -> None:
        guard, store = _guard(max_model_calls=1)
        # Bütçeyi dışarıdan tüket: guard'a kalan kapasite yok.
        pre = await store.reserve("run-a2", BudgetKind.MODEL_CALL, 1)
        await store.commit(pre, 1)
        calls: list[int] = []

        async def call(attempt: int) -> CallResult:
            calls.append(attempt)
            return CallResult(value="yasak")

        with pytest.raises(PortError) as excinfo:
            await guard.guarded(action_id="answer", kind=BudgetKind.MODEL_CALL, call=call, token_estimate=10)
        assert excinfo.value.code is AgentErrorCode.BUDGET_EXHAUSTED
        assert calls == []
        usage = await store.usage("run-a2")
        assert usage.committed == {BudgetKind.MODEL_CALL: 1}  # yalnız ön tüketim

    asyncio.run(scenario())


def test_cancellation_during_call_records_uncertain_usage() -> None:
    """Çağrı ortasında iptal: dış çağrının gerçekleşip gerçekleşmediği bilinmez.

    Plan A2: "Kesinti sonrası dış model çağrısının gerçekleşip gerçekleşmediği
    bilinmiyorsa bunu belirsiz kullanım olarak kaydet." Rezervasyonlar ihtiyatla
    tüketilir; istisna bastırılmadan yükselir [PY-ASYNCIO#C2].
    """

    async def scenario() -> None:
        guard, store = _guard()

        async def interrupted(attempt: int) -> CallResult:
            raise PortError(AgentErrorCode.CANCELLED, "kullanıcı iptal etti", port="ModelProvider")

        with pytest.raises(PortError) as excinfo:
            await guard.guarded(
                action_id="answer", kind=BudgetKind.MODEL_CALL, call=interrupted, token_estimate=100
            )
        assert excinfo.value.code is AgentErrorCode.CANCELLED

        usage = await store.usage("run-a2")
        assert usage.committed[BudgetKind.TOKEN] == 100  # ihtiyati tüketim
        assert usage.committed[BudgetKind.MODEL_CALL] == 1

    asyncio.run(scenario())


def test_asyncio_cancellation_records_uncertain_and_reraises() -> None:
    """Gerçek asyncio iptali de belirsiz kullanım yazar ve CancelledError yükselir."""

    async def scenario() -> None:
        guard, store = _guard()

        async def aborted(attempt: int) -> CallResult:
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await guard.guarded(
                action_id="answer", kind=BudgetKind.MODEL_CALL, call=aborted, token_estimate=100
            )
        usage = await store.usage("run-a2")
        assert usage.committed[BudgetKind.TOKEN] == 100

    asyncio.run(scenario())


def test_uncertain_event_reaches_sink_and_is_not_counted_as_call() -> None:
    """Belirsiz olay istisna yolunda sink'e düşer; kullanım görünümü çağrı saymaz.

    ``events_sink`` sözleşmesi TaskContext'in kesinti olaylarını state'e
    taşımasını sağlar (node çıktısı yazılamasa bile).
    """

    async def scenario() -> None:
        from agent_core.state import usage_record_from_events

        guard, _ = _guard()
        sink: list = []

        async def interrupted(attempt: int) -> CallResult:
            raise PortError(AgentErrorCode.CANCELLED, "iptal", port="ModelProvider")

        with pytest.raises(PortError):
            await guard.guarded(
                action_id="answer", kind=BudgetKind.MODEL_CALL, call=interrupted,
                token_estimate=40, events_sink=sink,
            )

        assert len(sink) == 1
        assert sink[0].uncertain is True
        assert sink[0].estimated is True
        assert sink[0].event_id == "answer#1"
        usage = usage_record_from_events("run-a2", sink)
        assert usage.model_calls == 0  # belirsiz çağrı sayımı üretmez
        assert usage.total_tokens == 0  # gerçekleşmeyen token rapor edilmez

    asyncio.run(scenario())
