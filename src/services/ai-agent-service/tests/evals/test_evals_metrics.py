"""Ölçüm fonksiyonlarının birim denetimleri (metrics saf fonksiyonları)."""

from __future__ import annotations

import evals_bootstrap  # noqa: F401 - sys.path kurulumu

from datetime import datetime, timezone

from agent_core.models import BudgetProfile, SourceReference, UsageRecord

NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)
from evals.metrics import (
    audit_citations,
    citations_hit_section,
    percentile,
    within_budget_profile,
)


def _article_citation(chunk_index: int) -> SourceReference:
    return SourceReference(
        kind="article", article_id="post-1", article_revision=1, chunk_index=chunk_index
    )


def test_audit_citations_counts_supported_and_wrong_sources():
    chunks = {
        0: "asyncio kuyrugunda onerilen ust sinir araligi 100 ile 1000 arasindadir",
        1: "farkin uretim hattiyla ilgisi yoktur",
    }
    answer = "Kuyruğun önerilen üst sınır aralığı 100 ile 1000 arasındadır."
    audit = audit_citations(answer, [_article_citation(0), _article_citation(1)], chunks)
    assert audit.total == 2
    assert audit.supported == 1
    assert audit.support_rate == 0.5
    assert audit.wrong_source_rate == 0.5
    assert audit.unsupported == ["article:post-1:1:1"]


def test_audit_citations_handles_empty_and_web_kinds():
    audit = audit_citations("cevap yok", [], {})
    assert audit.total == 0 and audit.support_rate == 0.0
    web = SourceReference(kind="web", url="https://ornek.dev/x", accessed_at=NOW)
    audit2 = audit_citations("cevap", [web], {})
    assert audit2.total == 1 and audit2.supported == 0


def test_citations_hit_section_matches_expected_heading():
    headings = {0: "Asyncio Kuyruk Yönetimi > Hata yönetimi", 1: "Giriş"}
    assert citations_hit_section([_article_citation(0)], headings, "Hata yönetimi") is True
    assert citations_hit_section([_article_citation(1)], headings, "Hata yönetimi") is False


def test_percentile_interpolates_and_handles_empty():
    assert percentile([], 0.95) is None
    assert percentile([3.0], 0.95) == 3.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert abs(percentile([1.0, 2.0, 3.0, 4.0], 0.95) - 3.85) < 1e-9


def _usage(**overrides) -> UsageRecord:
    defaults = dict(
        run_id="r",
        model_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        tool_calls=2,
        web_search_calls=1,
        duration_seconds=1.0,
        recorded_at=NOW,
    )
    defaults.update(overrides)
    return UsageRecord(**defaults)


def _profile(**overrides) -> BudgetProfile:
    defaults = dict(
        name="p",
        max_model_calls=2,
        max_total_tokens=1000,
        max_tool_calls=4,
        max_web_search_calls=2,
        max_duration_seconds=60.0,
    )
    defaults.update(overrides)
    return BudgetProfile(**defaults)


def test_within_budget_profile_reports_violations():
    ok, violations = within_budget_profile(_usage(), _profile())
    assert ok and violations == []
    bad, violations = within_budget_profile(
        _usage(web_search_calls=5, model_calls=9), _profile()
    )
    assert not bad
    assert any("web_search_calls" in v for v in violations)
    assert any("model_calls" in v for v in violations)
