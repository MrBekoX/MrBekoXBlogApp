"""Offline credential-origin regressions: every HTTP response is injected."""

import asyncio

import pytest

from agent_core.errors import AgentErrorCode, PortError
from agent_core.web.fetch import HttpFetcher
from agent_core.web.settings import WebToolSettings
from agent_core.web.ssrf import UrlGuard


def fetcher_with_responses(monkeypatch, locations):
    settings = WebToolSettings(environment="production")

    async def no_network(_host):
        raise AssertionError("Offline redirect tests must not resolve DNS")

    fetcher = HttpFetcher(settings, UrlGuard.from_settings(settings, resolver=no_network))
    requests = []

    async def single_request(target, *, cancel=None, extra_headers=None):
        requests.append((target.url, dict(extra_headers or {})))
        index = len(requests) - 1
        if index < len(locations):
            return 302, {"location": locations[index]}, b""
        return 200, {"content-type": "application/json"}, b'{"results": []}'

    monkeypatch.setattr(fetcher, "_single_request", single_request)
    return fetcher, requests


@pytest.mark.parametrize("location", [
    "https://other.example/results",
    "//other.example/results",
    "http://search.example/results",
    "https://search.example:80/results",
])
def test_credentials_never_reach_a_redirected_origin(monkeypatch, location):
    fetcher, requests = fetcher_with_responses(monkeypatch, [location])
    credential = "Bearer test-only-not-a-secret"
    with pytest.raises(PortError) as raised:
        asyncio.run(fetcher.fetch("https://search.example/api", extra_headers={"Authorization": credential}))
    assert raised.value.code is AgentErrorCode.VALIDATION_ERROR
    assert credential not in str(raised.value)
    assert requests == [("https://search.example/api", {"Authorization": credential})]


@pytest.mark.parametrize("location", ["/results", "https://SEARCH.example:443/results"])
def test_same_origin_https_redirect_keeps_authentication(monkeypatch, location):
    fetcher, requests = fetcher_with_responses(monkeypatch, [location])
    headers = {"Authorization": "Bearer test-only-not-a-secret"}
    result = asyncio.run(fetcher.fetch("https://search.example/api", extra_headers=headers))
    assert result.status_code == 200 and result.redirect_count == 1
    assert len(requests) == 2
    assert all(sent_headers == headers for _url, sent_headers in requests)


def test_each_hop_is_checked_after_a_permitted_same_origin_redirect(monkeypatch):
    fetcher, requests = fetcher_with_responses(monkeypatch, ["/intermediate", "https://other.example/collect"])
    with pytest.raises(PortError):
        asyncio.run(fetcher.fetch("https://search.example/api", extra_headers={"X-Api-Key": "test-only"}))
    assert [url for url, _headers in requests] == [
        "https://search.example/api", "https://search.example/intermediate",
    ]


def test_ordinary_source_reads_can_still_follow_public_cross_origin_redirects(monkeypatch):
    fetcher, requests = fetcher_with_responses(monkeypatch, ["https://other.example/article"])
    result = asyncio.run(fetcher.fetch("https://search.example/link"))
    assert result.final_url == "https://other.example/article"
    assert len(requests) == 2
    assert all(not headers for _url, headers in requests)
