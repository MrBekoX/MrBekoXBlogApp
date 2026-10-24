"""A6 web test yardımcıları: localhost mock HTTP sunucusu ve ortak kurulum.

L005: bu dizin ``__init__.py``'li pakettir; conftest.py AÇILMAZ, yardımcılar
benzersiz adlı bu modülde yaşar. Async testler pytest-asyncio gerektirmeden
``run()`` ile çağrılır (root conftest kuralı).

Mock sunucu yalnız 127.0.0.1'e bağlanır; test ortamı ayarları
(``environment="test", allow_loopback=True``) olmadan ona erişilemez — bu
aynı zamanda SSRF korumasının testte bile granüler çalıştığının kanıtıdır.
"""

from __future__ import annotations

import asyncio
import gzip as gzip_module
import zlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent_core.budget import PolicyBudgetStore
from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import BudgetKind, CancellationToken, WebSearchResult
from agent_core.web import TextExtractor, UrlGuard, WebToolSettings
from agent_core.web.fetch import HttpFetcher
from agent_core.web.tools import ReadSourceTool

# --- Async koşu ------------------------------------------------------------


def run(coroutine):
    """Coroutine'i senkron test içinde çalıştırır."""
    return asyncio.run(coroutine)


# --- Mock HTTP sunucusu -----------------------------------------------------


@dataclass
class MockRequest:
    method: str
    target: str
    path: str
    query: str
    headers: dict[str, str]
    body: bytes


@dataclass
class MockResponse:
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    reason: str | None = None

    @staticmethod
    def html(body: str, status: int = 200, headers: dict[str, str] | None = None) -> "MockResponse":
        merged = {"Content-Type": "text/html; charset=utf-8"}
        merged.update(headers or {})
        return MockResponse(status=status, headers=merged, body=body.encode("utf-8"))

    @staticmethod
    def json_text(payload: str, status: int = 200) -> "MockResponse":
        return MockResponse(status=status, headers={"Content-Type": "application/json"}, body=payload.encode("utf-8"))

    @staticmethod
    def gzip_html(body: str) -> "MockResponse":
        raw = gzip_module.compress(body.encode("utf-8"))
        return MockResponse(
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8", "Content-Encoding": "gzip"},
            body=raw,
        )

    @staticmethod
    def deflate_html(body: str) -> "MockResponse":
        compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -zlib.MAX_WBITS)
        raw = compressor.compress(body.encode("utf-8")) + compressor.flush()
        return MockResponse(
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8", "Content-Encoding": "deflate"},
            body=raw,
        )

    @staticmethod
    def redirect(location: str, status: int = 302) -> "MockResponse":
        return MockResponse(status=status, headers={"Location": location}, body=b"")


class _DelayedResponse:
    """Belirtilen süre bekleyip yanıt verir (zaman aşımı senaryosu)."""

    def __init__(self, seconds: float, response: MockResponse | None = None) -> None:
        self.seconds = seconds
        self.response = response or MockResponse.html("<html><body>slow</body></html>")


class _RawResponse:
    """Ham byte'ları olduğu gibi yazar (chunked/bozuk çerçeve senaryoları)."""

    def __init__(self, raw: bytes) -> None:
        self.raw = raw


