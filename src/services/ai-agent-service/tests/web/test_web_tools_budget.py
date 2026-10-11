"""A6 araç–bütçe entegrasyonu ve ``search_web`` sağlayıcı testleri.

Plan A6 kabul ölçütü: "Her dış araç denemesi bütçe kaydına yansır." Retry
denemeleri ayrı olay olarak yazılır (A2: ``event_id = action_id#attempt``);
``budget_exhausted`` çağrı ÖNCESİ reddedilir ve olay üretmez; yerel araçlar
(extract_text, assess_source) dış deneme olmadığından olay üretmez.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agent_core.adapters.test_doubles.fake_signals import PreCancelledToken
from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import BudgetKind, ReadSource, SourceReader
from agent_core.web import (
    AssessSourceTool,
    ExtractionStatus,
    ExtractTextTool,
    HttpSourceReader,
    HttpWebSearchProvider,
    ReadSourceTool,
    SearchWebTool,
    TextExtractor,
    WebSourceRecord,
    WebToolSettings,
)
from agent_core.web.fetch import HttpFetcher
from agent_core.web.ssrf import UrlGuard

from .web_helpers import (
    CapacityBudgetStore,
    FakeBudgetStore,
    MockResponse,
    MockWebServer,
    ScriptedSearchProvider,
    html_page,
    make_settings,
    run,
)

RESULT_OK = [{"title": "Sonuç", "url": "https://example.com/r", "snippet": "özet"}]


def make_guard(store=None, *, max_attempts: int = 2) -> BudgetGuard:
    return BudgetGuard(
        store or FakeBudgetStore(),
        BudgetPolicy(max_attempts_per_action=max_attempts, max_duration_seconds=60),
        "run-a6",
    )


def make_search_tool(provider, store=None, *, max_attempts: int = 2) -> SearchWebTool:
    return SearchWebTool(make_guard(store, max_attempts=max_attempts), provider, settings=WebToolSettings(environment="test", retry_backoff_base_s=0))


def retryable_error() -> PortError:
    return PortError(AgentErrorCode.PROVIDER_ERROR, "sağlayıcı 500", port="WebSearchProvider", retryable=True)


def hard_error() -> PortError:
    return PortError(AgentErrorCode.PROVIDER_ERROR, "erişim engellendi", port="WebSearchProvider", retryable=False)


# --- search_web bütçe olayları --------------------------------------------------------


def test_search_success_records_single_budget_event() -> None:
    provider = ScriptedSearchProvider([RESULT_OK])
    store = FakeBudgetStore()
    tool = make_search_tool(provider, store)
    events: list = []
    results = run(tool.search("asyncio iptal", events_sink=events))

    assert results[0].url == "https://example.com/r"
    assert len(events) == 1
    event = events[0]
    assert event.kind.value == "web_search_call"
    assert event.outcome == "success"
    assert event.attempt == 1
    assert event.event_id.endswith("#1")
    assert store.committed[BudgetKind.WEB_SEARCH_CALL] == 1


def test_search_empty_query_rejected_before_budget() -> None:
    provider = ScriptedSearchProvider([RESULT_OK])
    store = FakeBudgetStore()
    tool = make_search_tool(provider, store)
    with pytest.raises(PortError) as excinfo:
        run(tool.search("   "))
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert provider.calls == []  # çağrı hiç başlamadı
    assert store.committed == {}  # bütçe olayı yok


def test_search_retryable_failure_then_success_records_both_attempts() -> None:
    provider = ScriptedSearchProvider([retryable_error(), RESULT_OK])
    store = FakeBudgetStore()
    tool = make_search_tool(provider, store)
    events: list = []
    results = run(tool.search("sorgu", events_sink=events))

    assert results[0].title == "Sonuç"
    assert [e.outcome for e in events] == ["failed", "success"]
    assert [e.attempt for e in events] == [1, 2]
    assert events[0].event_id != events[1].event_id
    assert store.committed[BudgetKind.WEB_SEARCH_CALL] == 2  # başarısız deneme de bütçededir


def test_search_hard_failure_records_single_failed_event() -> None:
    provider = ScriptedSearchProvider([hard_error()])
    store = FakeBudgetStore()
    tool = make_search_tool(provider, store)
    events: list = []
    with pytest.raises(PortError):
        run(tool.search("sorgu", events_sink=events))
    assert len(provider.calls) == 1  # tekrar denenmez
    assert [e.outcome for e in events] == ["failed"]
    assert store.committed[BudgetKind.WEB_SEARCH_CALL] == 1


def test_search_retry_exhaustion_respects_policy() -> None:
    provider = ScriptedSearchProvider([retryable_error(), retryable_error(), retryable_error()])
    store = FakeBudgetStore()
    tool = make_search_tool(provider, store, max_attempts=2)
    events: list = []
    with pytest.raises(PortError) as excinfo:
        run(tool.search("sorgu", events_sink=events))
    assert excinfo.value.retryable is True
    assert len(provider.calls) == 2
    assert [e.outcome for e in events] == ["failed", "failed"]
    assert store.committed[BudgetKind.WEB_SEARCH_CALL] == 2


def test_search_budget_exhausted_rejected_before_call_without_events() -> None:
    provider = ScriptedSearchProvider([RESULT_OK])
    store = CapacityBudgetStore({BudgetKind.WEB_SEARCH_CALL: 0})
    tool = make_search_tool(provider, store)
    events: list = []
    with pytest.raises(PortError) as excinfo:
        run(tool.search("sorgu", events_sink=events))
    assert excinfo.value.code is AgentErrorCode.BUDGET_EXHAUSTED
    assert provider.calls == []  # rezervasyon reddi: çağrı başlamadı
    assert events == []


def test_search_precancelled_before_budget() -> None:
    provider = ScriptedSearchProvider([RESULT_OK])
    tool = make_search_tool(provider)
    with pytest.raises(PortError) as excinfo:
        run(tool.search("sorgu", cancel=PreCancelledToken()))
    assert excinfo.value.code is AgentErrorCode.CANCELLED
    assert provider.calls == []


# --- read_source bütçe olayları ve kayıt ------------------------------------------------


def test_read_success_produces_record_with_plan_fields() -> None:
    async def scenario():
        async with MockWebServer() as server:
            page = html_page(
                "<p>RabbitMQ publisher confirm davranışı açıklanır.</p>",
                title="Confirms",
                meta='<meta property="og:site_name" content="RabbitMQ">'
                '<meta property="article:published_time" content="2025-06-01T00:00:00Z">',
            )
            server.handlers["/docs/confirms"] = MockResponse.html(page)
            tool, _ = make_read_tool_for(server)
            events: list = []
            record = await tool.read(server.url("/docs/confirms"), events_sink=events)
            return record, events

    record, events = run(scenario())
    assert record.extraction_status.value == "ok"
    assert record.title == "Confirms"
    assert record.publisher == "RabbitMQ"
    assert record.published_at == datetime(2025, 6, 1, tzinfo=timezone.utc)
    assert record.accessed_at is not None
    assert len(record.content_hash) == 64
    assert record.final_url == record.url  # yönlendirme yok
    assert record.full_page_read is True
    kinds = {e.kind.value for e in record.evidences}
    assert kinds == {"full_page", "page_metadata"}
    metadata = next(e for e in record.evidences if e.kind.value == "page_metadata")
    assert "yayın tarihi: 2025-06-01" in metadata.excerpt
    assert [e.kind.value for e in events] == ["source_page_read"]
    assert events[0].outcome == "success"


def test_read_http_block_records_failed_budget_event() -> None:
    async def scenario():
        async with MockWebServer() as server:
            server.handlers["/deny"] = MockResponse(status=403, headers={"Content-Type": "text/plain"}, body=b"denied")
            tool, _ = make_read_tool_for(server)
            events: list = []
            try:
                await tool.read(server.url("/deny"), events_sink=events)
            except PortError as error:
                return error, events
            raise AssertionError("403 hata vermeliydi")

    error, events = run(scenario())
    assert "erişim engellendi" in error.message
    assert [e.outcome for e in events] == ["failed"]
    assert events[0].kind.value == "source_page_read"


def test_read_empty_page_reports_empty_status_with_success_event() -> None:
    """Boş kaynak senaryosu: getirme başarılı, çıkarma boş — durumla raporlanır."""
    async def scenario():
        async with MockWebServer() as server:
            server.handlers["/empty"] = MockResponse.html("<html><body></body></html>")
            tool, _ = make_read_tool_for(server)
            events: list = []
            record = await tool.read(server.url("/empty"), events_sink=events)
            return record, events

    record, events = run(scenario())
    assert record.extraction_status.value == "empty"
    assert record.text == ""
    assert [e.outcome for e in events] == ["success"]  # dış deneme başarılı sayılır


def test_read_invalid_url_rejected_before_budget() -> None:
    async def scenario():
        async with MockWebServer() as server:
            tool, _ = make_read_tool_for(server)
            events: list = []
            try:
                await tool.read("file:///etc/passwd", events_sink=events)
            except PortError as error:
                return error, events
            raise AssertionError("file şeması reddedilmeliydi")

    error, events = run(scenario())
    assert error.code is AgentErrorCode.VALIDATION_ERROR
    assert events == []  # çağrı başlamadı


def make_read_tool_for(server):
    settings = make_settings(server)
    store = FakeBudgetStore()
    guard = make_guard(store)
    fetcher = HttpFetcher(settings, UrlGuard.from_settings(settings))
    return ReadSourceTool(guard, fetcher, TextExtractor(settings), settings=settings), guard


# --- Yerel araçlar bütçe olayı üretmez ---------------------------------------------------


def test_extract_text_is_local_and_budget_free() -> None:
    from agent_core.web import FetchedContent

    content = FetchedContent(
        requested_url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=html_page("<p>yerel çıkarma</p>").encode("utf-8"),
        fetched_at=datetime.now(timezone.utc),
    )
    store = FakeBudgetStore()
    tool = ExtractTextTool(TextExtractor(WebToolSettings(environment="test")))
    extracted = run(tool.extract(content))
    assert extracted.extraction_status.value == "ok"
    assert store.committed == {}  # dış deneme yok


def test_assess_source_is_local_and_budget_free() -> None:
    record = WebSourceRecord(
        url="https://docs.python.org/x",
        final_url="https://docs.python.org/x",
        title="T",
        accessed_at=datetime.now(timezone.utc),
        content_hash="a" * 64,
        extraction_status=ExtractionStatus.OK,
        text="metin",
    )
    store = FakeBudgetStore()
    tool = AssessSourceTool()
    assessment = run(tool.assess(record))
    assert assessment.source_type.value == "official_docs"
    assert store.committed == {}


# --- Port uyumu (A1 sözleşmesi DONMUŞ) ---------------------------------------------------


def test_http_source_reader_satisfies_port_protocol() -> None:
    async def scenario():
        async with MockWebServer() as server:
            server.handlers["/ok"] = MockResponse.html(html_page("<p>port uyumlu metin</p>", title="Port"))
            settings = make_settings(server)
            reader = HttpSourceReader(HttpFetcher(settings, UrlGuard.from_settings(settings)), TextExtractor(settings))
            assert isinstance(reader, SourceReader)
            return await reader.read(server.url("/ok"))

    read_source = run(scenario())
    assert isinstance(read_source, ReadSource)
    assert read_source.title == "Port"
    assert "port uyumlu metin" in read_source.text


def test_http_source_reader_maps_empty_to_not_found() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/empty"] = MockResponse.html("<html><body></body></html>")
            settings = make_settings(server)
            reader = HttpSourceReader(HttpFetcher(settings, UrlGuard.from_settings(settings)), TextExtractor(settings))
            try:
                await reader.read(server.url("/empty"))
            except PortError as error:
                return error
            raise AssertionError("boş içerik not_found vermeliydi")

    error = run(scenario())
    assert error.code is AgentErrorCode.NOT_FOUND


# --- HttpWebSearchProvider (gerçek JSON uç noktası, mock sunucu) ---------------------------


def test_search_provider_parses_json_results() -> None:
    async def scenario():
        async with MockWebServer() as server:
            payload = json.dumps(
                {"results": [
                    {"title": "Asyncio docs", "url": "https://docs.python.org/3/library/asyncio.html", "snippet": "coroutines"},
                    {"title": "Bozuk girdi"},  # url yok: atlanır
                ]}
            )
            server.handlers["/search"] = MockResponse.json_text(payload)
            settings = make_settings(server)
            provider = HttpWebSearchProvider(server.url("/search"), settings, UrlGuard.from_settings(settings))
            results = await provider.search("asyncio", max_results=5)
            request = server.requests_to("/search")[0]
            return results, request

    results, request = run(scenario())
    assert len(results) == 1  # bozuk girdi atlandı
    assert results[0].title == "Asyncio docs"
    assert results[0].retrieved_at.tzinfo is not None
    assert "q=asyncio" in request.query


def test_search_provider_sends_api_key_from_env_without_leaking() -> None:
    """Anahtar yalnız sağlayıcıya gider; hata mesajı/kayıt taşımaz (sır kuralı)."""
    import os

    async def scenario() -> tuple[list, str | None]:
        async with MockWebServer() as server:
            server.handlers["/search"] = MockResponse.json_text(json.dumps({"results": RESULT_OK}))
            settings = make_settings(server)
            provider = HttpWebSearchProvider(
                server.url("/search"),
                settings,
                UrlGuard.from_settings(settings),
                api_key_env="A6_TEST_SEARCH_KEY",
            )
            os.environ["A6_TEST_SEARCH_KEY"] = "gizli-deger-test"
            try:
                results = await provider.search("sorgu")
            finally:
                os.environ.pop("A6_TEST_SEARCH_KEY", None)
            auth = server.requests_to("/search")[0].headers.get("authorization")
            return results, auth

    results, auth = run(scenario())
    assert results[0].url == "https://example.com/r"
    assert auth == "Bearer gizli-deger-test"  # anahtar yalnız operatör uç noktasına gitti
    assert os.environ.get("A6_TEST_SEARCH_KEY") is None  # ortam temizlendi; sır koda/loga girmez


def test_search_provider_missing_api_key_is_config_error() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            settings = make_settings(server)
            provider = HttpWebSearchProvider(
                server.url("/search"), settings, UrlGuard.from_settings(settings), api_key_env="A6_MISSING_KEY_ENV"
            )
            import os

            os.environ.pop("A6_MISSING_KEY_ENV", None)
            try:
                await provider.search("sorgu")
            except PortError as error:
                return error
            raise AssertionError("eksik anahtar config_error vermeliydi")

    error = run(scenario())
    assert error.code is AgentErrorCode.CONFIG_ERROR
    assert "A6_MISSING_KEY_ENV" in error.message
    assert "gizli" not in error.message  # değer asla mesaja girmez


def test_search_provider_malformed_json_is_non_retryable_provider_error() -> None:
    async def scenario() -> tuple[PortError, int]:
        async with MockWebServer() as server:
            server.handlers["/search"] = MockResponse.json_text("{bozuk json")
            settings = make_settings(server)
            provider = HttpWebSearchProvider(server.url("/search"), settings, UrlGuard.from_settings(settings))
            try:
                await provider.search("sorgu")
            except PortError as error:
                return error, len(server.requests_to("/search"))
            raise AssertionError("bozuk JSON hata vermeliydi")

    error, calls = run(scenario())
    assert error.code is AgentErrorCode.PROVIDER_ERROR
    assert error.retryable is False
    assert calls == 1  # tekrar denenmez


def test_search_provider_missing_results_key_is_error() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/search"] = MockResponse.json_text(json.dumps({"veriler": []}))
            settings = make_settings(server)
            provider = HttpWebSearchProvider(server.url("/search"), settings, UrlGuard.from_settings(settings))
            try:
                await provider.search("sorgu")
            except PortError as error:
                return error
            raise AssertionError("'results' yoksa hata beklenir")

    error = run(scenario())
    assert error.code is AgentErrorCode.PROVIDER_ERROR
    assert "results" in error.message


def test_search_provider_rate_limit_is_retryable() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/search"] = MockResponse(status=429, headers={"Content-Type": "text/plain"}, body=b"slow down")
            settings = make_settings(server)
            provider = HttpWebSearchProvider(server.url("/search"), settings, UrlGuard.from_settings(settings))
            try:
                await provider.search("sorgu")
            except PortError as error:
                return error
            raise AssertionError("429 hata vermeliydi")

    error = run(scenario())
    assert "oran sınırı" in error.message
    assert error.retryable is True


def test_build_web_tools_without_provider_has_no_search() -> None:
    from agent_core.web import build_web_tools

    tools = build_web_tools(make_guard(), WebToolSettings(environment="test"))
    assert set(tools) == {"read_source", "extract_text", "assess_source", "source_reader", "fetcher"}


# --- Kısa güncel soru senaryosu: arama → okuma → değerlendirme ------------------------


def test_short_freshness_question_end_to_end() -> None:
    """Plan A6 kabul: 'kısa güncel soru' akışı araç katmanında uçtan uca doğrulanır.

    Kısa güncellik sorusu → search_web (snippet kanıtı, tam sayfa sayılmaz) →
    read_source (tam sayfa, metadata) → assess_source (resmî belge önceliği,
    yayın tarihi yoksa uydurulmaz). Tüm dış denemeler bütçededir.
    """
    import os

    async def scenario():
        async with MockWebServer() as server:
            page = html_page(
                "<p>Publisher confirms Since RabbitMQ 3.3, channels...</p>",
                title="Consumer Acknowledgements and Publisher Confirms",
                meta='<meta property="og:site_name" content="RabbitMQ">',  # yayın tarihi yok
            )
            server.handlers["/docs/confirms"] = MockResponse.html(page)
            payload = json.dumps(
                {"results": [{"title": "RabbitMQ Confirms", "url": server.url("/docs/confirms"), "snippet": "confirms since 3.3"}]}
            )
            server.handlers["/search"] = MockResponse.json_text(payload)

            settings = make_settings(server)
            store = FakeBudgetStore()
            guard = make_guard(store)
            provider = HttpWebSearchProvider(server.url("/search"), settings, UrlGuard.from_settings(settings))
            fetcher = HttpFetcher(settings, UrlGuard.from_settings(settings))
            extractor = TextExtractor(settings)
            search_tool = SearchWebTool(guard, provider, settings=settings)
            read_tool = ReadSourceTool(guard, fetcher, extractor, settings=settings)
            assess_tool = AssessSourceTool()

            os.environ["A6_TEST_SEARCH_KEY"] = "test-anahtari"
            try:
                results = await search_tool.search("rabbitmq publisher confirms güncel davranış", max_results=3)
            finally:
                os.environ.pop("A6_TEST_SEARCH_KEY", None)
            snippet_evidence = results[0]

            record = await read_tool.read(snippet_evidence.url)
            assessment = await assess_tool.assess(record)
            return record, assessment, store, snippet_evidence

    record, assessment, store, snippet = run(scenario())
    # arama sonucu snippet'tir: tam sayfa sayılmaz
    assert snippet.snippet == "confirms since 3.3"
    # tam sayfa okuma metadata'yı getirdi; tarih yoksa uydurulmaz
    assert record.extraction_status.value == "ok"
    assert record.published_at is None
    assert "confirms" in record.text
    # değerlendirme resmî belgeyi önceliklendirir
    assert assessment.source_type.value == "official_docs"
    assert assessment.priority_rank == 0 and assessment.preferred is True
    assert any("uydurulmadı" in note for note in assessment.notes)
    # her dış deneme bütçede: 1 arama + 1 okuma
    assert store.committed[BudgetKind.WEB_SEARCH_CALL] == 1
    assert store.committed[BudgetKind.SOURCE_PAGE_READ] == 1
