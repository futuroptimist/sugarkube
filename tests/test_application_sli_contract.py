import copy
import json
from pathlib import Path

import pytest

from scripts import validate_application_slis as slis

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/observability/application-slis.json"
RULES = ROOT / "platform/observability/rules/application-slis.yaml"


def inventory():
    return json.loads(CONTRACT.read_text())


def test_contract_is_bounded_unmeasured_and_non_alerting():
    data = inventory()
    assert slis.validate(data) == 5
    assert all(item["objective"] is None for item in data["slis"])
    assert "alert:" not in RULES.read_text()


def mutate_sli(**values):
    data = copy.deepcopy(inventory())
    data["slis"][0].update(values)
    return data


def test_rejects_probe_as_real_traffic_substitution():
    with pytest.raises(slis.ContractError, match="probe cannot substitute"):
        slis.validate(mutate_sli(numerator="sum(probe_success)"))


def test_rejects_fabricated_objective():
    with pytest.raises(slis.ContractError, match="unreviewed numerical objective"):
        slis.validate(mutate_sli(objective=0.999))


def test_rejects_unconditional_zero_fallback():
    with pytest.raises(slis.ContractError, match="zero fallback"):
        slis.validate(mutate_sli(numerator="sum(rate(example[1h])) or vector(0)"))


def test_rejects_unsupported_retention_window():
    data = inventory()
    data["retention"] = "91d"
    with pytest.raises(slis.ContractError, match="retention exceeds"):
        slis.validate(data)


@pytest.mark.parametrize(
    ("arguments", "state"),
    [
        ({"eligible": 20, "failed": 2, "telemetry": "fresh", "complete": True}, "failed_eligible_traffic"),
        ({"eligible": 20, "failed": 0, "telemetry": "fresh", "complete": True}, "successful_eligible_traffic"),
        ({"eligible": 0, "failed": 0, "telemetry": "fresh", "complete": True}, "no_eligible_traffic"),
        ({"eligible": 0, "failed": 0, "telemetry": "absent", "complete": False}, "missing_or_stale_telemetry"),
        ({"eligible": 5, "failed": 0, "telemetry": "fresh", "complete": True, "reset": True}, "reset_or_incomplete_history"),
        ({"eligible": 5, "failed": 0, "telemetry": "fresh", "complete": False}, "reset_or_incomplete_history"),
        ({"eligible": 0, "failed": 0, "telemetry": "disabled", "complete": False}, "disabled"),
    ],
)
def test_request_window_states_cover_outage_recovery_idle_and_history(arguments, state):
    assert slis.classify_request_window(**arguments) == state


def test_rules_aggregate_multiple_replicas_and_do_not_create_budget():
    rules = RULES.read_text()
    assert "sum by (environment) (increase(dspace_http_requests_total" in rules
    assert "instance" not in rules and "pod" not in rules
    assert "error_budget" not in rules and "burn" not in rules
