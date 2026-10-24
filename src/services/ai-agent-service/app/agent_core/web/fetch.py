"""Sınırlı asyncio HTTP/1.1 getirme motoru (plan A6).

Standart kütüphane ``asyncio`` akışlarıyla yazılmıştır; harici HTTP istemci
bağımlılığı eklenmez. Sınırlar plan A6 gereğidir: süre (bağlan/üstbilgi/gövde/
toplam), yönlendirme sayısı, yanıt boyutu (sıkıştırılmış çıktı dahil) ve
içerik türü. Her yönlendirme adımı ``UrlGuard``'tan yeniden geçer; bağlantı
doğrulanmış IP'ye pinlenir (bkz. ``ssrf.py``).

Hata eşlemesi (SourceReader portu ile hizalı):
- şema/port/kontrol karakteri/adres engeli → ``validation_error``
- DNS çözülemedi, 404/410, boş gövde taşınamayan kaynak → ``not_found``
- 401/403 (erişim engeli), 5xx dışı 4xx, boyut/tür aşımı → ``provider_error``
- 429 (oran sınırı), 5xx, bağlantı arızası, zaman aşımı → ``retryable=True``
- ``CancelledError`` bastırılmaz [PY-ASYNCIO#C2]; bağlantı temizlenir.
"""

from __future__ import annotations

import asyncio
import ssl
import time
import zlib
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urljoin

from ..budget.policy import Deadline
from ..errors import AgentErrorCode, PortError
from ..ports import CancellationToken
from .models import FetchedContent
from .settings import WebToolSettings
from .ssrf import IPAddress, ParsedTarget, UrlGuard

__all__ = ["HttpFetcher"]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECT_HEADER_VALUE = 2048


