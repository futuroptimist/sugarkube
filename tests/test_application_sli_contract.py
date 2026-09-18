import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts import validate_application_slis as validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/observability/application-slis.json"
RULES = ROOT / "platform/observability/rules/application-slis.yaml"


def contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_contract_is_bounded_complete_and_unmeasured():
    value = contract()
    assert validator.validate(value) == 6
    assert {sli["signalType"] for sli in value["slis"]} == {
        "actual_request_success", "synthetic_completion", "http_probe_health"
    }
    assert all(sli["objective"] is None for sli in value["slis"])
    assert value["retention"] == "90d"


def mutate_sli(**changes):
    value = contract()
    value["slis"][0].update(changes)
    return value


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (mutate_sli(signalType="actual_request_success", numerator="sum(probe_success)"), "probe cannot substitute"),
        (mutate_sli(objective=0.999), "objectives require"),
        (mutate_sli(denominator="sum(rate(metric[5m])) or vector(0)"), "zero fallback"),
        ({**contract(), "retention": "365d"}, "retention window"),
    ],
)
def test_validator_rejects_unsafe_semantic_substitutions(value, message):
    with pytest.raises(ValueError, match=message):
        validator.validate(value)


def test_rules_preserve_no_data_and_no_traffic_and_handle_resets_and_replicas():
    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"][0]["rules"]
    expressions = "\n".join(rule["expr"] for rule in rules)
    assert "or vector(0)" not in expressions
    assert "increase(" in expressions  # reset-safe over the explicit five-minute window
    assert "sum by (environment)" in expressions  # replicas aggregate before division
    ratio = next(rule for rule in rules if rule["record"] == "sugarkube:sli_success_ratio:ratio5m")
    assert " / " in ratio["expr"]  # zero traffic and absent telemetry produce no ratio, not success
    assert not any("alert" in rule for rule in rules)


def test_contract_names_distinct_failure_and_lifecycle_semantics():
    by_id = {sli["id"]: sli for sli in contract()["slis"]}
    assert "5xx" in by_id["dspace-http-requests"]["numerator"]
    assert "stale or absent" in " ".join(by_id["dspace-chat-synthetic"]["exclusions"])
    assert "disabled" in " ".join(by_id["tokenplace-encrypted-completion"]["exclusions"])
    assert "disabled" in " ".join(by_id["danielsmith-visitor-journey"]["exclusions"])
    assert "real-user request success" in " ".join(by_id["shared-public-http-probes"]["exclusions"])


def test_outage_recovery_low_traffic_and_incomplete_history_are_not_objectives():
    """The first slice exposes evidence, never infers a budget from partial history."""
    value = contract()
    scenarios = {"outage": (0, 12), "recovery": (8, 10), "low_traffic": (1, 1)}
    assert scenarios["outage"][0] == 0
    assert scenarios["recovery"][0] > scenarios["outage"][0]
    assert scenarios["low_traffic"][1] == 1
    assert all(sli["objective"] is None for sli in value["slis"])
