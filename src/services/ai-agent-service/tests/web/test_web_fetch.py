"""A6 getirme motoru testleri: sınır, kodlama, yönlendirme, iptal ve hata eşlemesi."""

from __future__ import annotations

import pytest

from agent_core.adapters.test_doubles.fake_signals import PreCancelledToken
from agent_core.errors import AgentErrorCode, PortError
from agent_core.web import HttpFetcher, UrlGuard

from .web_helpers import (
    MockResponse,
    MockWebServer,
    html_page,
    make_settings,
    raw_chunked_response,
    run,
)


def make_fetcher(settings, resolver=None) -> HttpFetcher:
    return HttpFetcher(settings, UrlGuard.from_settings(settings, resolver=resolver))


# --- Temel getirme ve kodlama ----------------------------------------------------


def test_fetch_html_ok() -> None:
    async def scenario():
        async with MockWebServer() as server:
            server.handlers["/doc"] = MockResponse.html(html_page("<p>Merhaba dünya</p>", title="Belge"))
            settings = make_settings(server)
            return await make_fetcher(settings).fetch(server.url("/doc"))

    content = run(scenario())
    assert content.status_code == 200
    assert content.final_url.endswith("/doc")
    assert content.redirect_count == 0
    assert b"Merhaba" in content.body
    assert content.content_type == "text/html; charset=utf-8"
    assert content.fetched_at.tzinfo is not None


def test_fetch_decodes_gzip() -> None:
    async def scenario():
        async with MockWebServer() as server:
            server.handlers["/gz"] = MockResponse.gzip_html(html_page("<p>sıkıştırılmış</p>"))
            return await make_fetcher(make_settings(server)).fetch(server.url("/gz"))

    assert "sıkıştırılmış".encode("utf-8") in run(scenario()).body


def test_fetch_decodes_deflate() -> None:
    async def scenario():
        async with MockWebServer() as server:
            server.handlers["/df"] = MockResponse.deflate_html(html_page("<p>deflate</p>"))
            return await make_fetcher(make_settings(server)).fetch(server.url("/df"))

    assert b"deflate" in run(scenario()).body


def test_fetch_decodes_chunked() -> None:
    async def scenario():
        async with MockWebServer() as server:
            server.handlers["/chunk"] = raw_chunked_response([b"<p>parca1</p>", b"<p>parca2</p>"])
            return await make_fetcher(make_settings(server)).fetch(server.url("/chunk"))

    assert b"parca1" in run(scenario()).body and b"parca2" in run(scenario()).body


def test_fetch_follows_redirect_chain() -> None:
    async def scenario():
        async with MockWebServer() as server:
            server.handlers["/a"] = MockResponse.redirect("/b", status=302)
            server.handlers["/b"] = MockResponse.redirect("/c", status=301)
            server.handlers["/c"] = MockResponse.html(html_page("<p>son</p>", title="Son"))
            return await make_fetcher(make_settings(server)).fetch(server.url("/a"))

    content = run(scenario())
    assert content.final_url.endswith("/c")
    assert content.redirect_count == 2
    assert content.requested_url.endswith("/a")


def test_redirect_loop_hits_limit() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/self"] = MockResponse.redirect("/self")
            settings = make_settings(server, max_redirects=2)
            try:
                await make_fetcher(settings).fetch(server.url("/self"))
            except PortError as error:
                return error
            raise AssertionError("yönlendirme sınırı aşılmalıydı")

    error = run(scenario())
    assert error.code is AgentErrorCode.PROVIDER_ERROR
    assert "yönlendirme sınırı" in error.message


def test_redirect_without_location_is_error() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/noloc"] = MockResponse(status=302, headers={}, body=b"")
            try:
                await make_fetcher(make_settings(server)).fetch(server.url("/noloc"))
            except PortError as error:
                return error
            raise AssertionError("hedefsiz yönlendirme hata vermeliydi")

    error = run(scenario())
    assert "yönlendirme hedefi yok" in error.message


# --- Durum kodu eşlemesi ----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_code", "message_part"),
    [
        (404, AgentErrorCode.NOT_FOUND, "bulunamadı"),
        (410, AgentErrorCode.NOT_FOUND, "kaldırıldı"),
        (403, AgentErrorCode.PROVIDER_ERROR, "erişim engellendi"),
        (401, AgentErrorCode.PROVIDER_ERROR, "erişim engellendi"),
        (429, AgentErrorCode.PROVIDER_ERROR, "oran sınırı"),
        (500, AgentErrorCode.PROVIDER_ERROR, "sağlayıcı arızası"),
    ],
)
def test_status_mapping(status: int, expected_code: AgentErrorCode, message_part: str) -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/s"] = MockResponse(status=status, headers={"Content-Type": "text/plain"}, body=b"x")
            try:
                await make_fetcher(make_settings(server)).fetch(server.url("/s"))
            except PortError as error:
                return error
            raise AssertionError(f"HTTP {status} hata vermeliydi")

    error = run(scenario())
    assert error.code is expected_code
    assert message_part in error.message
    if status == 429 or status == 500:
        assert error.retryable is True
    else:
        assert error.retryable is False


