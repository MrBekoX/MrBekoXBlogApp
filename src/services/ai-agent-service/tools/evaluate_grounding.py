"""Opt-in real-model grounding acceptance over a public, versioned corpus.

The default command only validates corpus structure. It never loads .env files.
Model calls require BOTH the explicit CLI flag and AGENT_RUN_PAID_TESTS=1.
Offline stub-based unit tests prove protocol behavior, not semantic quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE / "app"))

CORPUS = SERVICE / "tests" / "grounding" / "corpus.json"
MAX_CASES = MAX_MODEL_CALLS = 9
MAX_TOTAL_TOKENS = 60000


def load_corpus(path: Path = CORPUS):
    cases = json.loads(path.read_text(encoding="utf-8"))
    required = {"id", "question", "source", "answer", "supported"}
    if not isinstance(cases, list) or len(cases) != MAX_CASES:
        raise ValueError(f"The complete corpus must contain all {MAX_CASES} cases")
    if any(not isinstance(case, dict) or set(case) != required or type(case["supported"]) is not bool
           or any(not isinstance(case[key], str) or not case[key].strip() for key in required - {"supported"})
           for case in cases) or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("The corpus contains invalid or duplicate cases")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid-provider-calls", action="store_true")
    parser.add_argument("--check-corpus", action="store_true")
    parser.add_argument("--scope", choices=("verifier", "full-pipeline", "all"), default="verifier")
    args = parser.parse_args()
    cases = load_corpus()
    from grounding_acceptance import load_pipeline_expectations, validate_cases
    validate_cases(cases)
    if args.scope != "verifier":
        load_pipeline_expectations(cases)
    if args.check_corpus or not args.allow_paid_provider_calls:
        print(json.dumps({"corpus_valid": True, "cases": len(cases), "provider_calls": 0}))
        return 0
    if os.environ.get("AGENT_RUN_PAID_TESTS") != "1":
        parser.error("Real provider calls require owner authorization and AGENT_RUN_PAID_TESTS=1")
    from grounding_acceptance import run_acceptance
    try:
        result = asyncio.run(run_acceptance(cases, args.scope))
    except Exception as error:
        # URLs, connection strings and provider errors can contain credentials.
        print(json.dumps({"passed": False, "scope": args.scope, "error": type(error).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