class HttpFetcher:
    """Sınırlı GET istemcisi; SSRF koruması için ``UrlGuard`` ile çalışır."""

    def __init__(
        self,
        settings: WebToolSettings,
        guard: UrlGuard,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._guard = guard
        self._clock = clock or time.monotonic

    def parse_url(self, url: str) -> ParsedTarget:
        """URL'yi şema/port/adres sözleşmesine göre doğrular (ağ GİTMEZ).

        Araç katmanı rezervasyondan ÖNCE bunu çağırır: geçersiz şema/adres
        dış çağrı başlamadan reddedilir ve bütçe olayı üretmez.
        """
        return self._guard.parse(url)

    async def fetch(
        self,
        url: str,
        *,
        cancel: CancellationToken | None = None,
        deadline: Deadline | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> FetchedContent:
        """URL'yi sınırlar içinde GET eder; yönlendirmeleri izler.

        ``extra_headers`` yalnız operatör yapılandırmasından gelir (ör. arama
        sağlayıcı anahtarı) ve asla günlüğe yazılmaz; kontrol karakteri
        taşıyan başlık reddedilir.

        Raises:
            PortError: yukarıdaki eşleme; ``cancelled``/``timeout`` dahil.
            asyncio.CancelledError: dış iptal; bağlantılar kapatılır, istisna
                bastırılmadan yükselir.
        """
        if extra_headers:
            for name, value in extra_headers.items():
                if any(ord(ch) < 0x20 or ch == "\x7f" for ch in f"{name}{value}"):
                    raise PortError(
                        AgentErrorCode.VALIDATION_ERROR,
                        f"başlık kontrol karakteri taşıyor: {name}",
                        port="HttpFetcher",
                    )
        if cancel is not None:
            cancel.raise_if_cancelled()
        started = self._clock()
        try:
            async with asyncio.timeout(self._settings.total_timeout_s):
                return await self._fetch(url, cancel=cancel, deadline=deadline, extra_headers=extra_headers)
        except TimeoutError:
            elapsed = self._clock() - started
            raise PortError(
                AgentErrorCode.TIMEOUT,
                f"getirme zaman aşımı (süre sınırı aşıldı, geçen {elapsed:.3f}s): {url}",
                port="HttpFetcher",
                retryable=True,
            ) from None

    async def _fetch(
        self,
        url: str,
        *,
        cancel: CancellationToken | None,
        deadline: Deadline | None,
        extra_headers: dict[str, str] | None = None,
    ) -> FetchedContent:
        requested = url
        current = url
        redirects = 0
        while True:
            if cancel is not None:
                cancel.raise_if_cancelled()
            if deadline is not None:
                deadline.raise_if_exceeded()
            target = self._guard.parse(current)
            status, headers, body = await self._single_request(
                target, cancel=cancel, extra_headers=extra_headers
            )
            if status in _REDIRECT_STATUSES:
                location = headers.get("location")
                if not location:
                    raise PortError(
                        AgentErrorCode.PROVIDER_ERROR,
                        f"yönlendirme hedefi yok (HTTP {status}): {current}",
                        port="HttpFetcher",
                    )
                if len(location) > _MAX_REDIRECT_HEADER_VALUE:
                    raise PortError(
                        AgentErrorCode.PROVIDER_ERROR,
                        "yönlendirme hedefi çok uzun",
                        port="HttpFetcher",
                    )
                if redirects >= self._settings.max_redirects:
                    raise PortError(
                        AgentErrorCode.PROVIDER_ERROR,
                        f"yönlendirme sınırı aşıldı ({self._settings.max_redirects}): {current}",
                        port="HttpFetcher",
                    )
                # Operator headers can contain a search credential. Public IP
                # validation alone does not authorize sharing it with another
                # origin (including an HTTPS-to-HTTP downgrade).
                redirect_url = urljoin(target.url, location.strip())
                if extra_headers:
                    redirect_target = self._guard.parse(redirect_url)
                    if (redirect_target.scheme, redirect_target.host, redirect_target.port) != (
                        target.scheme, target.host, target.port
                    ):
                        raise PortError(
                            AgentErrorCode.VALIDATION_ERROR,
                            "Authenticated requests cannot follow a redirect to another origin",
                            port="HttpFetcher",
                        )
                # Every permitted hop still passes parse, DNS and address checks.
                current = redirect_url
                redirects += 1
                continue
            return FetchedContent(
                requested_url=requested,
                final_url=current,
                status_code=status,
                content_type=headers.get("content-type"),
                body=body,
                fetched_at=datetime.now(timezone.utc),
                redirect_count=redirects,
            )

    # --- Tek istek -------------------------------------------------------

    async def _single_request(
        self,
        target: ParsedTarget,
        *,
        cancel: CancellationToken | None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        addresses = await self._guard.resolve(target)
        last_error: OSError | None = None
        for ip in addresses[:4]:
            try:
                return await self._request_once(target, ip, cancel=cancel, extra_headers=extra_headers)
            except PortError:
                raise  # protokol/içerik hatası adres değiştirmez
            except TimeoutError:
                raise  # faz zaman aşımı: TIMEOUT olarak raporlanır (TimeoutError, OSError alt sınıfıdır)
            except (OSError, ConnectionError) as error:
                last_error = error  # bu IP yarım yanıt verdi: sıradakini dene
        raise PortError(
            AgentErrorCode.PROVIDER_ERROR,
            f"bağlanılamadı: {target.host} ({last_error.__class__.__name__})",
            port="HttpFetcher",
            retryable=True,
        )

    async def _request_once(
        self,
        target: ParsedTarget,
        ip: IPAddress,
        *,
        cancel: CancellationToken | None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        reader, writer = await self._connect(target, ip)
        try:
            request = self._build_request(target, extra_headers)
            writer.write(request)
            await asyncio.wait_for(writer.drain(), timeout=self._settings.header_timeout_s)
            status_line, headers = await self._read_headers(reader)
            # 1xx ara yanıtları atla.
            while 100 <= status_line[1] < 200:
                status_line, headers = await self._read_headers(reader)
            status = status_line[1]
            self._check_status(status)  # hata durumları gövde okumadan raporlanır
            if status < 200 or status >= 300:
                return status, headers, b""  # yönlendirme: gövde ilgi dışı
            self._check_content_type(headers)
            body = await self._read_body(reader, status, headers, cancel=cancel)
            return status, headers, body
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
            except (OSError, ConnectionError, TimeoutError, asyncio.CancelledError):
                pass  # orijinal sonuç/istisna korunur; soket kapatıldı

    async def _connect(
        self, target: ParsedTarget, ip: IPAddress
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if target.is_tls:
            context = ssl.create_default_context()
            return await asyncio.wait_for(
                asyncio.open_connection(
                    str(ip),
                    target.port,
                    ssl=context,
                    server_hostname=target.host,
                ),
                timeout=self._settings.connect_timeout_s,
            )
        return await asyncio.wait_for(
            asyncio.open_connection(str(ip), target.port),
            timeout=self._settings.connect_timeout_s,
        )

    def _build_request(self, target: ParsedTarget, extra_headers: dict[str, str] | None = None) -> bytes:
        default_port = 443 if target.is_tls else 80
        host_header = target.host_header if target.port == default_port else f"{target.host_header}:{target.port}"
        lines = [
            f"GET {target.path_with_query} HTTP/1.1",
            f"Host: {host_header}",
            f"User-Agent: {self._settings.user_agent}",
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,"
            "text/plain;q=0.8,application/json;q=0.9,*/*;q=0.5",
            "Accept-Encoding: gzip, deflate",
            "Connection: close",
        ]
        for name, value in (extra_headers or {}).items():
            lines.append(f"{name}: {value}")
        return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")

    async def _read_headers(self, reader: asyncio.StreamReader) -> tuple[tuple[str, int], dict[str, str]]:
        try:
            raw = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"),
                timeout=self._settings.header_timeout_s,
            )
        except asyncio.IncompleteReadError:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "bağlantı yanıt üstbilgisi tamamlanmadan kapandı",
                port="HttpFetcher",
                retryable=True,
            ) from None
        except asyncio.LimitOverrunError:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"yanıt üstbilgisi sınırı aşıldı ({self._settings.max_header_bytes} bayt)",
                port="HttpFetcher",
            ) from None
        if len(raw) > self._settings.max_header_bytes:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"yanıt üstbilgisi sınırı aşıldı ({self._settings.max_header_bytes} bayt)",
                port="HttpFetcher",
            )
        try:
            head = raw.decode("latin-1")
        except UnicodeDecodeError:  # pragma: no cover - latin-1 her baytı alır
            raise PortError(AgentErrorCode.PROVIDER_ERROR, "üstbilgi çözümlenemedi", port="HttpFetcher") from None
        lines = head.split("\r\n")
        parts = lines[0].split(" ", 2)
        if len(parts) < 2 or not parts[0].startswith("HTTP/"):
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"geçersiz yanıt satırı: {lines[0][:60]!r}",
                port="HttpFetcher",
                retryable=True,
            )
        try:
            status = int(parts[1])
        except ValueError:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"geçersiz durum kodu: {parts[1]!r}",
                port="HttpFetcher",
                retryable=True,
            ) from None
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        return (parts[0].strip(), status), headers

    async def _read_body(
        self,
        reader: asyncio.StreamReader,
        status: int,
        headers: dict[str, str],
        *,
        cancel: CancellationToken | None,
    ) -> bytes:
        cap = self._settings.max_response_bytes
        transfer = headers.get("transfer-encoding", "").lower()
        content_length = headers.get("content-length")
        if content_length is not None and "chunked" not in transfer:
            try:
                length = int(content_length)
            except ValueError:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    f"geçersiz Content-Length: {content_length!r}",
                    port="HttpFetcher",
                ) from None
            if length > cap:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    f"yanıt boyutu sınırı aşıldı: Content-Length {length} > {cap}",
                    port="HttpFetcher",
                )
            chunks: list[bytes] = []
            received = 0
            while received < length:
                if cancel is not None:
                    cancel.raise_if_cancelled()
                piece = await asyncio.wait_for(
                    reader.read(min(65536, length - received)),
                    timeout=self._settings.body_idle_timeout_s,
                )
                if not piece:
                    raise PortError(
                        AgentErrorCode.PROVIDER_ERROR,
                        f"yanıt gövdesi Content-Length'ten kısa kesildi ({received}/{length})",
                        port="HttpFetcher",
                        retryable=True,
                    )
                chunks.append(piece)
                received += len(piece)
            body = b"".join(chunks)
        elif "chunked" in transfer:
            body = await self._read_chunked(reader, cap, cancel=cancel)
        else:
            body = await self._read_until_eof(reader, cap, cancel=cancel)
        return self._maybe_decompress(body, headers.get("content-encoding", "").lower().strip(), cap)

    async def _read_chunked(
        self,
        reader: asyncio.StreamReader,
        cap: int,
        *,
        cancel: CancellationToken | None,
    ) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            if cancel is not None:
                cancel.raise_if_cancelled()
            size_line = await asyncio.wait_for(reader.readline(), timeout=self._settings.body_idle_timeout_s)
            if not size_line:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    "chunked yanıt beklenmedik biçimde kapandı",
                    port="HttpFetcher",
                    retryable=True,
                )
            try:
                size = int(size_line.split(b";", 1)[0].strip() or b"0", 16)
            except ValueError:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    "geçersiz chunk boyutu",
                    port="HttpFetcher",
                ) from None
            if size == 0:
                await asyncio.wait_for(
                    reader.readline(), timeout=self._settings.body_idle_timeout_s
                )  # son fragman satırı (varsa)
                break
            total += size
            if total > cap:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    f"yanıt boyutu sınırı aşıldı: chunked toplam > {cap}",
                    port="HttpFetcher",
                )
            try:
                chunk = await asyncio.wait_for(
                    reader.readexactly(size + 2),  # veri + CRLF
                    timeout=self._settings.body_idle_timeout_s,
                )
            except asyncio.IncompleteReadError as error:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    "chunked yanıt tamamlanmadan bağlantı kapandı",
                    port="HttpFetcher",
                    retryable=True,
                ) from None
            chunks.append(chunk[:size])
        return b"".join(chunks)

    async def _read_until_eof(
        self,
        reader: asyncio.StreamReader,
        cap: int,
        *,
        cancel: CancellationToken | None,
    ) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            if cancel is not None:
                cancel.raise_if_cancelled()
            piece = await asyncio.wait_for(
                reader.read(65536),
                timeout=self._settings.body_idle_timeout_s,
            )
            if not piece:
                break
            total += len(piece)
            if total > cap:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    f"yanıt boyutu sınırı aşıldı ({cap} bayt)",
                    port="HttpFetcher",
                )
            chunks.append(piece)
        return b"".join(chunks)

    def _maybe_decompress(self, body: bytes, encoding: str, cap: int) -> bytes:
        if encoding in ("", "identity"):
            return body
        if encoding not in ("gzip", "x-gzip", "deflate"):
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"desteklenmeyen içerik kodlaması: {encoding}",
                port="HttpFetcher",
            )
        if encoding == "gzip":
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        else:
            decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        out: list[bytes] = []
        produced = 0
        for start in range(0, len(body), 65536):
            piece = decompressor.decompress(body[start : start + 65536], cap - produced + 1)
            produced += len(piece)
            if produced > cap:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    f"sıkıştırılmış yanıt sınırı aşıldı ({cap} bayt)",
                    port="HttpFetcher",
                )
            out.append(piece)
        return b"".join(out)

    def _check_status(self, status: int) -> None:
        if 200 <= status < 400:
            return  # 3xx yönlendirmesi _fetch'te işlenir
        if status in (401, 403):
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"erişim engellendi (HTTP {status}): kaynak kimlik doğrulama/erişim politikası "
                "tarafından reddedildi; engel raporlanır, tekrar denenmez",
                port="HttpFetcher",
            )
        if status == 429:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "oran sınırı (HTTP 429): sağlayıcı istek hızını aştı; sınırlı geri çekilmeyle tekrar denenebilir",
                port="HttpFetcher",
                retryable=True,
            )
        if status in (404, 410):
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"kaynak bulunamadı veya kaldırıldı (HTTP {status})",
                port="HttpFetcher",
            )
        if 400 <= status < 500:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"kaynak isteği reddedildi (HTTP {status})",
                port="HttpFetcher",
            )
        raise PortError(
            AgentErrorCode.PROVIDER_ERROR,
            f"sağlayıcı arızası (HTTP {status}); sınırlı tekrar denenebilir",
            port="HttpFetcher",
            retryable=True,
        )

    def _check_content_type(self, headers: dict[str, str]) -> None:
        content_type = headers.get("content-type")
        if not content_type:
            return  # tür bildirilmedi: çıkarıcı davranışı belirler
        media = content_type.split(";", 1)[0].strip().lower()
        if not media:
            return
        if any(media.startswith(prefix) for prefix in self._settings.allowed_content_types):
            return
        raise PortError(
            AgentErrorCode.PROVIDER_ERROR,
            f"desteklenmeyen içerik türü: {media} — metin çıkarma yapılmaz",
            port="HttpFetcher",
        )
