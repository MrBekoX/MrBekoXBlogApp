"""Collect host memory or assess explicitly supplied operational evidence.

This tool never starts/deploys services, reads dotenv, calls a provider or sends
traffic. Run the memory collector on the intended host while an approved load
scenario is running. Assessment fails closed when live evidence is missing.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time


def _number(value, name, *, minimum=0, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"Invalid {name}")
    if maximum is not None and value > maximum:
        raise ValueError(f"Invalid {name}")
    return float(value)


def assess(evidence: dict, policy: dict, *, expected_commit: str | None = None) -> dict:
    """Return aggregate results only; never echo questions, IDs or credentials."""
    if not isinstance(evidence,dict) or not isinstance(policy,dict):
        raise ValueError("Evidence and policy must be objects")
    fields = {"max_p95_run_seconds", "max_failure_fraction", "max_peak_memory_fraction",
              "max_outbox_age_seconds", "max_dead_letters", "minimum_runs", "minimum_memory_samples"}
    if set(policy) != fields:
        raise ValueError("Supply every operational threshold explicitly")
    limits = {key: _number(value,key) for key,value in policy.items()}
    for key in ("max_failure_fraction", "max_peak_memory_fraction"):
        _number(limits[key],key,maximum=1)
    for key in ("minimum_runs", "minimum_memory_samples"):
        if type(policy[key]) is not int or policy[key] < 2:
            raise ValueError(f"{key} must be an integer of at least two")
    if evidence.get("kind") != "agent-operational-evidence-v1":
        raise ValueError("Invalid operational evidence kind")
    missing = []
    if expected_commit is None or not re.fullmatch(r"[0-9a-f]{40}",expected_commit):
        missing.append("expected_revision_not_selected")
    elif evidence.get("commit") != expected_commit:
        missing.append("measured_revision_does_not_match")
    try:
        stamp=evidence.get("collected_at","")
        if not isinstance(stamp,str):
            raise ValueError("Invalid timestamp")
        collected=datetime.fromisoformat(stamp.replace("Z","+00:00"))
        age=(datetime.now(timezone.utc)-collected).total_seconds()
        if not 0 <= age <= 86400:
            missing.append("measurement_is_not_recent")
    except (ValueError,TypeError):
        missing.append("measurement_time_missing_or_invalid")
    if evidence.get("live_target_measured") is not True:
        missing.append("live_target_not_measured")
    if evidence.get("target_instance_type") != "t3.micro":
        missing.append("target_instance_not_verified")
    if evidence.get("approved_load_scenario") is not True:
        missing.append("approved_load_scenario_not_recorded")
    runs = evidence.get("runs",[])
    memory = evidence.get("host_memory_fractions",[])
    if not isinstance(runs,list) or not isinstance(memory,list) or len(runs)>10000 or len(memory)>100000:
        raise ValueError("Invalid or oversized evidence samples")
    if len(runs) < limits["minimum_runs"]:
        missing.append("insufficient_completed_run_samples")
    if len(memory) < limits["minimum_memory_samples"]:
        missing.append("insufficient_host_memory_samples")
    durations = []
    failures = 0
    for run in runs:
        if not isinstance(run,dict) or set(run) != {"duration_seconds","status"}:
            raise ValueError("Run evidence accepts aggregate duration/status only")
        durations.append(_number(run["duration_seconds"],"run duration"))
        status=run["status"].casefold() if isinstance(run["status"],str) else ""
        if status not in ("completed","failed","cancelled","partial","partially_completed","partiallycompleted"):
            raise ValueError("Run evidence must be terminal")
        # Partial research is a legitimate terminal result, but not a full
        # success for this explicit success-rate acceptance objective.
        failures += status != "completed"
    fractions = [_number(value,"host memory fraction",maximum=1) for value in memory]
    outbox_age = evidence.get("oldest_outbox_age_seconds")
    dead_letters = evidence.get("dead_letters_delta")
    if outbox_age is None or dead_letters is None:
        missing.append("outbox_or_dead_letter_measurement_missing")
    if missing:
        return {"status":"not_measured","missing":missing,"runs":len(runs),"memory_samples":len(memory)}
    ordered = sorted(durations)
    p95 = ordered[max(0,math.ceil(len(ordered)*0.95)-1)]
    observed = {
        "p95_run_seconds":p95,
        "failure_fraction":failures/len(runs),
        "peak_memory_fraction":max(fractions),
        "oldest_outbox_age_seconds":_number(outbox_age,"outbox age"),
        "dead_letters_delta":_number(dead_letters,"dead-letter delta"),
    }
    checks = {
        "latency":p95 <= limits["max_p95_run_seconds"],
        "failure_rate":observed["failure_fraction"] <= limits["max_failure_fraction"],
        "memory_headroom":observed["peak_memory_fraction"] <= limits["max_peak_memory_fraction"],
        "outbox_age":observed["oldest_outbox_age_seconds"] <= limits["max_outbox_age_seconds"],
        "dead_letters":observed["dead_letters_delta"] <= limits["max_dead_letters"],
    }
    return {"status":"passed" if all(checks.values()) else "failed","checks":checks,
            "observed":observed,"runs":len(runs),"memory_samples":len(memory)}


def memory_fraction(text: str) -> float:
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] in ("MemTotal:","MemAvailable:"):
            values[parts[0][:-1]] = int(parts[1])
    total, available = values.get("MemTotal",0),values.get("MemAvailable",-1)
    if total <= 0 or available < 0 or available > total:
        raise ValueError("Host memory counters are unavailable")
    return (total-available)/total


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    collect=commands.add_parser("collect-memory",help="Read host memory only; no load or model traffic")
    collect.add_argument("--seconds",type=int,default=120)
    collect.add_argument("--output",type=Path,required=True)
    check=commands.add_parser("assess",help="Evaluate supplied live evidence against explicit product thresholds")
    check.add_argument("--evidence",type=Path,required=True)
    check.add_argument("--policy",type=Path,required=True)
    check.add_argument("--expected-commit",required=True)
    args=parser.parse_args(argv)
    try:
        if args.command == "collect-memory":
            if not 2 <= args.seconds <= 3600:
                raise ValueError("Collection duration must be between 2 and 3600 seconds")
            if args.output.exists() or args.output.suffix != ".json":
                raise ValueError("Use a new JSON evidence file")
            samples=[]
            for _ in range(args.seconds):
                samples.append(memory_fraction(Path("/proc/meminfo").read_text(encoding="ascii")))
                time.sleep(1)
            with args.output.open("x",encoding="utf-8") as stream:
                json.dump({"kind":"host-memory-samples-v1",
                    "collected_at":datetime.now(timezone.utc).isoformat(),"host_memory_fractions":samples},stream)
            return 0
        evidence=json.loads(args.evidence.read_text(encoding="utf-8"))
        policy=json.loads(args.policy.read_text(encoding="utf-8"))
        result=assess(evidence,policy,expected_commit=args.expected_commit)
        print(json.dumps(result,sort_keys=True))
        return 0 if result["status"]=="passed" else 2
    except (ValueError,OSError,KeyError,TypeError):
        print(json.dumps({"status":"invalid_evidence","error":"Cannot assess the supplied evidence safely"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
