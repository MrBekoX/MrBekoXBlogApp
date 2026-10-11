"""``search_web``: JSON uç noktası üzerinden kontrollü web arama adaptörü (plan A6).

Sağlayıcı sözleşmesi (operatör yapılandırması): ``GET {base_url}?q=...&count=N``
→ ``200`` JSON ``{"results": [{"title": str, "url": str, "snippet"?: str}]}``.
Bu, self-hosted meta arama uç noktalarının (SearXNG vb.) normalize edicisiyle
uyumlu, sır-taşımayan genel biçimdir.

Sır kuralı (plan A6): "kaynak okuma aracına uygulama sırlarını taşıma".
Arama anahtarı YALNIZ ortam değişkeni adıyla gösterilir
(``api_key_env``), değeri çağrı anında ``os.environ``'dan okunur; log,
istisna mesajı veya kayda girmez. ``HttpFetcher`` bu modülün üzerinden geçen
kaynak okumalarının hiçbirine anahtar başlığı eklemez — anahtar yalnız
operatörün yapılandırdığı arama uç noktasına gider.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from ..errors import AgentErrorCode, PortError
from ..ports import CancellationToken, WebSearchProvider, WebSearchResult
from .fetch import HttpFetcher
from .settings import WebToolSettings
from .ssrf import UrlGuard

__all__ = ["HttpWebSearchProvider"]


class HttpWebSearchProvider:
    """``WebSearchProvider`` portunun somut JSON sağlayıcı adaptörü.

    Uç nokta operatör yapılandırmasıdır (sağlayıcı taban URL'si gibi);
    ajan kontrolündeki rastgele URL'lerle kullanılmaz.
    """

    def __init__(
        self,
        base_url: str,
        settings: WebToolSettings,
        guard: UrlGuard,
        *,
        api_key_env: str | None = None,
        api_key_header: str = "Authorization",
        api_key_scheme: str = "Bearer",
        provider_name: str = "http-json",
    ) -> None:
        if not base_url.strip():
            raise PortError(
                AgentErrorCode.CONFIG_ERROR,
                "arama sağlayıcı taban adresi (base_url) boş; WebToolSettings ile yapılandırın",
                port="HttpWebSearchProvider",
            )
        self._base_url = base_url.strip().rstrip("/")
        self._settings = settings
        self._fetcher = HttpFetcher(settings, guard)
        self._api_key_env = api_key_env
        self._api_key_header = api_key_header
        self._api_key_scheme = api_key_scheme
        self.provider_name = provider_name

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        cancel: CancellationToken | None = None,
    ) -> list[WebSearchResult]:
        """Sorguyu sağlayıcıya gönderir; sonuçları port modeline doğrular.

        Raises:
            PortError: ``validation_error`` — boş sorgu; ``config_error`` —
                anahtar ortam değişkeni tanımlı ama değeri yok; ``not_found`` /
                ``provider_error`` / ``timeout`` / ``cancelled`` — getirme ve
                çözümleme arızaları.
        """
        if not isinstance(query, str) or not query.strip():
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "arama sorgusu boş olamaz",
                port="WebSearchProvider",
            )
        if cancel is not None:
            cancel.raise_if_cancelled()

        params = urlencode({"q": query.strip(), "count": max_results})
        url = f"{self._base_url}?{params}"
        headers = self._auth_headers()
        content = await self._fetcher.fetch(url, cancel=cancel, extra_headers=headers)
        return self._parse_results(content.body, max_results)

    def _auth_headers(self) -> dict[str, str]:
        """Yapılandırılmışsa anahtar başlığını üretir; değer asla loglanmaz."""
        if self._api_key_env is None:
            return {}
        value = os.environ.get(self._api_key_env, "").strip()
        if not value:
            raise PortError(
                AgentErrorCode.CONFIG_ERROR,
                f"arama sağlayıcı anahtarı eksik: '{self._api_key_env}' ortam değişkeni "
                "tanımlı ama değeri yok. Değişkeni ortamdan besleyin; anahtar kod veya "
                "yapılandırmaya yazılmaz.",
                port="HttpWebSearchProvider",
            )
        return {self._api_key_header: f"{self._api_key_scheme} {value}"}

    def _parse_results(self, body: bytes, max_results: int) -> list[WebSearchResult]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "arama yanıtı geçerli JSON değil",
                port="HttpWebSearchProvider",
            ) from None
        raw_results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(raw_results, list):
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "arama yanıtı 'results' listesi taşımıyor; sağlayıcı sözleşmesine uymuyor",
                port="HttpWebSearchProvider",
            )
        now = datetime.now(timezone.utc)
        results: list[WebSearchResult] = []
        for item in raw_results[: max_results * 2]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title or not url:
                continue  # bozuk girdi atlanır; sağlayıcı hatasına dönüşmez
            snippet = item.get("snippet")
            results.append(
                WebSearchResult(
                    title=title[:512],
                    url=url[:2048],
                    snippet=str(snippet)[:4000] if snippet else None,
                    retrieved_at=now,
                )
            )
            if len(results) >= max_results:
                break
        return results
