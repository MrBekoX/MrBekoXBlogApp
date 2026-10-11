"""A6 SSRF koruma testleri: şema, adres engeli, DNS çözümleme, yeniden-çözümlü redirect.

Plan A6: "DNS çözümleme ve yönlendirmeler dahil özel, loopback, link-local ve
metadata adreslerini engelle." Her test somut girdi → somut ret kanıtı verir.
"""

from __future__ import annotations

import socket

import pytest

from agent_core.errors import AgentErrorCode, PortError
from agent_core.web import HttpFetcher, UrlGuard, WebToolSettings

from .web_helpers import (
    MockResponse,
    MockWebServer,
    html_page,
    make_settings,
    run,
)


def strict_settings(**overrides) -> WebToolSettings:
    """Loopback dahil hiçbir özel adrese izin vermeyen ayar (varsayılan üretim durumu)."""
    return make_settings(server=None, allow_loopback=False, **overrides)


def loopback_settings(**overrides) -> WebToolSettings:
    """Yalnız loopback'i açan test ayarı; private/metadata hâlâ engelli."""
    return make_settings(server=None, allow_loopback=True, **overrides)


def mapping_resolver(mapping: dict[str, list[str]], default: str | None = "NXDOMAIN"):
    async def resolve(host: str) -> list[str]:
        if host in mapping:
            return list(mapping[host])
        if default == "NXDOMAIN":
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return list(default or [])

    return resolve


# --- Şema ve URL biçimi -------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/doc",
        "javascript:alert(1)",
        "data:text/html,<h1>hi</h1>",
        "gopher://example.com",
        "/relative/only",
        "",
        "   ",
    ],
)
def test_parse_rejects_non_http_schemes(url: str) -> None:
    guard = UrlGuard(strict_settings())
    with pytest.raises(PortError) as excinfo:
        guard.parse(url)
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR


def test_parse_rejects_userinfo() -> None:
    guard = UrlGuard(strict_settings())
    with pytest.raises(PortError) as excinfo:
        guard.parse("https://user:secret@example.com/doc")
    assert "userinfo" in excinfo.value.message


def test_parse_rejects_disallowed_port() -> None:
    guard = UrlGuard(strict_settings())
    with pytest.raises(PortError) as excinfo:
        guard.parse("http://example.com:8080/doc")
    assert "bağlantı noktası" in excinfo.value.message


def test_parse_rejects_control_characters_in_path() -> None:
    guard = UrlGuard(strict_settings())
    with pytest.raises(PortError) as excinfo:
        guard.parse("http://example.com/a\x00/b")
    assert "kontrol karakteri" in excinfo.value.message


def test_parse_strips_tab_and_newline_from_url() -> None:
    """WHATWG uyumu: urlsplit \t\r\n karakterlerini atar; başlık enjeksiyonu yolu kapanır."""
    guard = UrlGuard(strict_settings())
    target = guard.parse("http://example.com/a\r\nX-Injected: 1")
    assert "\r" not in target.path_with_query and "\n" not in target.path_with_query


def test_parse_rejects_hostless_url() -> None:
    guard = UrlGuard(strict_settings())
    with pytest.raises(PortError) as excinfo:
        guard.parse("http:///only/path")
    assert "host" in excinfo.value.message


# --- Literal IP engeli ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://[::ffff:127.0.0.1]/admin",  # IPv4-eşlenmiş IPv6 sarmalı
        "http://0.0.0.0/",
        "http://10.1.2.3/internal",
        "http://172.16.5.4/internal",
        "http://192.168.1.10/router",
        "http://169.254.169.254/latest/meta-data/",  # bulut metadata
        "http://100.64.0.1/cgnat",
        "http://198.18.0.9/bench",
        "http://[fe80::1]/linklocal",
        "http://[fd00::1]/ula",
    ],
)
def test_parse_blocks_literal_private_and_metadata_addresses(url: str) -> None:
    guard = UrlGuard(strict_settings())
    with pytest.raises(PortError) as excinfo:
        guard.parse(url)
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "yasak adres" in excinfo.value.message


def test_allow_loopback_opens_only_loopback() -> None:
    """Test bayrağı yalnız 127.0.0.0/8 + ::1'i açar; metadata/private engelli kalır."""
    guard = UrlGuard(loopback_settings(allowed_ports=(80, 443, 8080, 9000)))
    assert guard.parse("http://127.0.0.1:8080/ok").host == "127.0.0.1"
    assert guard.parse("http://[::1]:9000/ok").host == "::1"
    for url in (
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.9/",
        "http://192.168.0.5/",
        "http://[fe80::1]/",
    ):
        with pytest.raises(PortError):
            guard.parse(url)


def test_allow_loopback_rejected_outside_test_environment() -> None:
    settings = WebToolSettings(environment="production", allow_loopback=True)
    with pytest.raises(PortError) as excinfo:
        UrlGuard.from_settings(settings)
    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR


# --- DNS çözümleme engeli (yeniden çözümlü koruma girdisi) ----------------------