# --- Sınırlar ----------------------------------------------------------------------


def test_size_limit_exceeded_by_content_length() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            big = b"x" * 256
            server.handlers["/big"] = MockResponse(status=200, headers={"Content-Type": "text/plain"}, body=big)
            settings = make_settings(server, max_response_bytes=64)
            try:
                await make_fetcher(settings).fetch(server.url("/big"))
            except PortError as error:
                return error
            raise AssertionError("boyut sınırı aşılmalıydı")

    error = run(scenario())
    assert "yanıt boyutu sınırı aşıldı" in error.message


def test_unsupported_content_type_rejected() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/pdf"] = MockResponse(status=200, headers={"Content-Type": "application/pdf"}, body=b"%PDF-1.4")
            try:
                await make_fetcher(make_settings(server)).fetch(server.url("/pdf"))
            except PortError as error:
                return error
            raise AssertionError("desteklenmeyen içerik türü reddedilmeliydi")

    error = run(scenario())
    assert "desteklenmeyen içerik türü" in error.message


def test_truncated_body_is_error() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            raw = (
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                b"Content-Length: 100\r\nConnection: close\r\n\r\nshort"
            )
            server.handlers["/short"] = type("R", (), {"raw": raw})  # _RawResponse yeterince
            from .web_helpers import _RawResponse

            server.handlers["/short"] = _RawResponse(raw)
            try:
                await make_fetcher(make_settings(server)).fetch(server.url("/short"))
            except PortError as error:
                return error
            raise AssertionError("kesik gövde hata vermeliydi")

    error = run(scenario())
    assert "kısa kesildi" in error.message
    assert error.retryable is True


def test_slow_response_times_out() -> None:
    from .web_helpers import _DelayedResponse

    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/slow"] = _DelayedResponse(seconds=5.0)
            settings = make_settings(server, header_timeout_s=0.3, total_timeout_s=1.0)
            try:
                await make_fetcher(settings).fetch(server.url("/slow"))
            except PortError as error:
                return error
            raise AssertionError("zaman aşımı bekleniyordu")

    error = run(scenario())
    assert error.code is AgentErrorCode.TIMEOUT
    assert error.retryable is True


# --- İptal ve başlık güvenliği ------------------------------------------------------


def test_precancelled_token_fails_before_any_request() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/"] = MockResponse.html("<p>x</p>")
            fetcher = make_fetcher(make_settings(server))
            try:
                await fetcher.fetch(server.url("/"), cancel=PreCancelledToken("iptal"))
            except PortError as error:
                return error
            raise AssertionError("iptal sinyali bekleniyordu")

    error = run(scenario())
    assert error.code is AgentErrorCode.CANCELLED


def test_extra_header_with_control_char_rejected() -> None:
    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/"] = MockResponse.html("<p>x</p>")
            fetcher = make_fetcher(make_settings(server))
            try:
                await fetcher.fetch(server.url("/"), extra_headers={"X-A": "v\r\nEvil: 1"})
            except PortError as error:
                return error
            raise AssertionError("kontrol karakterli başlık reddedilmeliydi")

    error = run(scenario())
    assert "kontrol karakteri" in error.message


def test_request_host_header_uses_server_name() -> None:
    async def scenario() -> str:
        async with MockWebServer() as server:
            server.handlers["/"] = MockResponse.html("<p>ok</p>")
            await make_fetcher(make_settings(server)).fetch(server.url("/"))
            return server.requests[0].headers["host"]

    assert run(scenario()).startswith("127.0.0.1:")


def test_ipv6_target_host_header_is_bracketed() -> None:
    """IPv6 hedeflerde Host ve URL gösterimi köşeli parantezli olmalı (RFC 3986)."""
    settings = make_settings(server=None, allow_loopback=True, allowed_ports=(80, 443, 9000))
    fetcher = make_fetcher(settings)
    target = fetcher.parse_url("http://[::1]:9000/x")
    assert target.url == "http://[::1]:9000/x"
    assert target.host == "::1"  # DNS/SNI alanı çıplak adres
    request = fetcher._build_request(target)
    assert b"Host: [::1]:9000" in request
