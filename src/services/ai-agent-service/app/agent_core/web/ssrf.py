"""SSRF koruması: URL doğrulama, DNS çözümleme ve adres engeli (plan A6).

Plan: "DNS çözümleme ve yönlendirmeler dahil özel, loopback, link-local ve
metadata adreslerini engelle." Uygulama stratejisi TOCTOU'ya kapalıdır:

1. URL ayrıştırılır: yalnız http/https, userinfo yok, bağlantı noktası
   izin listesinde, kontrol karakteri yok.
2. Anahtar adı çözümlenir (literal IP ise DNS atlanır) ve dönen HER adres
   engel listesinden geçirilir; engelli bir adres varsa bağlantı kurulmaz.
3. Bağlantı doğrulanmış IP'ye PİNLENİR (yeniden çözümleme yapılmaz) —
   çözümleme ile bağlantı arasında DNS değişse bile engelli adrese
   gidilemez. Yönlendirmeler her adımda bu üç adımı TEKRARLAR (yeniden
   çözümlü redirect koruması).

Engel listesi loopback/private/link-local/metadata'nın (169.254.169.254
dahil) yanına IPv4-eşlenmiş IPv6 (``::ffff:127.0.0.1`` gibi), NAT64
(``64:ff9b::/96``), CGNAT, benchmark ve belge aralıklarını da sarar.

``allow_loopback=True`` yalnız ``environment="test"`` için geçerlidir
(localhost mock sunucu); üretimde ``config_error`` ile reddedilir. Bayrak
yalnız loopback'i açar: özel ağlar, link-local ve metadata adresi testte
bile engelli kalır.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from urllib.parse import urlsplit

from ..errors import AgentErrorCode, PortError
from .settings import WebToolSettings

__all__ = ["IPAddress", "ParsedTarget", "Resolver", "UrlGuard"]

IPAddress = IPv4Address | IPv6Address

#: Anahtar adını adres listesine çözümleyen eşzamansız fonksiyon (test enjeksiyonu için).
Resolver = Callable[[str], Awaitable[Sequence[str]]]

#: Engellenen ek IPv4 aralıkları: CGNAT, benchmark, TEST-NET belge aralıkları.
_EXTRA_BLOCKED_V4 = (
    ip_network("100.64.0.0/10"),  # CGNAT / carrier-grade NAT
    ip_network("198.18.0.0/15"),  # benchmark
    ip_network("192.0.2.0/24"),  # TEST-NET-1
    ip_network("198.51.100.0/24"),  # TEST-NET-2
    ip_network("203.0.113.0/24"),  # TEST-NET-3
)

#: Engellenen ek IPv6 aralıkları: belge aralığı.
_EXTRA_BLOCKED_V6 = (
    ip_network("2001:db8::/32"),  # belge aralığı
)

#: NAT64 önekinden eşlenen IPv4'ün engel denetimine sokulması.
_NAT64_PREFIX = ip_network("64:ff9b::/96")


@dataclass(frozen=True)
class ParsedTarget:
    """Doğrulanmış tek hedef: bağlantı için gerekli alanlar.

    ``host`` DNS/SNI/IDNA için ASCII biçimdir; ``host_header`` HTTP/Host ve
    URL gösterimi içindir (IPv6 köşeli parantezli: ``[::1]``).
    """

    url: str
    scheme: str
    host: str
    host_header: str
    port: int
    path_with_query: str
    is_tls: bool
    literal_ip: IPAddress | None


def _unwrap_ipv4(ip: IPAddress) -> IPAddress:
    """IPv4-eşlenmiş ve NAT64 sarılı IPv6 adreslerini IPv4'e açar."""
    if isinstance(ip, IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return mapped
        if ip in _NAT64_PREFIX:
            return IPv4Address(ip.packed[-4:])
    return ip


def _is_blocked(ip: IPAddress, *, allow_loopback: bool) -> bool:
    """Adres engel listesi: özel/loopback/link-local/metadata + ek aralıklar.

    ``allow_loopback`` yalnız loopback'i (127.0.0.0/8, ::1) serbest bırakır;
    private/link-local/metadata test ortamında bile engelli kalır.
    """
    if ip.is_loopback:
        return not allow_loopback
    if allow_loopback:
        pass  # loopback dışı aralıklar normal engel akışına devam eder
    checks = (
        ip.is_unspecified,
        ip.is_private,
        ip.is_link_local,  # 169.254.0.0/16 — metadata 169.254.169.254 dahil
        ip.is_multicast,
        ip.is_reserved,
    )
    if any(checks):
        return True
    extra = _EXTRA_BLOCKED_V4 if isinstance(ip, IPv4Address) else _EXTRA_BLOCKED_V6
    return any(ip in network for network in extra)


async def _system_resolver(host: str) -> list[str]:
    """Varsayılan çözümleyici: ``loop.getaddrinfo``; sonuçları tekilleştirir."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.append(addr)
    return seen


class UrlGuard:
    """URL doğrulama + çözümleme + adres engeli; fetch motorunun tek girişi."""

    def __init__(
        self,
        settings: WebToolSettings,
        *,
        resolver: Resolver | None = None,
    ) -> None:
        self._settings = settings
        self._resolver: Resolver = resolver or _system_resolver

    @classmethod
    def from_settings(
        cls,
        settings: WebToolSettings,
        *,
        resolver: Resolver | None = None,
    ) -> "UrlGuard":
        """Ayarlardan koruyucu kurar; test bayrağı üretimde reddedilir.

        Raises:
            PortError: ``config_error`` — ``allow_loopback`` yalnız
                ``environment="test"`` iken kullanılabilir.
        """
        if settings.allow_loopback and settings.environment != "test":
            raise PortError(
                AgentErrorCode.CONFIG_ERROR,
                "allow_loopback yalnız environment='test' iken kullanılabilir; "
                f"environment='{settings.environment}' için loopback erişimi reddedildi. "
                "Loopback dahil özel adresler SSRF engeline takılır.",
                port="UrlGuard",
            )
        return cls(settings, resolver=resolver)

    def parse(self, url: str) -> ParsedTarget:
        """URL'yi şema/host/port/kontrol karakteri açısından doğrular.

        Raises:
            PortError: ``validation_error`` — desteklenmeyen şema, userinfo,
                izin dışı port, boş/karışık anahtar adı, kontrol karakteri.
        """
        if not isinstance(url, str) or not url.strip():
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "URL boş olamaz",
                port="UrlGuard",
            )
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"desteklenmeyen adres şeması: '{scheme or '(yok)'}' — yalnız http/https okunur",
                port="UrlGuard",
            )
        if "@" in parts.netloc:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "URL userinfo taşımaz (kullanıcı:parola@host reddedilir)",
                port="UrlGuard",
            )
        raw_host = parts.hostname
        if not raw_host:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "URL anahtar adı (host) yok",
                port="UrlGuard",
            )
        try:
            host = raw_host.rstrip(".").encode("idna").decode("ascii").lower()
        except (UnicodeError, ValueError) as error:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"anahtar adı IDNA olarak kodlanamadı: {error}",
                port="UrlGuard",
            ) from None

        literal_ip: IPAddress | None
        try:
            parsed_ip = ip_address(host)
        except ValueError:
            literal_ip = None
        else:
            literal_ip = parsed_ip  # type: ignore[assignment]
            if _is_blocked(_unwrap_ipv4(parsed_ip), allow_loopback=self._settings.allow_loopback):
                raise PortError(
                    AgentErrorCode.VALIDATION_ERROR,
                    f"yasak adres engellendi: {parsed_ip} (özel/loopback/link-local/metadata)",
                    port="UrlGuard",
                )

        default_port = 443 if scheme == "https" else 80
        try:
            port = parts.port if parts.port is not None else default_port
        except ValueError:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "URL bağlantı noktası geçersiz",
                port="UrlGuard",
            ) from None
        if port not in self._settings.allowed_ports:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"bağlantı noktası izinli değil: {port} (izinli: "
                f"{', '.join(map(str, self._settings.allowed_ports))})",
                port="UrlGuard",
            )

        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        if any(ord(ch) < 0x20 or ch == "\x7f" for ch in path):
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "URL yolu kontrol karakteri taşıyor",
                port="UrlGuard",
            )

        host_header = f"[{host}]" if ":" in host else host
        normalized = f"{scheme}://{host_header}" + (f":{port}" if port != default_port else "") + path
        return ParsedTarget(
            url=normalized,
            scheme=scheme,
            host=host,
            host_header=host_header,
            port=port,
            path_with_query=path,
            is_tls=scheme == "https",
            literal_ip=literal_ip,
        )

    async def resolve(self, target: ParsedTarget) -> list[IPAddress]:
        """Anahtar adını çözümler ve TÜM adresleri engel listesinden geçirir.

        Literal IP hedeflerde DNS atlanır. En az bir genel adres döner; hepsi
        engelliyse istisna yükselir ve bağlantı hiç denenmez.

        Raises:
            PortError: ``not_found`` — çözümleme başarısız (anahtar adı yok);
                ``timeout`` — çözümleme süresi doldu; ``validation_error`` —
                tüm adresler özel/loopback/link-local/metadata.
        """
        if target.literal_ip is not None:
            return [target.literal_ip]
        try:
            addresses = await asyncio.wait_for(
                self._resolver(target.host),
                timeout=self._settings.resolver_timeout_s,
            )
        except TimeoutError:
            raise PortError(
                AgentErrorCode.TIMEOUT,
                f"DNS çözümleme zaman aşımı: {target.host}",
                port="UrlGuard",
                retryable=True,
            ) from None
        except (socket.gaierror, OSError) as error:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"anahtar adı çözümlenemedi: {target.host} ({error.__class__.__name__})",
                port="UrlGuard",
            ) from None

        allowed: list[IPAddress] = []
        blocked: list[str] = []
        for raw in addresses:
            try:
                ip = ip_address(raw)
            except ValueError:
                continue
            unwrapped = _unwrap_ipv4(ip)
            if _is_blocked(unwrapped, allow_loopback=self._settings.allow_loopback):
                blocked.append(str(ip))
            elif unwrapped not in allowed:
                allowed.append(unwrapped)
        if not allowed:
            detail = f"; engellenen: {', '.join(blocked)}" if blocked else ""
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"yasak adres engellendi: {target.host} için güvenli adres yok{detail} "
                "(özel/loopback/link-local/metadata)",
                port="UrlGuard",
            )
        return allowed
