"""Sağlayıcı yapılandırma çözümleme testleri.

Kabul ölçütleri: "Sağlayıcı yapılandırma hataları anlaşılırdır" ve kritik
kontrol "Test sağlayıcısı üretimde etkinleştirilemez".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_core.adapters import ProviderSettings, resolve_embedding_provider, resolve_model_provider, resolve_web_search_provider
from agent_core.adapters.test_doubles import FakeModelProvider
from agent_core.errors import AgentErrorCode, PortError


def test_test_provider_is_rejected_outside_test_environment() -> None:
    for environment in ("development", "production"):
        settings = ProviderSettings(provider="test", environment=environment)

        with pytest.raises(PortError) as excinfo:
            resolve_model_provider(settings)

        assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
        message = str(excinfo.value)
        assert "environment" in message
        assert environment in message


def test_test_provider_is_returned_only_in_test_environment() -> None:
    provider = resolve_model_provider(ProviderSettings(provider="test", environment="test"))

    assert isinstance(provider, FakeModelProvider)
    assert provider.is_test_double is True


def test_unknown_provider_message_names_the_provider_and_known_ones() -> None:
    settings = ProviderSettings(provider="mistralx", environment="test")

    with pytest.raises(PortError) as excinfo:
        resolve_model_provider(settings)

    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    message = str(excinfo.value)
    assert "mistralx" in message
    for known in ("test", "ollama", "openai", "anthropic"):
        assert known in message


def test_missing_required_settings_are_named_in_the_error() -> None:
    settings = ProviderSettings(provider="openai", environment="test")  # api_key ve model_name yok

    with pytest.raises(PortError) as excinfo:
        resolve_model_provider(settings)

    message = str(excinfo.value)
    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    assert "api_key" in message
    assert "model_name" in message


def test_known_but_unimplemented_provider_gives_actionable_error() -> None:
    settings = ProviderSettings(
        provider="openai", environment="test", api_key="sk-test", model_name="gpt-x"
    )

    with pytest.raises(PortError) as excinfo:
        resolve_model_provider(settings)

    message = str(excinfo.value)
    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    assert "A1" in message
    assert "agent_core/adapters" in message


def test_unknown_settings_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProviderSettings(providers="openai", environment="test")


def test_embedding_resolver_follows_same_contract() -> None:
    with pytest.raises(PortError) as production_exc:
        resolve_embedding_provider(ProviderSettings(provider="test", environment="production"))
    assert production_exc.value.code is AgentErrorCode.CONFIG_ERROR

    with pytest.raises(PortError) as unknown_exc:
        resolve_embedding_provider(ProviderSettings(provider="cohere", environment="test"))
    assert unknown_exc.value.code is AgentErrorCode.CONFIG_ERROR

    provider = resolve_embedding_provider(ProviderSettings(provider="test", environment="test"))
    assert provider.is_test_double is True


def test_web_search_resolver_follows_same_contract() -> None:
    with pytest.raises(PortError) as unknown_exc:
        resolve_web_search_provider(ProviderSettings(provider="serpapi", environment="test"))
    assert unknown_exc.value.code is AgentErrorCode.CONFIG_ERROR

    provider = resolve_web_search_provider(ProviderSettings(provider="test", environment="test"))
    assert provider.is_test_double is True
