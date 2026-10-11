"""A6 gerçek resmî sayfa okumaları (gerçek internet erişimi).

Bu testler sahte sonuç üretmez: gerçek DNS + TLS + HTTP üzerinden resmî
belgeleri okur. Ağ kapalıysa ``pytest.skip`` ile işaretlenir ve faz raporunda
partial durum olarak kaydedilir — başarısızlık başarı gibi gösterilmez.
"""

from __future__ import annotations

import socket

import pytest

from agent_core.adapters.test_doubles.fake_state import FakeBudgetStore
from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy
from agent_core.errors import PortError
from agent_core.web import (
    AssessSourceTool,
    HttpFetcher,
    ReadSourceTool,
    TextExtractor,
    UrlGuard,
    WebToolSettings,
)

from .web_helpers import run

REAL_SETTINGS = WebToolSettings(
    environment="production",  # loopback dahil özel adres engelli: gerçek üretim davranışı
    connect_timeout_s=10.0,
    header_timeout_s=10.0,
    body_idle_timeout_s=15.0,
    total_timeout_s=40.0,
    resolver_timeout_s=5.0,
    max_response_bytes=2_000_000,
)


def make_read_tool() -> ReadSourceTool:
    guard = BudgetGuard(
        FakeBudgetStore(),
        BudgetPolicy(max_attempts_per_action=2, max_duration_seconds=60),
        "run-a6-real",
    )
    fetcher = HttpFetcher(REAL_SETTINGS, UrlGuard.from_settings(REAL_SETTINGS))
    return ReadSourceTool(guard, fetcher, TextExtractor(REAL_SETTINGS), settings=REAL_SETTINGS)


def _skip_on_network_error(error: Exception) -> None:
    pytest.skip(f"gerçek ağ erişimi başarısız: {error.__class__.__name__}: {error}")


def _run_read(url: str):
    """Gerçek okuma; ağ tipi arızalarda skip, içerik hatasında gerçek başarısızlık."""
    try:
        return run(make_read_tool().read(url))
    except (socket.gaierror, OSError, TimeoutError) as error:
        _skip_on_network_error(error)
    except PortError as error:
        if error.code.value in ("not_found", "timeout", "provider_error") and error.retryable:
            _skip_on_network_error(error)
        raise


def test_read_rabbitmq_confirms_official_page() -> None:
    """Resmî RabbitMQ publisher confirms belgesi gerçekten okunur."""
    record = _run_read("https://www.rabbitmq.com/docs/confirms")
    assert record.extraction_status.value == "ok", record.extraction_status
    assert record.title and "onfirm" in record.title  # "Confirms" / "Consumer Acknowledgements..."
    assert record.final_url.startswith("https://")
    assert len(record.content_hash) == 64
    assert "confirm" in record.text.lower()
    assert record.published_at is None or record.published_at.tzinfo is not None  # varsa UTC; yoksa None (uydurma yok)
    assert any(e.kind.value == "full_page" for e in record.evidences)

    assessment = run(AssessSourceTool().assess(record))
    assert assessment.source_type.value == "official_docs"
    assert assessment.priority_rank == 0


def test_read_python_asyncio_official_docs() -> None:
    """Resmî Python asyncio belgesi gerçekten okunur (DNS + TLS dahil)."""
    record = _run_read("https://docs.python.org/3.13/library/asyncio-task.html")
    assert record.extraction_status.value == "ok"
    assert "coroutines and tasks" in (record.title or "").lower()
    assert "asyncio" in record.text.lower()
    assert len(record.content_hash) == 64

    assessment = run(AssessSourceTool().assess(record))
    assert assessment.source_type.value == "official_docs"
    assert assessment.publisher_group == "python.org"


def test_real_dns_resolution_yields_only_public_addresses() -> None:
    """Gerçek DNS: resmî anahtar adı yalnız genel adreslere çözümlenir."""
    guard = UrlGuard.from_settings(REAL_SETTINGS)
    target = guard.parse("https://www.rabbitmq.com/docs/confirms")
    addresses = run(guard.resolve(target))
    assert addresses, "en az bir adres çözümlenmeli"
    for ip in addresses:
        assert not ip.is_private and not ip.is_loopback and not ip.is_link_local