@pytest.mark.parametrize(
    ("host", "addresses"),
    [
        ("metadata.example", ["169.254.169.254"]),
        ("private.example", ["10.0.0.77"]),
        ("cgnat.example", ["100.64.1.9"]),
        ("mapped.example", ["::ffff:10.0.0.7"]),  # IPv4-eşlenmiş sarmal
        ("nat64.example", ["64:ff9b::a00:1"]),  # NAT64 → 10.0.0.1
        ("linklocal.example", ["fe80::1"]),
    ],
)
def test_resolve_blocks_forbidden_dns_answers(host: str, addresses: list[str]) -> None:
    guard = UrlGuard(loopback_settings(), resolver=mapping_resolver({host: addresses}))
    target = guard.parse(f"http://{host}/x")
    with pytest.raises(PortError) as excinfo:
        run(guard.resolve(target))
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "yasak adres" in excinfo.value.message


def test_resolve_filters_blocked_keeps_public() -> None:
    """Karışık yanıt: engelli adres düşer, genel adres kullanılır."""
    guard = UrlGuard(strict_settings(), resolver=mapping_resolver({"mixed.example": ["169.254.169.254", "93.184.216.34"]}))
    target = guard.parse("http://mixed.example/x")
    allowed = run(guard.resolve(target))
    assert [str(ip) for ip in allowed] == ["93.184.216.34"]


def test_resolve_all_blocked_raises() -> None:
    guard = UrlGuard(strict_settings(), resolver=mapping_resolver({"allbad.example": ["192.168.0.1", "10.9.9.9"]}))
    target = guard.parse("http://allbad.example/x")
    with pytest.raises(PortError) as excinfo:
        run(guard.resolve(target))
    assert "güvenli adres yok" in excinfo.value.message


def test_resolve_nxdomain_maps_to_not_found() -> None:
    guard = UrlGuard(strict_settings(), resolver=mapping_resolver({}))
    target = guard.parse("http://missing.example/x")
    with pytest.raises(PortError) as excinfo:
        run(guard.resolve(target))
    assert excinfo.value.code is AgentErrorCode.NOT_FOUND


def test_resolve_timeout_maps_to_timeout() -> None:
    import asyncio

    async def slow_resolver(host: str) -> list[str]:
        await asyncio.sleep(5.0)
        return ["93.184.216.34"]

    guard = UrlGuard(strict_settings(resolver_timeout_s=0.1), resolver=slow_resolver)
    target = guard.parse("http://slow.example/x")
    with pytest.raises(PortError) as excinfo:
        run(guard.resolve(target))
    assert excinfo.value.code is AgentErrorCode.TIMEOUT


# --- Yönlendirme koruması --------------------------------------------------------


def test_redirect_to_metadata_ip_blocked_at_second_hop() -> None:
    """Yönlendirme hedefi metadata adresi: her adım yeniden doğrulanır, engellenir."""
    responses = {
        "/rebind": MockResponse.redirect("http://169.254.169.254/latest/meta-data/"),
    }

    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers.update(responses)
            settings = make_settings(server)
            guard = UrlGuard.from_settings(settings)
            fetcher = HttpFetcher(settings, guard)
            try:
                await fetcher.fetch(server.url("/rebind"))
            except PortError as error:
                return error
            raise AssertionError("yönlendirme engellenmeliydi")

    error = run(scenario())
    assert error.code is AgentErrorCode.VALIDATION_ERROR
    assert "yasak adres" in error.message
    assert "169.254.169.254" in error.message


def test_redirect_rebinding_via_dns_blocked() -> None:
    """Anahtar adı sonradan özel adrese çözümlenirse: adım başına çözümleme engeller."""

    async def scenario() -> PortError:
        async with MockWebServer() as server:
            server.handlers["/hop"] = MockResponse.redirect("http://rebind.example/next")
            settings = make_settings(server)
            guard = UrlGuard.from_settings(settings, resolver=mapping_resolver({"rebind.example": ["169.254.169.254"]}))
            fetcher = HttpFetcher(settings, guard)
            try:
                await fetcher.fetch(server.url("/hop"))
            except PortError as error:
                return error
            raise AssertionError("DNS rebinding engellenmeliydi")

    error = run(scenario())
    assert error.code is AgentErrorCode.VALIDATION_ERROR


def test_resolved_ip_pinned_and_host_header_preserved() -> None:
    """Çözümlenen IP'ye bağlanılır, Host başlığı anahtar adını korur (pin kanıtı)."""

    async def scenario() -> tuple[str, str, int]:
        async with MockWebServer() as server:
            server.handlers["/"] = MockResponse.html(html_page("<p>pin</p>"))
            settings = make_settings(server)
            guard = UrlGuard.from_settings(settings, resolver=mapping_resolver({"pinned.example": ["127.0.0.1"]}))
            fetcher = HttpFetcher(settings, guard)
            url = f"http://pinned.example:{server.port}/"
            content = await fetcher.fetch(url)
            return content.final_url, server.requests[0].headers["host"], server.port

    final_url, host_header, port = run(scenario())
    assert final_url == f"http://pinned.example:{port}/"
    assert host_header == f"pinned.example:{port}"  # Host anahtar adını korur; bağlantı çözümlenen IP'ye gitti
