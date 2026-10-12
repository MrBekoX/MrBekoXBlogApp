"""Sağlayıcı yapılandırma çözümlemesi.

Kabul ölçütü: "Sağlayıcı yapılandırma hataları anlaşılırdır" — her red
``config_error`` kodlu ve insan-okur mesajlıdır; mesaj sağlayıcı adını, eksik
alanı ve düzeltmeyi gösterir.

Kritik kontrol: test sağlayıcısı üretimde etkinleştirilemez (ana prompt).
``environment != "test"`` iken test double döndüren çözümleyici ``config_error``
ile reddeder; ayrıca döndürdüğü her nesnenin ``is_test_double`` işareti
üretimde yasaktır.

A1'de yalnız ``test`` sağlayıcısının somut adaptörü vardır; ollama/openai/
anthropic bilinen adlardır ve eksik-alan doğrulaması yapılır, somut
adaptörleri sonraki fazlarda ``agent_core.adapters`` altına eklenir.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..errors import AgentErrorCode, PortError
from ..ports import EmbeddingProvider, ModelProvider, WebSearchProvider

__all__ = ["ProviderSettings", "resolve_embedding_provider", "resolve_model_provider", "resolve_web_search_provider"]


class ProviderSettings(BaseModel):
    """Sağlayıcı yapılandırma girdisi; bilinmeyen anahtar reddedilir (extra=forbid)."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "test"
    environment: Literal["development", "test", "production"] = "development"
    api_key: str | None = None
    base_url: str | None = None
    model_name: str | None = None


#: Bilinen sağlayıcı adları ve zorunlu ayar alanları (değerler sonraki fazlarda dolan altyapıdır).
_KNOWN_PROVIDERS: dict[str, tuple[str, ...]] = {
    "test": (),
    "ollama": ("base_url", "model_name"),
    "openai": ("api_key", "model_name"),
    "anthropic": ("api_key", "model_name"),
}

#: Bilinen adların aynası; ayar alanları embed/web varyantlarında farklılaşmaz.
_KNOWN_EMBEDDING_PROVIDERS = ("test", "ollama", "openai")
_KNOWN_WEB_PROVIDERS = ("test",)


def _validate_known(kind: str, provider: str, known: tuple[str, ...] | dict[str, tuple[str, ...]]) -> None:
    names = tuple(known) if isinstance(known, dict) else known
    if provider not in known:
        raise PortError(
            AgentErrorCode.CONFIG_ERROR,
            f"Bilinmeyen {kind} sağlayıcısı '{provider}'. Bilinen sağlayıcılar: {', '.join(names)}. "
            "ProviderSettings.provider alanını düzeltin.",
            port="ProviderSettings",
        )


def _validate_required_fields(provider: str, settings: ProviderSettings, required: tuple[str, ...]) -> None:
    missing = [
        field for field in required
        if getattr(settings, field) is None or (isinstance(getattr(settings, field), str) and not getattr(settings, field).strip())
    ]
    if missing:
        raise PortError(
            AgentErrorCode.CONFIG_ERROR,
            f"'{provider}' sağlayıcısı eksik yapılandırılmış: zorunlu ayar(lar) yok: "
            f"{', '.join(missing)}. ProviderSettings alanlarını doldurun ve sağlayıcı "
            "kimlik bilgilerini ortam değişkenlerinden besleyin.",
            port="ProviderSettings",
        )


def _reject_test_outside_test_env(settings: ProviderSettings, provider_obj: object) -> None:
    if settings.environment != "test" and getattr(provider_obj, "is_test_double", False):
        raise PortError(
            AgentErrorCode.CONFIG_ERROR,
            f"'test' sağlayıcısı yalnız environment='test' iken kullanılabilir; "
            f"environment='{settings.environment}' için gerçek bir sağlayıcı yapılandırın. "
            "Test double'lar üretimde asla etkinleştirilemez.",
            port="ProviderSettings",
        )


def resolve_model_provider(settings: ProviderSettings) -> ModelProvider:
    """Ayarları somut ``ModelProvider``'a çözer.

    Raises:
        PortError: ``config_error`` — bilinmeyen sağlayıcı, eksik zorunlu ayar,
            uygulanmamış adaptör veya test double'ın test dışı ortamda istenmesi.
    """
    _validate_known("model", settings.provider, _KNOWN_PROVIDERS)
    _validate_required_fields(settings.provider, settings, _KNOWN_PROVIDERS[settings.provider])

    if settings.provider == "test":
        from .test_doubles import FakeModelProvider

        provider = FakeModelProvider()
        _reject_test_outside_test_env(settings, provider)
        return provider

    raise PortError(
        AgentErrorCode.CONFIG_ERROR,
        f"'{settings.provider}' model sağlayıcısının somut adaptörü bu fazda (A1) henüz uygulanmadı; "
        "yalnız 'test' sağlayıcısı mevcuttur. Somut adaptör agent_core/adapters altına "
        "eklenene kadar yapılandırmayı 'test' (yalnız test ortamı) olarak ayarlayın.",
        port="resolve_model_provider",
    )


def resolve_embedding_provider(settings: ProviderSettings) -> EmbeddingProvider:
    """Ayarları somut ``EmbeddingProvider``'a çözer; hata sözleşmesi model çözücü ile aynıdır."""
    _validate_known("embedding", settings.provider, _KNOWN_EMBEDDING_PROVIDERS)
    if settings.provider != "test":
        _validate_required_fields(settings.provider, settings, _KNOWN_PROVIDERS[settings.provider])

    if settings.provider == "test":
        from .test_doubles import FakeEmbeddingProvider

        provider = FakeEmbeddingProvider()
        _reject_test_outside_test_env(settings, provider)
        return provider

    raise PortError(
        AgentErrorCode.CONFIG_ERROR,
        f"'{settings.provider}' embedding sağlayıcısının somut adaptörü bu fazda (A1) henüz uygulanmadı; "
        "yalnız 'test' sağlayıcısı mevcuttur. A3 öncesi sağlayıcı kararı tamamlandığında "
        "agent_core/adapters altına eklenecektir.",
        port="resolve_embedding_provider",
    )


def resolve_web_search_provider(settings: ProviderSettings) -> WebSearchProvider:
    """Ayarları somut ``WebSearchProvider``'a çözer; hata sözleşmesi model çözücü ile aynıdır."""
    _validate_known("web arama", settings.provider, _KNOWN_WEB_PROVIDERS)

    if settings.provider == "test":
        from .test_doubles import FakeWebSearchProvider

        provider = FakeWebSearchProvider()
        _reject_test_outside_test_env(settings, provider)
        return provider

    raise PortError(
        AgentErrorCode.CONFIG_ERROR,
        f"'{settings.provider}' web arama sağlayıcısı bilinmiyor; bilinen: test.",
        port="resolve_web_search_provider",
    )
