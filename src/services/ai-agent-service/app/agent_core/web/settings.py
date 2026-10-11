"""Web araç ayarları (plan A6: süre, yönlendirme, yanıt boyutu ve içerik türü sınırları).

Sır/anahtar kuralı: bu ayarlar anahtar TAŞIMAZ. Arama sağlayıcı anahtarı
varsa yalnız ortam değişkeni adıyla gösterilir (``HttpWebSearchProvider``) ve
değeri çağrı anında ``os.environ``'dan okunur; log/istisna/rapora girmez.

``allow_private_addresses`` test kolaylığıdır (localhost mock sunucu) ve
``UrlGuard.from_settings`` üretimde (``environment != "test"``) ``config_error``
ile reddeder — test double kuralıyla aynı desen (adapters/config.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat

__all__ = ["DEFAULT_ALLOWED_CONTENT_TYPES", "WebToolSettings"]

#: Kabul edilen medya türleri; parametreler strip edilip önekle eşlenir.
DEFAULT_ALLOWED_CONTENT_TYPES: tuple[str, ...] = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/json",
    "application/xml",
    "text/xml",
    "application/xml+rss",
    "application/rss+xml",
)


class WebToolSettings(BaseModel):
    """Web okuma/arama sınırları; bilinmeyen anahtar reddedilir."""

    model_config = ConfigDict(extra="forbid")

    environment: Literal["development", "test", "production"] = "development"

    #: Sabit, sırsız kimlik; operatör geçersine kılmak istiyorsa değiştirir.
    user_agent: str = "MrBekoXBlogApp-Agent/0.1 (research tool; +https://mrbekox.dev)"

    # Yanıt sınırları (plan A6: yanıt boyutu ve içerik türü sınırları).
    max_response_bytes: int = Field(default=2_000_000, gt=0)
    max_header_bytes: int = Field(default=64 * 1024, gt=0)
    max_text_chars: int = Field(default=500_000, gt=0)
    allowed_content_types: tuple[str, ...] = DEFAULT_ALLOWED_CONTENT_TYPES

    # Süre sınırları (plan A6: süre sınırı; fazlara bölünmüş).
    connect_timeout_s: PositiveFloat = 10.0
    header_timeout_s: PositiveFloat = 10.0
    body_idle_timeout_s: PositiveFloat = 20.0
    resolver_timeout_s: PositiveFloat = 5.0
    total_timeout_s: PositiveFloat = 30.0

    # Yönlendirme ve bağlantı noktası sınırları.
    max_redirects: int = Field(default=5, ge=0)
    allowed_ports: tuple[int, ...] = (80, 443)

    # SSRF: özel/loopback/link-local/metadata adresler varsayılan engelli.
    # allow_loopback yalnız 127.0.0.0/8 + ::1'i (localhost mock sunucu) açar ve
    # yalnız environment="test" iken kabul edilir (UrlGuard.from_settings);
    # diğer özel ağlar ve metadata adresi testte bile engelli kalır.
    allow_loopback: bool = False

    # Sınırlı retry gecikmesi (üst düzey retry BudgetGuard'a aittir).
    retry_backoff_base_s: float = Field(default=0.25, ge=0)
    retry_backoff_cap_s: PositiveFloat = 2.0
