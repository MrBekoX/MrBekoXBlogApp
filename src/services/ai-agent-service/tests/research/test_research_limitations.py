"""A7 sınırlılık senaryoları: çelişki, yetersiz kaynak, bütçe bitişi ve iptal.

Plan A7 kabul ölçütleri: "normal araştırma, çelişki, yetersiz kaynak, bütçe
bitişi ve iptal senaryoları gerçekçi fixture'larla çalışır. Raporda uydurma
kaynak ID'si bulunmaz." Fixture'lar gerçek HTTP üzerinden A6 araçlarıyla
koşar (tests/web MockWebServer; start/stop tek event loop'ta); double
sonuçları gerçek sağlayıcı başarısı değildir.
"""

from __future__ import annotations

from typing import Any

from agent_core.errors import AgentErrorCode
from agent_core.models import RunStatus
from agent_core.research.models import SupportKind
from agent_core.research.runner import run_deep_research

from .conftest import (
    CONFLICT_TEXT,
    ERRORS_TEXT,
    GUIDE_TEXT,
    CancelAfterToken,
    FixedModelProvider,
    RoutingSearchProvider,
    build_server,
    build_web_bundle,
    make_research_context,
    make_research_policy,
    make_research_route,
    run,
)


def test_contradiction_is_detected_and_reported() -> None:
    """Bir iddia hem destek hem KARŞI çıkan kanıt taşıyorsa çelişki raporlanır (adım 5-6)."""

    async def scenario() -> dict[str, Any]:
        async with build_server(
            {"/guide": GUIDE_TEXT, "/conflict": CONFLICT_TEXT, "/errors": ERRORS_TEXT}
        ) as server:
            provider = RoutingSearchProvider(
                [
                    ("üst değer 1000", [server.url("/guide"), server.url("/conflict")]),
                    ("", [server.url("/errors")]),
                ]
            )
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=FixedModelProvider("Kanıtlar karışık; bir kaynak üst sınırı 100 olarak veriyor."),
                web_tools=web_tools,
                policy=policy,
                store=store,
            )
            return {"outcome": result.outcome, "state": result.state}

    data = run(scenario())
    state = data["state"]
    coverage = state["coverage"]
    assert coverage.contradicted_claim_ids, "sayısal çelişki saptanmalı"
    comparison = {note.claim_id: note for note in state["comparison"]}
    assert any(note.relation == "contradicts" for note in comparison.values())
    report_text = data["outcome"].report or ""
    assert "çeliş" in report_text  # karşılaştırma bölümünde bildirilir
    evidence = list(state["evidence"])
    assert any(record.support is SupportKind.CONTRADICTS for record in evidence)
    # Çelişki ayrı bir bulgu olarak raporlanır; çalışma yine tamamlandı durumundadır.
    assert data["outcome"].status is RunStatus.COMPLETED


def test_insufficient_sources_yields_partial_report_without_sources() -> None:
    """Arama sonucu okunamıyorsa (404) kısmi rapor üretilir, kaynak bölümü boştur."""

    async def scenario() -> dict[str, Any]:
        async with build_server(
            {"/missing": "Bu sayfa yok"}, status_overrides={"/missing": 404}
        ) as server:
            provider = RoutingSearchProvider([("", [server.url("/missing")])])
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=FixedModelProvider(),
                web_tools=web_tools,
                policy=policy,
                store=store,
            )
            return {"outcome": result.outcome, "state": result.state}

    data = run(scenario())
    state = data["state"]
    assert data["outcome"].status is RunStatus.PARTIAL
    report = state.get("report")
    assert report is not None and report.completeness == "partial"
    assert "kısmi" in (data["outcome"].report or "")
    assert data["outcome"].citations == []  # uydurma kaynak yok
    assert state["sources"] == []
    assert state["evidence"] == []
    # İkinci tur denendi (bütçe vardı) ve yine sonuçsuz kaldı.
    rounds = [
        event
        for event in state["usage_events"]
        if event.kind.value == "research_round" and event.outcome == "success"
    ]
    assert len(rounds) == 2
    # Kaynak bölümü boşlukla değil, doğru durum bildirimiyle dolu.
    assert "Okunabilen kaynak yok" in (data["outcome"].report or "")
    # Okuma arızaları hata izine düştü (erişilemeyen adres raporlanır).
    assert any("kaynak" in record.message for record in state["errors"])


