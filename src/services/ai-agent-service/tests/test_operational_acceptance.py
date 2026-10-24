"""Operational acceptance cannot turn missing/live-unmeasured data into a pass."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location("operational_acceptance",Path(__file__).parents[1]/"tools"/"operational_acceptance.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

POLICY={"max_p95_run_seconds":30,"max_failure_fraction":0.05,"max_peak_memory_fraction":0.85,
        "max_outbox_age_seconds":20,"max_dead_letters":0,"minimum_runs":20,"minimum_memory_samples":20}
COMMIT="a"*40


def assess(data):
    return module.assess(data,POLICY,expected_commit=COMMIT)


def evidence():
    return {"kind":"agent-operational-evidence-v1","live_target_measured":True,
        "commit":COMMIT,"collected_at":datetime.now(timezone.utc).isoformat(),
        "target_instance_type":"t3.micro","approved_load_scenario":True,
        "runs":[{"status":"completed","duration_seconds":10} for _ in range(20)],
        "host_memory_fractions":[0.5]*20,"oldest_outbox_age_seconds":2,"dead_letters_delta":0}


def test_complete_evidence_is_compared_to_all_thresholds():
    result=assess(evidence())
    assert result["status"]=="passed" and len(result["checks"])==5


@pytest.mark.parametrize("field,value",[("live_target_measured",False),("target_instance_type","local"),
    ("approved_load_scenario",False),("runs",[]),("host_memory_fractions",[]),("dead_letters_delta",None)])
def test_missing_live_evidence_never_passes(field,value):
    data=evidence();data[field]=value
    assert assess(data)["status"]=="not_measured"


@pytest.mark.parametrize("field,value",[("host_memory_fractions",[0.99]*20),
    ("oldest_outbox_age_seconds",100),("dead_letters_delta",1),
    ("runs",[{"status":"failed","duration_seconds":100}]*20)])
def test_actual_threshold_breach_fails(field,value):
    data=evidence();data[field]=value
    assert assess(data)["status"]=="failed"


def test_sensitive_or_nonfinite_sample_fields_are_rejected():
    data=evidence();data["runs"][0]["question"]="must-never-appear-in-an-artifact"
    with pytest.raises(ValueError):assess(data)
    data=evidence();data["runs"][0]["duration_seconds"]=float("nan")
    with pytest.raises(ValueError):assess(data)


def test_old_or_different_revision_cannot_be_certified():
    data=evidence();data["commit"]="b"*40
    assert assess(data)["status"]=="not_measured"
    data=evidence();data["collected_at"]="2020-01-01T00:00:00+00:00"
    assert assess(data)["status"]=="not_measured"
    assert module.assess(evidence(),POLICY)["status"]=="not_measured"


def test_host_memory_uses_available_headroom_including_os_services():
    assert module.memory_fraction("MemTotal: 1024 kB\nMemAvailable: 256 kB\n")==0.75
    with pytest.raises(ValueError):module.memory_fraction("MemTotal: 0 kB")


@pytest.mark.parametrize("status",["partial","partially_completed","PartiallyCompleted"])
def test_partial_research_is_counted_as_non_success_not_invalid_evidence(status):
    data=evidence();data["runs"][0]["status"]=status
    result=assess(data)
    assert result["observed"]["failure_fraction"]==0.05
    assert result["status"]=="passed"


@pytest.mark.parametrize("status",[None,[],{},1])
def test_malformed_terminal_status_is_rejected_without_attribute_errors(status):
    data=evidence();data["runs"][0]["status"]=status
    with pytest.raises(ValueError,match="terminal"):
        assess(data)
