"""Isolated test overrides must never fall back to personal dotenv files."""

from pathlib import Path

import pytest

from infra_environment import (
    broker_address, broker_management_url, postgres_credentials,
    postgres_host, postgres_migration_url, postgres_port,
)


@pytest.fixture(autouse=True)
def clean_test_settings(monkeypatch):
    for key in ("BLOGAPP_TEST_PG_HOST", "BLOGAPP_TEST_PG_PORT", "BLOGAPP_TEST_PG_USER",
                "BLOGAPP_TEST_PG_PASSWORD", "RABBITMQ_HOST", "RABBITMQ_PORT", "RABBITMQ_MGMT_URL"):
        monkeypatch.delenv(key, raising=False)


def test_explicit_credentials_never_read_dotenv(monkeypatch):
    monkeypatch.setenv("BLOGAPP_TEST_PG_USER", "disposable-user")
    monkeypatch.setenv("BLOGAPP_TEST_PG_PASSWORD", "disposable-password")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("dotenv must not be read"))
    assert postgres_credentials(Path("unavailable-repository")) == {
        "POSTGRES_USER": "disposable-user", "POSTGRES_PASSWORD": "disposable-password",
    }


def test_partial_explicit_settings_fail_without_reading_dotenv(monkeypatch):
    monkeypatch.setenv("BLOGAPP_TEST_PG_PORT", "25432")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("dotenv must not be read"))
    with pytest.raises(pytest.fail.Exception, match="require BLOGAPP_TEST_PG_USER"):
        postgres_credentials(Path("unavailable-repository"))


def test_infrastructure_endpoints_accept_isolated_overrides(monkeypatch):
    monkeypatch.setenv("RABBITMQ_HOST", "test-broker")
    monkeypatch.setenv("RABBITMQ_PORT", "25672")
    monkeypatch.setenv("RABBITMQ_MGMT_URL", "http://test-broker:25673/api/")
    monkeypatch.setenv("BLOGAPP_TEST_PG_HOST", "::1")
    monkeypatch.setenv("BLOGAPP_TEST_PG_PORT", "25432")
    assert broker_address() == {"host": "test-broker", "port": 25672}
    assert broker_management_url() == "http://test-broker:25673/api"
    assert postgres_migration_url("scratch", "user@name", "password:example") == (
        "postgresql+asyncpg://user%40name:password%3Aexample@[::1]:25432/scratch"
    )


def test_existing_ci_endpoint_defaults_are_preserved():
    assert broker_address() == {"host": "127.0.0.1", "port": 5672}
    assert broker_management_url() == "http://127.0.0.1:15672/api"
    assert postgres_host() == "127.0.0.1"
    assert postgres_port() == 5432
