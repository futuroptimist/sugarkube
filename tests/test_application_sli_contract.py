import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts.validate_application_slis import (
    classify_counter_window,
    classify_synthetic,
    validate_document,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "platform/observability/application-slis.json"
RULES = ROOT / "platform/observability/rules/application-slis.yaml"


def contract():
    return json.loads(CONTRACT.read_text())


def test_contract_is_valid_and_keeps_signal_types_separate():
    document = contract()
    validate_document(document)
    assert {sli["signalType"] for sli in document["slis"]} == {
        "http_probe_health",
        "synthetic_completion",
        "actual_request_success",
    }
    assert document["objectives"]["target"] is None


@pytest.mark.parametrize(
    ("denominator", "numerator", "complete", "reset", "state"),
    [
        (10, 10, True, False, "successful_eligible_traffic"),
        (10, 8, True, False, "failed_eligible_traffic"),
        (0, 0, True, False, "no_eligible_traffic"),
        (None, None, True, False, "missing_or_stale_telemetry"),
        (10, 10, False, False, "reset_or_incomplete_history"),
        (10, 10, True, True, "reset_or_incomplete_history"),
        (20, 19, True, False, "failed_eligible_traffic"),
    ],
)
def test_request_window_states(denominator, numerator, complete, reset, state):
    assert (
        classify_counter_window(
            denominator=denominator, numerator=numerator, complete=complete, reset=reset
        )
        == state
    )


def test_disabled_and_recovered_synthetic_states():
    assert (
        classify_synthetic(expected=False, enabled=False, fresh=None, success=None)
        == "intentionally_disabled"
    )
    assert (
        classify_synthetic(expected=True, enabled=True, fresh=False, success=True)
        == "missing_or_stale_telemetry"
    )
    assert (
        classify_synthetic(expected=True, enabled=True, fresh=True, success=False)
        == "failed_eligible_traffic"
    )
    assert (
        classify_synthetic(expected=True, enabled=True, fresh=True, success=True)
        == "successful_eligible_traffic"
    )


def test_multiple_replica_outage_and_recovery_are_aggregated_before_classification():
    replica_denominators = [12, 8]
    outage_successes = [12, 6]
    recovery_successes = [12, 8]
    assert (
        classify_counter_window(
            denominator=sum(replica_denominators),
            numerator=sum(outage_successes),
            complete=True,
            reset=False,
        )
        == "failed_eligible_traffic"
    )
    assert (
        classify_counter_window(
            denominator=sum(replica_denominators),
            numerator=sum(recovery_successes),
            complete=True,
            reset=False,
        )
        == "successful_eligible_traffic"
    )


@pytest.mark.parametrize("mutation", ["probe", "objective", "zero", "retention"])
def test_validator_rejects_unsafe_contracts(mutation):
    document = copy.deepcopy(contract())
    if mutation == "probe":
        next(s for s in document["slis"] if s["signalType"] == "actual_request_success")[
            "dataSource"
        ] = "probe_success"
    elif mutation == "objective":
        document["objectives"].update(state="measured", target=0.999)
    elif mutation == "zero":
        next(s for s in document["slis"] if s["signalType"] == "actual_request_success")[
            "dataSource"
        ] += " or vector(0)"
    else:
        document["slis"][0]["observationWindow"] = "30d"
    with pytest.raises(ValueError):
        validate_document(document)


def test_rules_are_recording_only_and_aggregate_replicas():
    rules = yaml.safe_load(RULES.read_text())["groups"][0]["rules"]
    assert all("alert" not in rule for rule in rules)
    assert all("probe_success" not in rule["expr"] for rule in rules)
    request_rules = [rule for rule in rules if "increase(" in rule["expr"]]
    assert len(request_rules) == 4
    assert all("sum without (instance, pod, job)" in rule["expr"] for rule in request_rules)
    assert all("or vector(0)" not in rule["expr"] for rule in rules)