def test_budget_exhaustion_stops_research_and_reports_partial() -> None:
    """Bütçe bitişi: arama rezervasyonu reddedilen worker kısmi yola bağlanır."""

    async def scenario() -> dict[str, Any]:
        async with build_server({"/guide": GUIDE_TEXT, "/errors": ERRORS_TEXT}) as server:
            provider = RoutingSearchProvider([("", [server.url("/guide"), server.url("/errors")])])
            # Tek arama + tek sayfa bütçesi: bir worker arar, ilk sayfa okunur,
            # ikinci sayfa budget_exhausted alır; ikinci tur araması da bütçesiz
            # kalır. Graph exception ile değil kısmi raporla biter.
            policy = make_research_policy(max_search_calls=1, max_source_pages=1)
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=FixedModelProvider(),
                web_tools=web_tools,
                policy=policy,
                store=store,
            )
            return {"outcome": result.outcome, "state": result.state}

    data = run(scenario())
    state = data["state"]
    assert data["outcome"].status is RunStatus.PARTIAL
    budget_errors = [
        record
        for record in state["errors"]
        if record.code == AgentErrorCode.BUDGET_EXHAUSTED.value
    ]
    assert budget_errors, "bütçe reddi hata izine yazılmalı"
    assert state.get("report") is not None
    assert "kısmi" in (data["outcome"].report or "")
    # Karşılanmayan iddialar belirsizlik bölümüne düştü (bulguya bağlanmadı).
    coverage = state["coverage"]
    assert coverage.uncovered_claim_ids or coverage.budget_note


def test_cancellation_before_run_produces_cancelled_outcome() -> None:
    """İptal sinyali: graph başlamadan iptal edilirse sonuç cancelled olur (adım 10)."""
    from agent_core.adapters.test_doubles.fake_signals import PreCancelledToken

    async def scenario() -> Any:
        async with build_server({"/guide": GUIDE_TEXT}) as server:
            provider = RoutingSearchProvider([("", [server.url("/guide")])])
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            model = FixedModelProvider()
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=model,
                web_tools=web_tools,
                policy=policy,
                store=store,
                cancel=PreCancelledToken("kullanıcı iptali"),
            )
            return result.outcome, model

    outcome, model = run(scenario())
    assert outcome.status is RunStatus.CANCELLED
    assert outcome.error_code is None  # cancelled iş hatası değildir
    assert model.call_count == 0


def test_cancellation_mid_research_produces_cancelled_outcome() -> None:
    """Araştırma sırasında gelen iptal: iş kısmi değil cancelled terminaliyle biter."""

    async def scenario() -> Any:
        async with build_server({"/guide": GUIDE_TEXT, "/errors": ERRORS_TEXT}) as server:
            provider = RoutingSearchProvider([("", [server.url("/guide"), server.url("/errors")])])
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            return await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=FixedModelProvider(),
                web_tools=web_tools,
                policy=policy,
                store=store,
                cancel=CancelAfterToken(after=4),
            )

    result = run(scenario())
    assert result.outcome.status is RunStatus.CANCELLED
    assert result.outcome.report is None  # iptalde rapor üretilmez
    assert result.outcome.error_message is not None


def test_source_page_budget_cap_limits_reads() -> None:
    """Kaynak sayfası bütçesi: sayfa sınırı dolunca kalan adaylar denenmez."""

    async def scenario() -> dict[str, Any]:
        async with build_server({f"/p{i}": GUIDE_TEXT for i in range(3)}) as server:
            provider = RoutingSearchProvider([("", [server.url(f"/p{i}") for i in range(3)])])
            policy = make_research_policy(max_source_pages=2)
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=FixedModelProvider("Özet."),
                web_tools=web_tools,
                policy=policy,
                store=store,
            )
            return {"outcome": result.outcome, "state": result.state}

    data = run(scenario())
    assert data["outcome"].status in (RunStatus.COMPLETED, RunStatus.PARTIAL)
    read_events = [
        event
        for event in data["state"]["usage_events"]
        if event.kind.value == "source_page_read" and event.outcome == "success"
    ]
    assert 0 < len(read_events) <= 2, "sayfa bütçesi aşılamaz"
