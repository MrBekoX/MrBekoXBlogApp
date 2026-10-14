"""Streaming sözleşmesi: research ``make_report`` node'unun ``GENERATION_DELTA`` yayını.

Kısa sonuç taslağı ``stream_complete`` ile üretilir; scripted parçalar
``GENERATION_DELTA`` olarak akar. Rapor kontrol aşamasında (uydurma kaynak
sökümü + yapılandırılmış kurulum) işlendiği için terminal rapor metni
akıştan HAFİF FARKLI olabilir (bilinçli sınır; risks kaydı).
"""

from __future__ import annotations

from typing import Any

from agent_core.adapters.test_doubles import RecordingProgressSink
from agent_core.models import ProgressKind, RunStatus
from agent_core.research.runner import run_deep_research
from web.web_helpers import MockWebServer

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
    run,
)

PAGES = {"/guide": GUIDE_TEXT, "/errors": ERRORS_TEXT}


class DeltaModel(FixedModelProvider):
    """``FixedModelProvider`` + scripted parça yayını (streaming testi için)."""

    is_test_double = True

    def __init__(self, text: str, chunks: list[str], *, fabricated_marker: str | None = None) -> None:
        super().__init__(text, fabricated_marker=fabricated_marker)
        self._chunks = list(chunks)

    async def stream_complete(
        self, request: Any, *, cancel: Any = None, on_delta: Any
    ) -> Any:
        for chunk in self._chunks:
            await on_delta(chunk)
        return await self.complete(request, cancel=cancel)


def test_research_report_streams_scripted_deltas() -> None:
    async def scenario() -> dict[str, Any]:
        async with build_server(PAGES) as server:
            assert isinstance(server, MockWebServer)
            provider = RoutingSearchProvider([("", [server.url("/guide"), server.url("/errors")])])
            policy = make_research_policy()
            web_tools, store = build_web_bundle(server, provider, policy=policy)
            sink = RecordingProgressSink()
            model = DeltaModel(
                "Kaynaklar kuyruk sınırı ve hata yönetimi önerilerini destekliyor.",
                ["Kaynaklar kuyruk", " sınırı ve", " hata yönetimi önerilerini destekliyor."],
            )
            result = await run_deep_research(
                make_research_context(),
                make_research_route(),
                model=model,
                web_tools=web_tools,
                policy=policy,
                store=store,
                progress=sink,
            )
            return {"outcome": result.outcome, "sink": sink}

    data = run(scenario())
    outcome = data["outcome"]
    sink: RecordingProgressSink = data["sink"]

    deltas = [event.message for event in sink.events if event.kind is ProgressKind.GENERATION_DELTA]
    assert deltas == [
        "Kaynaklar kuyruk",
        "sınırı ve",
        "hata yönetimi önerilerini destekliyor.",
    ]
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.report is not None
    # Kontrol aşaması raporu yapılandırır: terminal rapor akış birleşiminden
    # bağımsızdır (rapor bölümleri eklenir).
    assert "## Kısa sonuç" in outcome.report
    assert "kuyruk" in outcome.report
