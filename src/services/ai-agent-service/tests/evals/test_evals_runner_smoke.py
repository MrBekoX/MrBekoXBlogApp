"""Koşucu duman testleri: gerçek koşu kısa suitte + rapor üretimi.

Tam küme koşusu kapı komutuyla yapılır (``python -m evals.run --suite all
--report out/evals``); bu duman testi koşucunun ÇALIŞTIRILABİLİRLİĞİNİ ve
sağlayıcı işaretlemesini sürekli doğrular. Tamamı test sağlayıcılarla
koşar (gerçek LLM/embedding yoktur ve başarı olarak yazılmaz).
"""

from __future__ import annotations

import json

import evals_bootstrap  # noqa: F401 - sys.path kurulumu

from evals.dataset import case_by_id, cases_for_suite
from evals.harness import EvalRuntime, run_cases
from evals.providers import TEST_PROVIDER_ID
from evals.report import write_report


def test_routing_suite_runs_through_entry_points():
    with EvalRuntime() as runtime:
        results = run_cases("routing", runtime=runtime)
    assert len(results) == len(cases_for_suite("routing"))
    assert all(r.provider == TEST_PROVIDER_ID for r in results)
    # Bilinen bulgu dışında rota örnekleri beklenen davranışı verir.
    # (r08: 'recommend' öneri sinyalinin makale sorusunu yakalaması — A10 raporu F1.
    sapislar = [r.case_id for r in results if not r.ok]
    assert set(sapislar) <= {"r08"}, f"beklenmeyen rota sapmaları: {sapislar}"


def test_cache_suite_fully_passes():
    with EvalRuntime() as runtime:
        results = run_cases("cache", runtime=runtime)
    assert all(r.ok for r in results)


def test_qa_suite_fully_passes_and_measures_citations():
    with EvalRuntime() as runtime:
        results = run_cases("qa", runtime=runtime)
    assert all(r.ok for r in results), [r.case_id for r in results if not r.ok]
    audits = [r.audit for r in results if r.audit and r.audit["total"]]
    assert audits, "atıf denetimi üretilmedi"
    assert all(a["total"] == a["supported"] for a in audits), "desteklenmeyen atıf üretildi"


def test_report_writer_marks_test_executor():
    with EvalRuntime() as runtime:
        results = run_cases("cache", runtime=runtime)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        written = write_report(results, Path(tmp))
        payload = json.loads(Path(written["json"]).read_text(encoding="utf-8"))
        markdown = Path(written["markdown"]).read_text(encoding="utf-8")
    assert payload["provider"] == TEST_PROVIDER_ID == "test_executor"
    assert payload["provider_note"]
    assert "test_executor" in markdown
    assert payload["totals"]["executed"] == len(results)


def test_known_signal_collision_is_documented_as_finding():
    """r08 etiketi bilinçli olarak bağımsız kalır: sapma gerçek bulgudur."""
    case = case_by_id("r08")
    assert case is not None
    assert case.expected.intent == "article_qa"
    assert "recommend" in case.question