class MockWebServer:
    """Yol → yanıt eşlemeli minimal asyncio HTTP/1.1 sunucusu.

    Handler değerleri: ``MockResponse``, ``_DelayedResponse``, ``_RawResponse``,
    ``Exception`` veya ``Callable[[MockRequest], MockResponse | Awaitable[MockResponse]]``.
    Gelen istekler ``requests`` listesine kaydedilir (Host başlığı ve sır
    sızıntısı denetimleri için).
    """

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.requests: list[MockRequest] = []
        self._server: asyncio.AbstractServer | None = None
        self.port: int = 0

    async def start(self) -> "MockWebServer":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def __aenter__(self) -> "MockWebServer":
        return await self.start()

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    @property
    def allowed_ports(self) -> tuple[int, ...]:
        return (80, 443, self.port)

    def requests_to(self, path: str) -> list[MockRequest]:
        return [r for r in self.requests if r.path == path]

    # -- sunucu döngüsü ---------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await self._read_request(reader)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.LimitOverrunError):
            writer.close()
            return
        response = await self._dispatch(request)
        try:
            if isinstance(response, _RawResponse):
                writer.write(response.raw)
                await writer.drain()
            else:
                await self._write_response(writer, response)
        except (ConnectionError, BrokenPipeError):  # istemci erken kapattı
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _read_request(self, reader: asyncio.StreamReader) -> MockRequest:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        method, target, _ = request_line.decode("latin-1").strip().split(" ", 2)
        headers: dict[str, str] = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        body = b""
        length = headers.get("content-length")
        if length and length.isdigit():
            body = await asyncio.wait_for(reader.readexactly(int(length)), timeout=5.0)
        path, _, query = target.partition("?")
        return MockRequest(method=method, target=target, path=path, query=query, headers=headers, body=body)

    async def _dispatch(self, request: MockRequest):
        self.requests.append(request)
        handler = self.handlers.get(request.path)
        if handler is None:
            return MockResponse(status=404, headers={"Content-Type": "text/plain"}, body=b"not found")
        if isinstance(handler, Exception):
            return handler
        if isinstance(handler, _DelayedResponse):
            await asyncio.sleep(handler.seconds)
            return handler.response
        if isinstance(handler, _RawResponse):
            return handler
        if callable(handler):
            result = handler(request)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        return handler  # MockResponse

    @staticmethod
    async def _write_response(writer: asyncio.StreamWriter, response: MockResponse) -> None:
        reason = response.reason or _REASONS.get(response.status, "Unknown")
        head_lines = [f"HTTP/1.1 {response.status} {reason}"]
        headers = dict(response.headers)
        headers.setdefault("Content-Length", str(len(response.body)))
        headers.setdefault("Connection", "close")
        for name, value in headers.items():
            head_lines.append(f"{name}: {value}")
        head = ("\r\n".join(head_lines) + "\r\n\r\n").encode("latin-1")
        writer.write(head + response.body)
        await writer.drain()


_REASONS = {200: "OK", 301: "Moved Permanently", 302: "Found", 403: "Forbidden", 404: "Not Found", 500: "Internal Server Error", 503: "Service Unavailable"}


def raw_chunked_response(chunks: list[bytes]) -> _RawResponse:
    """Geçerli chunked yanıt üretir (Transfer-Encoding: chunked)."""
    head = b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nTransfer-Encoding: chunked\r\n\r\n"
    body = b""
    for chunk in chunks:
        body += f"{len(chunk):x}".encode("ascii") + b"\r\n" + chunk + b"\r\n"
    body += b"0\r\n\r\n"
    return _RawResponse(head + body)


# --- HTML kalıpları ----------------------------------------------------------


def html_page(
    body: str,
    *,
    title: str = "Örnek Sayfa",
    meta: str = "",
) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<title>{title}</title>{meta}</head><body>{body}</body></html>"
    )


# --- Ayar ve koruyucu kurulum --------------------------------------------------


def make_settings(server: MockWebServer | None = None, **overrides) -> WebToolSettings:
    defaults: dict = dict(
        environment="test",
        allow_loopback=server is not None,
        connect_timeout_s=2.0,
        header_timeout_s=2.0,
        body_idle_timeout_s=3.0,
        resolver_timeout_s=2.0,
        total_timeout_s=6.0,
        retry_backoff_base_s=0.0,
    )
    if server is not None:
        defaults["allowed_ports"] = server.allowed_ports
    defaults.update(overrides)
    return WebToolSettings(**defaults)


def make_guard(settings: WebToolSettings, resolver: Callable[[str], Awaitable[Sequence[str]]] | None = None) -> UrlGuard:
    return UrlGuard.from_settings(settings, resolver=resolver)


def make_read_tool(settings: WebToolSettings, store: PolicyBudgetStore | None = None) -> tuple[ReadSourceTool, BudgetGuard]:
    """Kayıt aracını bellek içi bütçe deposuyla kurar (araç döner, koruyucu döner)."""
    budget_store = store or PolicyBudgetStore(BudgetPolicy(max_attempts_per_action=2, max_duration_seconds=60))
    guard = BudgetGuard(budget_store, BudgetPolicy(max_attempts_per_action=2, max_duration_seconds=60), "run-web-test")
    fetcher = HttpFetcher(settings, UrlGuard.from_settings(settings))
    return ReadSourceTool(guard, fetcher, TextExtractor(settings), settings=settings), guard
