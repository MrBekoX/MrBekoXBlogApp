"""Rapor yazıcı: ölçümleri JSON + Markdown olarak kümelendirir.

Her rapor ``provider="test_executor"`` işaretini ve "GERÇEK sağlayıcı ile
çalıştırılmadı" beyanını taşır (plan A10: ölçülmeyen performans başarı
iddiası olarak yazılmaz). Kapsam doluluğu ``dataset.AREAS`` üzerinden
raporlanır; örnek başına etiket gerekçeleri (``rationale``) raporda durur.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .dataset import AREAS, CASES, EvalCase
from .providers import TEST_PROVIDER_ID

__all__ = ["aggregate", "write_report", "PROVIDER_NOTE"]

PROVIDER_NOTE = (
    "Bu koşu GERÇEK LLM/embedding/web-arama sağlayıcısı olmadan, tamamı "
    "is_test_double işaretli test sağlayıcılarıyla yapılmıştır "
    "(provider=test_executor). Metrikler; bu sağlayıcılar altında boru "
    "hattının yönlendirme/retrieval/atıf denetimi/bütçe-iptal davranışını "
    "ölçer. GERÇEK model sadakati, gerçek gecikme ve gerçek arama kalitesi "
    "BU RAPORDAN ÖLÇÜLEMEZ ve başarı olarak yazılmamıştır."
)


def aggregate(case_results: list) -> dict:
    """CaseResult listesinden plan A10 ölçü ailelerinin özetini üretir."""
    by_id = {r.case_id: r for r in case_results}
    cases_by_id = {c.case_id: c for c in CASES}

    def _checks_of(case_id: str) -> list:
        record = by_id.get(case_id)
        return record.checks if record is not None else []

    # 1) Görev ve mod kararlarının doğruluğu ---------------------------------
    mode_cases = [c for c in CASES if c.expected.mode is not None]
    intent_cases = [c for c in CASES if c.expected.intent is not None]
    web_cases = [c for c in CASES if c.expected.needs_web is not None]
    clarify_cases = [c for c in CASES if c.expected.needs_clarification is not None]

    def _accuracy(check_name: str, case_list: list[EvalCase]) -> dict:
        total = 0
        correct = 0
        misses: list[str] = []
        for case in case_list:
            for check in _checks_of(case.case_id):
                if check.name == check_name:
                    total += 1
                    if check.ok:
                        correct += 1
                    else:
                        misses.append(f"{case.case_id}({check.actual}≠{check.expected})")
        rate = correct / total if total else None
        return {"total": total, "correct": correct, "accuracy": round(rate, 4) if rate is not None else None, "misses": misses}

    routing_block = {
        "mode_accuracy": _accuracy("mode", mode_cases),
        "intent_accuracy": _accuracy("intent", intent_cases),
        "web_need_accuracy": _accuracy("needs_web", web_cases),
        "clarification_accuracy": _accuracy("needs_clarification", clarify_cases),
        "source_scope_accuracy": _accuracy(
            "source_scope", [c for c in CASES if c.expected.source_scope is not None]
        ),
    }

    # 2) İlgili bölümün bulunması --------------------------------------------
    probe_total = probe_hit = cited_total = cited_hit = 0
    probe_misses: list[str] = []
    for case in CASES:
        if case.expected.expected_section is None:
            continue
        record = by_id.get(case.case_id)
        if record is None:
            continue
        if record.section_probe_hit is not None:
            probe_total += 1
            probe_hit += 1 if record.section_probe_hit else 0
            if not record.section_probe_hit:
                probe_misses.append(case.case_id)
        if record.section_cited is not None:
            cited_total += 1
            cited_hit += 1 if record.section_cited else 0

    retrieval_block = {
        "section_found": {
            "total": probe_total,
            "hit": probe_hit,
            "hit_rate": round(probe_hit / probe_total, 4) if probe_total else None,
            "misses": probe_misses,
        },
        "section_cited": {
            "total": cited_total,
            "hit": cited_hit,
            "hit_rate": round(cited_hit / cited_total, 4) if cited_total else None,
        },
    }

    # 3) İddia–kanıt desteği ve hatalı kaynak oranı ---------------------------
    audit_total = audit_supported = 0
    audits = 0
    for case in CASES:
        record = by_id.get(case.case_id)
        if record is None or not record.audit or not record.audit.get("total"):
            continue
        audits += 1
        audit_total += record.audit["total"]
        audit_supported += record.audit["supported"]
    citation_block = {
        "audited_runs": audits,
        "total_citations": audit_total,
        "supported_citations": audit_supported,
        "claim_support_rate": round(audit_supported / audit_total, 4) if audit_total else None,
        "wrong_source_rate": round((audit_total - audit_supported) / audit_total, 4) if audit_total else None,
    }

    # 4) Fast/analysis gecikmesi ----------------------------------------------
    latency: dict[str, dict] = {}
    from .metrics import percentile

    for family in ("fast", "analysis", "deep_research"):
        durations = [
            r.duration_s
            for r in case_results
            if r.latency_family == family and not r.latency_artificial and r.duration_s > 0
        ]
        if durations:
            latency[family] = {
                "runs": len(durations),
                "p50_s": round(percentile(durations, 0.50) or 0.0, 4),
                "p95_s": round(percentile(durations, 0.95) or 0.0, 4),
                "mean_s": round(sum(durations) / len(durations), 4),
            }
    latency_block = {
        "note": (
            "Test sağlayıcıyla ölçülen değerler ORKESTRASYON süresidir "
            "(model/embedding çağrısı yapay ve anlıktır); gerçek sağlayıcı "
            "gecikmesi bu koşudan ölçülemez."
        ),
        "families": latency,
    }

    # 5) Araştırma başına araç/model kullanımı --------------------------------
    research_records = [r for r in case_results if r.suite == "research" and r.usage]
    usage_runs = [r for r in research_records if r.usage.get("model_calls", 0) > 0 or r.usage.get("web_search_calls", 0) > 0]
    budget_ok = [
        1
        for r in research_records
        for check in r.checks
        if check.name == "within_budget" and check.ok
    ]
    research_block = {
        "runs": len(research_records),
        "runs_with_activity": len(usage_runs),
        "avg_model_calls": round(sum(r.usage["model_calls"] for r in research_records) / len(research_records), 2)
        if research_records
        else None,
        "avg_web_search_calls": round(sum(r.usage["web_search_calls"] for r in research_records) / len(research_records), 2)
        if research_records
        else None,
        "avg_tool_calls": round(sum(r.usage["tool_calls"] for r in research_records) / len(research_records), 2)
        if research_records
        else None,
        "within_budget_runs": len(budget_ok),
    }

    # 6) Checkpoint'ten devam başarısı ----------------------------------------
    resume_records = [r for r in case_results if r.kind == "resume"]
    resume_ok = [r for r in resume_records if r.ok]
    resume_block = {
        "runs": len(resume_records),
        "successful": len(resume_ok),
        "success_rate": round(len(resume_ok) / len(resume_records), 4) if resume_records else None,
        "failed_case_ids": [r.case_id for r in resume_records if not r.ok],
    }

    # 7) Bütçe/iptal davranışı -------------------------------------------------
    budget_cancel_cases = [c for c in CASES if set(c.areas) & {"butce", "iptal"} and c.suite != "research"]
    bc_total = 0
    bc_ok = 0
    for case in budget_cancel_cases:
        record = by_id.get(case.case_id)
        if record is None:
            continue
        bc_total += 1
        bc_ok += 1 if record.ok else 0
    budget_cancel_block = {
        "cases": bc_total,
        "expected_behavior": bc_ok,
        "accuracy": round(bc_ok / bc_total, 4) if bc_total else None,
    }

    # Önbellek sözleşmesi -------------------------------------------------------
    cache_records = [r for r in case_results if r.suite == "cache"]
    cache_checks = [check for r in cache_records for check in r.checks]
    cache_block = {
        "cases": len(cache_records),
        "checks": len(cache_checks),
        "passed": sum(1 for check in cache_checks if check.ok),
        "pass_rate": round(sum(1 for check in cache_checks if check.ok) / len(cache_checks), 4)
        if cache_checks
        else None,
    }

    # Kapsam doluluğu ------------------------------------------------------------
    coverage = {area: 0 for area in AREAS}
    for case in CASES:
        for area in case.areas:
            coverage[area] += 1

    total_cases = len(CASES)
    run_cases_n = len(case_results)
    all_checks = [check for r in case_results for check in r.checks]
    return {
        "provider": TEST_PROVIDER_ID,
        "provider_note": PROVIDER_NOTE,
        "totals": {
            "dataset_size": total_cases,
            "executed": run_cases_n,
            "case_expectation_checks": len(all_checks),
            "checks_passed": sum(1 for check in all_checks if check.ok),
            "check_pass_rate": round(sum(1 for check in all_checks if check.ok) / len(all_checks), 4)
            if all_checks
            else None,
        },
        "coverage": coverage,
        "routing": routing_block,
        "retrieval": retrieval_block,
        "citations": citation_block,
        "latency": latency_block,
        "research_usage": research_block,
        "resume": resume_block,
        "budget_cancel": budget_cancel_block,
        "cache_policy": cache_block,
    }


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join([head, sep, body])


def render_markdown(case_results: list, summary: dict) -> str:
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# A10 değerlendirme koşusu — özet")
    lines.append("")
    lines.append(f"- Üretim zamanı (UTC): {generated}")
    lines.append(f"- Sağlayıcı: **{summary['provider']}**")
    lines.append("")
    lines.append(f"> {summary['provider_note']}")
    lines.append("")
    totals = summary["totals"]
    lines.append("## Toplamlar")
    lines.append("")
    lines.append(
        _markdown_table(
            ["Küme büyüklüğü", "Koşulan", "Beklenti denetimi", "Geçen denetim", "Geçiş oranı"],
            [
                [
                    str(totals["dataset_size"]),
                    str(totals["executed"]),
                    str(totals["case_expectation_checks"]),
                    str(totals["checks_passed"]),
                    str(totals["check_pass_rate"]),
                ]
            ],
        )
    )
    lines.append("")
    lines.append("## Kapsam doluluğu (plan A10 kapsam listesi)")
    lines.append("")
    lines.append(
        _markdown_table(
            ["Kapsam", "Örnek sayısı"],
            [[area, str(count)] for area, count in summary["coverage"].items()],
        )
    )
    lines.append("")
    lines.append("## 1) Görev ve mod kararlarının doğruluğu")
    lines.append("")
    routing_rows = []
    for label, block in summary["routing"].items():
        routing_rows.append(
            [
                label,
                str(block["total"]),
                str(block["correct"]),
                str(block["accuracy"]) if block["accuracy"] is not None else "-",
                ", ".join(block["misses"]) or "-",
            ]
        )
    lines.append(
        _markdown_table(["Metrik", "Toplam", "Doğru", "Doğruluk", "Sapmalar"], routing_rows)
    )
    lines.append("")
    lines.append("## 2) İlgili bölümün bulunması")
    lines.append("")
    retrieval = summary["retrieval"]
    lines.append(
        _markdown_table(
            ["Yol", "Toplam", "İsabet", "İsabet oranı"],
            [
                ["Doğrudan retrieval sonda", str(retrieval["section_found"]["total"]), str(retrieval["section_found"]["hit"]), str(retrieval["section_found"]["hit_rate"])],
                ["Atıf hedefi beklenen bölüm", str(retrieval["section_cited"]["total"]), str(retrieval["section_cited"]["hit"]), str(retrieval["section_cited"]["hit_rate"])],
            ],
        )
    )
    lines.append("")
    lines.append("## 3) İddia–kanıt desteği ve hatalı kaynak oranı")
    lines.append("")
    citations = summary["citations"]
    lines.append(
        _markdown_table(
            ["Denetlenen koşu", "Toplam atıf", "Destekli atıf", "Destek oranı", "Hatalı kaynak oranı"],
            [[str(citations["audited_runs"]), str(citations["total_citations"]), str(citations["supported_citations"]), str(citations["claim_support_rate"]), str(citations["wrong_source_rate"])]],
        )
    )
    lines.append("")
    lines.append("## 4) Gecikme (test sağlayıcı — orkestrasyon yükü)")
    lines.append("")
    latency_rows = [
        [family, str(block["runs"]), str(block["p50_s"]), str(block["p95_s"]), str(block["mean_s"])]
        for family, block in summary["latency"]["families"].items()
    ]
    lines.append(_markdown_table(["Mod ailesi", "Koşu", "p50 (s)", "p95 (s)", "Ortalama (s)"], latency_rows))
    lines.append("")
    lines.append(f"> {summary['latency']['note']}")
    lines.append("")
    lines.append("## 5) Araştırma başına araç ve model kullanımı")
    lines.append("")
    research = summary["research_usage"]
    lines.append(
        _markdown_table(
            ["Koşu", "Etkin koşu", "Ort. model çağrısı", "Ort. arama", "Ort. araç", "Bütçe içi koşu"],
            [[str(research["runs"]), str(research["runs_with_activity"]), str(research["avg_model_calls"]), str(research["avg_web_search_calls"]), str(research["avg_tool_calls"]), str(research["within_budget_runs"])]],
        )
    )
    lines.append("")
    lines.append("## 6) Checkpoint'ten devam başarısı")
    lines.append("")
    resume = summary["resume"]
    lines.append(
        _markdown_table(
            ["Senaryo", "Başarılı", "Başarı oranı", "Başarısız"],
            [[str(resume["runs"]), str(resume["successful"]), str(resume["success_rate"]), ", ".join(resume["failed_case_ids"]) or "-"]],
        )
    )
    lines.append("")
    lines.append("## 7) Bütçe ve iptal davranışı")
    lines.append("")
    bc = summary["budget_cancel"]
    lines.append(
        _markdown_table(
            ["Örnek", "Beklenen davranış", "Doğruluk"],
            [[str(bc["cases"]), str(bc["expected_behavior"]), str(bc["accuracy"])]],
        )
    )
    lines.append("")
    lines.append("## Önbellek anahtar sözleşmesi (madde 5)")
    lines.append("")
    cache = summary["cache_policy"]
    lines.append(
        _markdown_table(
            ["Senaryo", "Denetim", "Geçen"],
            [[str(cache["cases"]), str(cache["checks"]), str(cache["passed"])]],
        )
    )
    lines.append("")
    lines.append("## Örnek başına sonuçlar")
    lines.append("")
    case_rows = []
    for record in case_results:
        failed = [check.name for check in record.checks if not check.ok]
        case_rows.append(
            [
                record.case_id,
                record.suite,
                "/".join(record.areas),
                "✓" if record.ok else "✗",
                ", ".join(failed) if failed else "-",
            ]
        )
    lines.append(_markdown_table(["ID", "Suite", "Kapsam", "Sonuç", "Başarısız denetim"], case_rows))
    lines.append("")
    lines.append("## Örnek başına bağımsız etiket gerekçeleri")
    lines.append("")
    case_by_id = {c.case_id: c for c in CASES}
    for record in case_results:
        case = case_by_id[record.case_id]
        lines.append(f"- **{case.case_id} — {case.title}**: {case.rationale}")
    lines.append("")
    return "\n".join(lines)


def write_report(case_results: list, report_dir: str | Path) -> dict:
    """JSON + Markdown raporu yazar; yazılan yolları döndürür."""
    summary = aggregate(case_results)
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "eval-report.json"
    md_path = out / "eval-report.md"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "suite_version": "a10-evals-v1",
        **summary,
        "cases": [r.as_dict() for r in case_results],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(case_results, summary), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "summary": summary}
