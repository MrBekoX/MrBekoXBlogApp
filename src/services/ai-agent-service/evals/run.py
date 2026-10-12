"""A10 değerlendirme koşucusunun komut satırı girişi.

Kullanım (hizmet kökü ``src/services/ai-agent-service`` içinden)::

    python -m evals.run --suite all --report out/evals
    python -m evals.run --suite routing --report out/evals-routing
    python -m evals.run --list

Dönen özet, plan A10 ölçü listesinin karşılığıdır ve rapor dosyalarıyla
konsol özetinde ``provider=test_executor`` işaretini taşır.
"""

from __future__ import annotations

import argparse
import json
import sys

from .dataset import CASES, SUITE_NAMES, cases_for_suite
from .harness import EvalRuntime, run_cases
from .report import write_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description="A10 agent kalite değerlendirmesini koşar (test sağlayıcı; gerçek sağlayıcı değildir).",
    )
    parser.add_argument(
        "--suite",
        default="all",
        choices=[*SUITE_NAMES, "all"],
        help="Koşulacak suite (varsayılan: all).",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Rapor dizini (eval-report.json + eval-report.md yazılır).",
    )
    parser.add_argument("--list", action="store_true", help="Kümedeki örnekleri listeler ve çıkar.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.list:
        for case in cases_for_suite(args.suite):
            areas = ",".join(case.areas)
            print(f"{case.case_id}\t{case.suite}\t{case.kind}\t{areas}\t{case.title}")
        print(f"toplam: {len(cases_for_suite(args.suite))} örnek (küme: {len(CASES)})", file=sys.stderr)
        return 0

    print(f"[evals] suite={args.suite} başlıyor (sağlayıcı: test_executor — gerçek sağlayıcı değildir)...")
    with EvalRuntime() as runtime:
        results = run_cases(args.suite, runtime=runtime)

    passed_cases = sum(1 for r in results if r.ok)
    print(f"[evals] {len(results)} örnek koştu; {passed_cases} örneğin tüm beklenti denetimleri geçti.")
    for record in results:
        if not record.ok:
            failed = ", ".join(check.name for check in record.checks if not check.ok)
            print(f"[evals] SAPIŞ: {record.case_id} — {failed}" + (f" — {record.error}" if record.error else ""))

    written: dict | None = None
    if args.report:
        written = write_report(results, args.report)
        summary = written["summary"]
        print(f"[evals] rapor: {written['json']}")
        print(f"[evals] rapor: {written['markdown']}")
        print(json.dumps({key: summary[key] for key in ("totals", "routing", "retrieval", "citations")}, ensure_ascii=False, indent=2))
    else:
        print("[evals] rapor dizini verilmedi; yalnız konsol özeti üretildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
