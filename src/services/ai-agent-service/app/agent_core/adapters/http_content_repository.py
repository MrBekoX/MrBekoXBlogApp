"""HTTP tabanlı ``ContentRepository`` adaptörü (backend iç ucu).

Canlı worker'da ``ContentRepository`` bağlanmadığında retrieval citation
üretilemez (``qa.nodes._fetch_snapshot``: ``config_error``); bu adaptör içeriği
backend'in iç uç noktasından okuyarak depoyu gerçek içerik kaynağına bağlar.

SABİT SÖZLEŞME (backend agent ile ortak; isimler birebir):

- ``GET {AGENT_CONTENT_BASE_URL}/agent/internal/content/{articleId}``
  (base URL sürümlü API köküdür, ör. ``https://host/api/v1`` — ``AGENT_LLM_BASE_URL``
  deseni: sürüm segmenti base'te, kaynak yolu adaptörde).
- Yetki: ``X-Agent-Service-Key`` başlığı; backend anahtarı
  ``AgentService:InternalApiKey`` ile SABİT ZAMANLI karşılaştırır. Anahtar
  yapılandırmamışsa uç nokta 404 döner (yüzey sızdırma).
- 200 gövdesi: ``articleId`` / ``revision`` (long) / ``contentHash``
  (sha256-hex-lower) / ``title`` / ``content`` (markdown) / ``tags`` /
  ``publishedAt`` (iso8601). Yalnız ``Published`` makaleler; yoksa/draft ise 404.
- ``revision`` backend'de kabul anındaki ``AgentRun.ArticleRevision`` ile AYNI
  kaynaktan (``BlogPost.ContentRevision``) gelir; ``contentHash`` kabul
  kodundaki UTF-8 SHA-256 hex hesabıyla aynıdır — böylece execute
  payload'undaki ``article_content_hash``/``article_revision`` ile
  uyuşmazsa çekirdekteki MEVCUT ``stale_snapshot`` guard'ı (``qa.nodes``
  ``_fetch_snapshot``) koşuyu düşürür. Bu adaptör YENİ GUARD YAZMAZ.

İstemci inject edilebilir (``client``); testler ``httpx.MockTransport``
kullanır — GERÇEK AĞ ÇAĞRISI YAPILMAZ (``openai_provider`` deseni).

Hata sözleşmesi (ports.content): ``not_found`` — HTTP 404 (yok/draft);
``provider_error`` — diğer HTTP/ağ arızası (5xx/429 ``retryable``);
``timeout`` — ağ zaman aşımı; sözleşmeye aykırı gövde ``provider_error``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from env_file import env_float

from ..errors import AgentErrorCode, PortError
from ..models import ArticleSnapshot
from ..ports import ContentRepository

__all__ = [
    "ContentRepositorySettings",
    "HttpContentRepository",
    "build_content_repository_from_env",
]

#: Uç nokta yolu; ``AGENT_CONTENT_BASE_URL`` (sürümlü API kökü) sonuna eklenir.
_CONTENT_PATH_TEMPLATE = "/agent/internal/content/{article_id}"

#: İç uç yetki başlığı (SABİT SÖZLEŞME).
_SERVICE_KEY_HEADER = "X-Agent-Service-Key"

#: Varsayılan istek zaman aşımı (saniye) — ``AGENT_CONTENT_TIMEOUT_SECONDS`` boşsa.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: ``PortError.port`` değeri: hata portu kendisidir (FakeContentRepository ile aynı ad).
_PORT = "ContentRepository"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ContentRepositorySettings:
    """İçerik deposu (backend iç ucu) bağlantı ayarları.

    ``from_env`` base URL boşken ``None`` döner: yapılandırılmamış, hata DEĞİL —
    çağıran MEVCUT (depoyu bağlamayan) davranışıyla sürer. Base URL dolu ama
    servis anahtarı boşsa ``config_error`` yükselir (anlaşılır yapılandırma
    redde kuralı): uç nokta anahtarsuz çağrıyı zaten reddeder; çalışma anında
    değil kurulumda düşer.
    """

    base_url: str
    service_key: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ContentRepositorySettings | None":
        """Ortam değişkenlerinden ayarları okur; base URL yoksa ``None`` döner.

        Değişkenler: ``AGENT_CONTENT_BASE_URL`` (boş → yapılandırılmamış),
        ``AGENT_CONTENT_SERVICE_KEY`` (base URL doluysa zorunlu),
        ``AGENT_CONTENT_TIMEOUT_SECONDS`` (saniye, default 10).
        """

        env = os.environ if environ is None else environ
        base_url = env.get("AGENT_CONTENT_BASE_URL", "")
        if not base_url.strip():
            return None
        service_key = env.get("AGENT_CONTENT_SERVICE_KEY", "")
        if not service_key.strip():
            raise PortError(
                AgentErrorCode.CONFIG_ERROR,
                "'AGENT_CONTENT_BASE_URL' dolu ama 'AGENT_CONTENT_SERVICE_KEY' tanımlı değil: "
                "içerik uç noktası 'X-Agent-Service-Key' başlığıyla yetkilendirilir. "
                "AGENT_CONTENT_SERVICE_KEY ortam değişkenini ayarlayın.",
                port="ContentRepositorySettings",
            )

        return cls(
            base_url=base_url,
            service_key=service_key,
            # env_file yardımcısı: boş değer → kod varsayılanı; tür hatası →
            # anlaşılır EnvConfigError (mesaj ham değeri yazmaz).
            timeout_seconds=env_float("AGENT_CONTENT_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, env),
        )


class HttpContentRepository(ContentRepository):
    """``ContentRepository`` portunun HTTP gerçekleştirimi (backend iç ucu).

    ``ArticleSnapshot`` alanlarına birebir mapleme (models/article.py:
    ``articleId`` → ``article_id``, ``revision`` → ``article_revision``,
    ``contentHash`` → ``content_hash``; ``slug``/``fetched_at`` yanıtta
    taşınmaz — slug yoksa makale kimliği, ``fetched_at`` okuma anıdır).
    ``hash``/``revision`` AYNEN taşınır: bağıt ve bayatlık denetimi çekirdeğin
    mevcut guard'ına aittir (bu adaptör yeniden hesaplamaz, yeni guard yazmaz).
    """

    def __init__(
        self,
        settings: ContentRepositorySettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        """Kendi kurduğu istemciyi kapatır; enjekte edilen istemciye dokunmaz."""

        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ port

    async def get_article(self, article_id: str) -> ArticleSnapshot:
        """İçerik uç noktasından makaleyi snapshot olarak döndürür.

        Raises:
            PortError: ``not_found`` — makale yok veya yayımlı değil (HTTP 404);
                ``timeout`` — ağ zaman aşımı; ``provider_error`` — diğer
                HTTP/ağ arızası veya sözleşmeye aykırı yanıt gövdesi.
        """

        url = self._settings.base_url.rstrip("/") + _CONTENT_PATH_TEMPLATE.format(
            article_id=quote(str(article_id), safe="")
        )
        timeout = httpx.Timeout(
            connect=self._settings.timeout_seconds,
            read=self._settings.timeout_seconds,
            write=self._settings.timeout_seconds,
            pool=self._settings.timeout_seconds,
        )
        try:
            client = self._ensure_client()
            response = await client.get(
                url,
                headers={_SERVICE_KEY_HEADER: self._settings.service_key},
                timeout=timeout,
            )
        except httpx.TimeoutException as error:
            raise PortError(
                AgentErrorCode.TIMEOUT,
                f"içerik isteği zaman aşımına uğradı: {error}",
                port=_PORT,
                retryable=True,
            ) from None
        except httpx.HTTPError as error:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"içerik isteği başarısız: {error}",
                port=_PORT,
                retryable=True,
            ) from None

        if response.status_code == 404:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"makale bulunamadı veya yayımlı değil: {article_id} (içerik uç noktası HTTP 404)",
                port=_PORT,
            )
        if response.status_code >= 400:
            detail = response.text[:500]
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"içerik uç noktası HTTP {response.status_code} döndürdü: {detail}",
                port=_PORT,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"içerik yanıtı JSON'a ayrıştırılamadı: {error}",
                port=_PORT,
                retryable=True,
            ) from None
        payload = self._unwrap_envelope(payload)
        return self._snapshot_from_payload(str(article_id), payload)

    @staticmethod
    def _unwrap_envelope(payload: Any) -> Any:
        """Backend uç konvansiyonu: 200 gövdesi ``ApiResponse<T>`` zarfıdır.

        ``{"success": true, "data": {…sözleşme alanları…}}`` biçimi açılır;
        ``success=false`` veya ``data`` taşımayan zarf ``provider_error``'dır —
        sözleşme alanlarının kendisi zarfsız beklenir.
        """

        if isinstance(payload, dict) and "success" in payload:
            if payload.get("success") is not True or not isinstance(payload.get("data"), dict):
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    "içerik yanıtı başarısız/eksik ApiResponse zarfı döndürdü",
                    port=_PORT,
                    retryable=True,
                )
            return payload["data"]
        return payload

    # -------------------------------------------------------------- iç adımlar

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    def _snapshot_from_payload(self, article_id: str, payload: Any) -> ArticleSnapshot:
        """Uç nokta yanıtını ``ArticleSnapshot``'a mapler; alan adları koddan.

        Sözleşme alanları: ``articleId``/``revision``/``contentHash``/``title``/
        ``content``/``tags``/``publishedAt`` (models/article.py alan adlarıyla
        birebir). Sözleşmeye aykırı gövde (eksik zorunlu alan, tip uyuşmazlığı,
        ``HashHex`` desenine aykırı hash) ``provider_error``'dır — sessiz
        varsayana düşmez, tutarsız veri akışa girmez.
        """

        if not isinstance(payload, dict):
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "içerik yanıtı beklenen JSON nesnesi değil",
                port=_PORT,
                retryable=True,
            )
        try:
            raw_tags = payload.get("tags") or []
            if not isinstance(raw_tags, list):
                raise ValueError("'tags' alanı dizi olmalıdır")
            return ArticleSnapshot(
                article_id=str(payload["articleId"]),
                # Sözleşme yanıtında slug taşınmaz: varsa kullan, yoksa makale
                # kimliği (Identifier kısıtı boşluğu reddeder; kimlik kararlıdır).
                slug=str(payload.get("slug") or article_id),
                title=str(payload["title"]),
                content=str(payload["content"]),
                content_hash=str(payload["contentHash"]),
                article_revision=int(payload["revision"]),
                tags=[str(tag) for tag in raw_tags],
                published_at=payload.get("publishedAt"),
                fetched_at=_utcnow(),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"içerik yanıtı ArticleSnapshot sözleşmesine aykırı: {error}",
                port=_PORT,
                retryable=True,
            ) from None


def build_content_repository_from_env(
    environ: Mapping[str, str] | None = None,
) -> ContentRepository | None:
    """``AGENT_CONTENT_BASE_URL`` doluysa gerçek HTTP içerik depoyu kurar.

    Base URL boşsa ``None`` döner: çağıran MEVCUT davranışıyla (depo bağlamadan)
    sürer — boş ortam birebir korunur (``build_model_provider_from_env`` deseni).
    """

    settings = ContentRepositorySettings.from_env(environ)
    if settings is None:
        return None
    return HttpContentRepository(settings)
