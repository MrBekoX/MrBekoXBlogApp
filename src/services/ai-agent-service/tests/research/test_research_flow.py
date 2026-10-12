"""A7 normal araştırma akışı: tam rapor, kaynaklı kanıt, giriş noktası
yönlendirmesi, ikinci tur ve ilerleme çıktısı.

Plan A7 kabul ölçütü "normal araştırma ... gerçekçi fixture'larla çalışır":
fixture'lar gerçek HTTP (localhost mock sunucu) üzerinden A6 araçlarıyla
koşar; model/arama double'larıdır ve gerçek sağlayıcı başarısı sayılmaz.
Mock sunucu start/stop'u aynı event loop'ta yapılır (Windows Proactor) —
senaryolar tek ``asyncio.run`` içinde koşar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_core.budget.guard import BudgetGuard
from agent_core.budget.store import PolicyBudgetStore
from agent_core.errors import AgentErrorCode
from agent_core.models import ProgressKind, RunStatus
from agent_core.research.models import SupportKind
from agent_core.research.report import SOURCE_ID_PATTERN
from agent_core.research.runner import run_deep_research
from agent_core.web import build_web_tools
from web.web_helpers import MockWebServer, make_settings

from .conftest import (
    ERRORS_TEXT,
    GUIDE_TEXT,
    FixedModelProvider,
    RoutingSearchProvider,
    build_server,
    build_web_bundle,
    make_research_context,
    make_research_policy,
    make_research_route,
    make_research_snapshot,
    run,
)


def _normal_pages() -> dict[str, str]:
    return {"/guide": GUIDE_TEXT, "/errors": ERRORS_TEXT}


def _unwired_tools(run_id: str) -> dict:
    """Sağlayıcısız araç kümesi: ``search_web`` yok (config_error senaryosu)."""
    policy = make_research_policy()
    guard = BudgetGuard(PolicyBudgetStore(policy), policy, run_id)
    return build_web_tools(guard, make_settings())


# --- Normal araştırma: tam rapor -----------------------------------------------


def test_normal_research_completes_with_evidence_backed_report() -> None:
    async def scenario() -> dict[str, Any]:
        async with build_server(_normal_pages()) as server:
            provider = RoutingSearchProvider([("", [server.url("/guide"), server.url("/errors")])])
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            model = FixedModelProvider(
                "Kaynaklar kuyruk sınırı ve hata yönetimi önerilerini destekliyor."
            )
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=model,
                web_tools=web_tools,
                policy=policy,
                store=store,
            )
            return {
                "outcome": result.outcome,
                "state": result.state,
                "provider_calls": list(provider.calls),
                "model": model,
                "guide_url": server.url("/guide"),
            }

    data = run(scenario())
    outcome = data["outcome"]
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.selected_mode.value == "deep_research"
    assert outcome.report is not None and outcome.answer is None
    assert outcome.source_scope.value == "article_and_web"
    assert data["provider_calls"], "arama sağlayıcısı kullanıldı"
    assert outcome.usage.web_search_calls > 0
    assert data["model"].call_count == 1  # kısa sonuç için tek model çağrısı
    assert data["model"].requests[0].metadata["flow"] == "article_research"

    # Plan A7 rapor bölüm kümesi: kısa sonuç, kapsam, tarih, makaleyle
    # ilişki, karşılaştırma, bulgular, belirsizlikler, kaynaklar, tamamlanma.
    report_text = outcome.report
    for section in (
        "## Kısa sonuç", "## Kapsam", "## Tarih", "## Makaleyle ilişki",
        "## Karşılaştırma", "## Bulgular", "## Belirsizlikler", "## Kaynaklar",
        "## Tamamlanma durumu",
    ):
        assert section in report_text, f"rapor bölümü eksik: {section}"
    assert "tam —" in report_text  # tamamlanma durumu: complete
    assert data["guide_url"] in report_text  # kaynaklar bölümünde gerçek URL

    # Kanıtlar: her iki iddia da destek kanıtı taşıyor; kanıt kayıtları
    # DONMUŞ EvidenceItem sözleşmesine daraltılabilir.
    evidence = list(data["state"]["evidence"])
    assert evidence, "kanıt üretildi"
    supported_claims = {
        record.claim_id for record in evidence if record.support is SupportKind.SUPPORTS
    }
    assert len(supported_claims) == 2  # claim-1 ve claim-2 destekli
    for record in evidence:
        item = record.to_evidence_item(collected_at=datetime.now(timezone.utc))
        assert item.evidence_id == record.evidence_id
        assert item.source.kind == "web"
        assert item.excerpt

    # Programatik kontrol alanları: URL eşleşmesi + içerik hash'i.
    entries_by_id = {entry.source_id: entry for entry in data["state"]["sources"]}
    for record in evidence:
        entry = entries_by_id[record.source_id]
        assert record.url == entry.final_url
        assert record.source_content_hash == entry.content_hash

    # Atıflar: yalnız kayıt defterindeki kaynaklar.
    citation_ids = {citation.source_id for citation in outcome.citations}
    assert citation_ids and citation_ids <= set(entries_by_id)


def test_report_contains_no_fabricated_source_ids() -> None:
    """Model çıktısına eklenen uydurma kaynak kimliği rapora geçmez (plan kabul ölçütü)."""

    async def scenario() -> dict[str, Any]:
        async with build_server(_normal_pages()) as server:
            provider = RoutingSearchProvider([("", [server.url("/guide")])])
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            model = FixedModelProvider(fabricated_marker="web:deadbeefdeadbeef:20261012T000000Z")
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=model,
                web_tools=web_tools,
                policy=policy,
                store=store,
            )
            return {"outcome": result.outcome, "state": result.state}

    data = run(scenario())
    # Fixture yalnız /guide döndürür: claim-2 karşılıksız → kısmi beklenir;
    # bu testin konusu uydurma kimliğin rapora geçmemesidir.
    assert data["outcome"].status is RunStatus.PARTIAL
    report_text = data["outcome"].report or ""
    assert "web:deadbeefdeadbeef" not in report_text
    valid_ids = {entry.source_id for entry in data["state"]["sources"]}
    found = set(SOURCE_ID_PATTERN.findall(report_text))
    assert found <= valid_ids, f"raporda kayıt defteri dışı kimlik: {found - valid_ids}"
    dropped = [
        record for record in data["state"]["errors"] if "uydurma kaynak kimlikleri" in record.message
    ]
    assert dropped, "kontrol düğümü uydurma kimliği hata izine yazmalı"


# --- Giriş noktası yönlendirmesi -------------------------------------------------


def test_entrypoint_dispatches_deep_research_when_web_tools_wired() -> None:
    from agent_core.entrypoints import execute_plan, prepare_and_route

    async def scenario() -> Any:
        async with build_server(_normal_pages()) as server:
            provider = RoutingSearchProvider([("", [server.url("/guide"), server.url("/errors")])])
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            context = make_research_context()
            prepared = await prepare_and_route(context)
            model = FixedModelProvider("Kaynaklar önerileri destekliyor.")
            outcome = await execute_plan(prepared, model=model, web_tools=web_tools, budget=store)
            return outcome, model

    outcome, model = run(scenario())
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.report is not None
    assert model.requests[0].metadata["flow"] == "article_research"


def test_entrypoint_keeps_legacy_note_when_web_tools_absent() -> None:
    """``web_tools`` verilmezse A5 geçiş davranışı korunur (tests/qa sözleşmesi)."""
    from agent_core.adapters.test_doubles.fake_web import FakeWebSearchProvider
    from agent_core.entrypoints import execute_plan, prepare_and_route

    context = make_research_context()
    prepared = run(prepare_and_route(context))
    web = FakeWebSearchProvider([])
    model = FixedModelProvider("# Rapor\n\nMakale bulguları.")

    outcome = run(execute_plan(prepared, model=model, web_search=web))

    assert outcome.status is RunStatus.COMPLETED
    assert (
        "web araştırma akışı bu sürümde henüz uygulanmadığı için dış kanıt toplanamadı"
        in (outcome.report or "")
    )
    assert web.call_count == 0  # graph koşmadı; geçiş yolu


def test_unwired_search_tool_fails_with_config_error() -> None:
    """search_web bağlı değilse anlaşılır config_error terminali döner (plan A1)."""
    from agent_core.entrypoints import execute_plan, prepare_and_route

    async def scenario() -> Any:
        context = make_research_context()
        prepared = await prepare_and_route(context)
        model = FixedModelProvider()
        outcome = await execute_plan(
            prepared, model=model, web_tools=_unwired_tools(context.run_id)
        )
        return outcome, model

    outcome, model = run(scenario())
    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.CONFIG_ERROR
    assert model.call_count == 0


# --- İkinci araştırma turu ---------------------------------------------------------


def test_second_round_runs_for_uncovered_claim() -> None:
    """İlk turda karşılanmayan iddia için bütçe varsa ikinci tur koşar (plan adım 7)."""

    async def scenario() -> dict[str, Any]:
        async with build_server(_normal_pages()) as server:
            # İlk turda claim-2 alt sorusu boş döner; ikinci tur iddia sorgusu
            # ("QueueFull" içerir) /errors sayfasını bulur.
            provider = RoutingSearchProvider(
                [
                    ("uyumlu mu: Kuyruk dolunca", []),  # round-1 claim-2 alt sorusu: boş
                    ("QueueFull", [server.url("/errors")]),  # round-2 claim sorgusu
                    ("", [server.url("/guide")]),
                ]
            )
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=FixedModelProvider("Bulgunun özeti."),
                web_tools=web_tools,
                policy=policy,
                store=store,
            )
            return {"outcome": result.outcome, "state": result.state}

    data = run(scenario())
    assert data["outcome"].status is RunStatus.COMPLETED
    state = data["state"]
    rounds = [
        event
        for event in state["usage_events"]
        if event.kind.value == "research_round" and event.outcome == "success"
    ]
    assert len(rounds) == 2, "iki tur bütçeye yazılmalı"
    assert state["research_round"] == 2
    assert state["coverage"].uncovered_claim_ids == []
    evidence = list(state["evidence"])
    assert any(
        record.support is SupportKind.SUPPORTS and "QueueFull" in record.excerpt
        for record in evidence
    ), "ikinci turda claim-2 kanıtı toplandı"


# --- İlerleme çıktısı ---------------------------------------------------------------


def test_progress_publishes_only_user_useful_stages() -> None:
    """İlerleme yalnız kullanıcıya yararlı aşamaları taşır (plan A7)."""
    from agent_core.adapters.test_doubles.fake_signals import RecordingProgressSink

    async def scenario() -> dict[str, Any]:
        async with build_server(_normal_pages()) as server:
            provider = RoutingSearchProvider([("", [server.url("/guide"), server.url("/errors")])])
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            sink = RecordingProgressSink()
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=FixedModelProvider(),
                web_tools=web_tools,
                policy=policy,
                store=store,
                progress=sink,
            )
            return {"outcome": result.outcome, "events": list(sink.events)}

    data = run(scenario())
    assert data["outcome"].status is RunStatus.COMPLETED
    kinds = {event.kind for event in data["events"]}
    allowed = {
        ProgressKind.RESEARCH_STARTED,
        ProgressKind.RESEARCH_ROUND_COMPLETED,
        ProgressKind.RETRIEVAL_COMPLETED,
        ProgressKind.GENERATION_STARTED,
        ProgressKind.GENERATION_COMPLETED,
    }
    assert kinds <= allowed, f"kullanıcıya yararsız aşama yayıldı: {kinds - allowed}"
    assert ProgressKind.RESEARCH_STARTED in kinds
    assert ProgressKind.RESEARCH_ROUND_COMPLETED in kinds
    assert ProgressKind.GENERATION_COMPLETED in kinds
    # Kaynak başına gürültü yok: olay sayısı adım sayısı mertebesinde.
    assert len(data["events"]) <= 8


# --- Kapsam doğrulama ---------------------------------------------------------------


def test_research_without_article_context_fails() -> None:
    """Makale bağlamı yoksa araştırma kapsam doğrulamasıyla başarısız olur (adım 1)."""
    snapshot = make_research_snapshot()
    context = make_research_context(
        snapshot,
        article_id=None,
        article_revision=None,
        article_content_hash=None,
        article_snapshot=None,
    )
    provider = RoutingSearchProvider([])
    policy = make_research_policy()
    web_tools, store = build_web_bundle(MockWebServer(), provider, policy=policy)

    result = run(
        run_deep_research(
            context,
            make_research_route(),
            model=FixedModelProvider(),
            web_tools=web_tools,
            policy=policy,
            store=store,
        )
    )

    assert result.outcome.status is RunStatus.FAILED
    assert result.outcome.error_code is AgentErrorCode.VALIDATION_ERROR
