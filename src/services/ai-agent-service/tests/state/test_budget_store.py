"""PolicyBudgetStore: paralel görevlerle bütçe aşımının engellenmesi.

Kabul ölçütü: "Paralel görevlerle bütçe sınırı aşılamıyor" — rezervasyon
atomik kritik bölümde yapılır; eşzamanlı isteklerin yalnız kapasite kadarı
geçer, fazlası çağrı başlamadan ``budget_exhausted`` ile reddedilir.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core.budget import BudgetPolicy, PolicyBudgetStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import BudgetProfile
from agent_core.ports import BudgetKind


def _policy(**overrides) -> BudgetPolicy:
    defaults: dict = dict(
        max_model_calls=3, max_total_tokens=900, max_tool_attempts=5,
        max_search_calls=2, max_source_pages=4, max_research_rounds=2,
    )
    defaults.update(overrides)
    return BudgetPolicy(**defaults)


def test_parallel_reserves_cannot_oversubscribe_capacity() -> None:
    """40 eşzamanlı rezervasyon, kapasite 8 iken tam 8 geçer; kalan çağrı başlamaz."""
    store = PolicyBudgetStore(_policy(max_search_calls=8))

    async def scenario() -> tuple[int, int]:
        results = await asyncio.gather(
            *(store.reserve("run-a2", BudgetKind.WEB_SEARCH_CALL, 1) for _ in range(40)),
            return_exceptions=True,
        )
        ok = [r for r in results if not isinstance(r, BaseException)]
        rejected = [r for r in results if isinstance(r, PortError)]
        assert all(r.code is AgentErrorCode.BUDGET_EXHAUSTED for r in rejected)
        for reservation in ok:
            await store.commit(reservation, 1)
        return len(ok), len(rejected)

    accepted, rejected = asyncio.run(scenario())
    assert (accepted, rejected) == (8, 32)


def test_release_frees_capacity_for_next_attempt() -> None:
    """Hata yolunda release edilen rezervasyon kapasiteyi geri açar."""

    async def scenario() -> None:
        store = PolicyBudgetStore(_policy(max_search_calls=1))
        first = await store.reserve("run-a2", BudgetKind.WEB_SEARCH_CALL, 1)
        with pytest.raises(PortError) as excinfo:
            await store.reserve("run-a2", BudgetKind.WEB_SEARCH_CALL, 1)
        assert excinfo.value.code is AgentErrorCode.BUDGET_EXHAUSTED
        await store.release(first)  # hata/iptal yolu
        second = await store.reserve("run-a2", BudgetKind.WEB_SEARCH_CALL, 1)
        await store.commit(second, 1)
        usage = await store.usage("run-a2")
        assert usage.committed[BudgetKind.WEB_SEARCH_CALL] == 1

    asyncio.run(scenario())


def test_commit_records_actual_usage_and_double_close_is_rejected() -> None:
    """Commit fiili kullanımı yazar; aynı rezervasyon ikinci kez kapatılamaz."""

    async def scenario() -> None:
        store = PolicyBudgetStore(_policy())
        reservation = await store.reserve("run-a2", BudgetKind.TOKEN, 500)
        await store.commit(reservation, 640)  # fiili > rezervasyon: kullanım zaten gerçekleşti
        with pytest.raises(PortError):
            await store.commit(reservation, 10)
        usage = await store.usage("run-a2")
        assert usage.committed[BudgetKind.TOKEN] == 640

    asyncio.run(scenario())


def test_policy_caps_cover_every_budget_kind() -> None:
    """Politika sınırları tür başına kapasiteye akar; araştırma turu dahil (plan A2)."""
    store = PolicyBudgetStore(_policy())

    async def reserve_until_exhausted(kind: BudgetKind) -> int:
        count = 0
        while True:
            try:
                await store.reserve("run-a2", kind, 1)
            except PortError as error:
                assert error.code is AgentErrorCode.BUDGET_EXHAUSTED
                return count
            count += 1

    async def scenario() -> dict[BudgetKind, int]:
        return {kind: await reserve_until_exhausted(kind) for kind in BudgetKind}

    counts = asyncio.run(scenario())
    assert counts == {
        BudgetKind.MODEL_CALL: 3,
        BudgetKind.TOKEN: 900,
        BudgetKind.TOOL_CALL: 5,
        BudgetKind.WEB_SEARCH_CALL: 2,
        BudgetKind.SOURCE_PAGE_READ: 4,
        BudgetKind.RESEARCH_ROUND: 2,
    }


def test_policy_from_budget_profile_tightens_defaults() -> None:
    """Sunucu bütçe profili, politika varsayımlarını aşan sınırları kısar (W0 §6.5)."""
    profile = BudgetProfile(
        name="kısıtlı", max_model_calls=2, max_total_tokens=1_000,
        max_tool_calls=3, max_web_search_calls=1, max_duration_seconds=45.0,
    )
    policy = BudgetPolicy.from_budget_profile(profile)

    assert policy.max_model_calls == 2
    assert policy.max_total_tokens == 1_000
    assert policy.max_tool_attempts == 3
    assert policy.max_search_calls == 1
    assert policy.max_duration_seconds == 45.0
    # Profil taşmayan araştırma sınırları plan önerisinde kalır.
    assert policy.max_sub_questions == 4
    assert policy.max_research_rounds == 2
    assert policy.max_parallel_subtasks == 3
