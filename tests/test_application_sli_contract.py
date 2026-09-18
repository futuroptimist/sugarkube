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


def test_contract_is_bounded_complete_and_explicitly_unmeasured():
    value = contract()
    assert validator.validate(value) == 7
    assert {sli["signalType"] for sli in value["slis"]} == validator.SIGNALS
    assert all(sli["objective"] is None for sli in value["slis"])
    assert all(sli["measurementState"] == "unmeasured" for sli in value["slis"])
    assert all(
        {"userJourney", "dataSource", "numerator", "denominator", "exclusions", "observationWindow"}
        <= sli.keys()
        for sli in value["slis"]
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda sli, doc: sli.update(dataSource="probe_success", numerator="probe_success"),
            "substitute|probe cannot",
        ),
        (lambda sli, doc: sli.update(objective=0.999), "no reviewed numerical objective"),
        (lambda sli, doc: sli.update(denominator="sum(metric) or vector(0)"), "zero fallback"),
        (lambda sli, doc: doc.update(retention="91d"), "90d maximum"),
        (lambda sli, doc: sli.update(observationWindow="91d"), "supported retention"),
    ],
)
def test_validator_rejects_unsafe_or_fabricated_contracts(mutation, message):
    value = copy.deepcopy(contract())
    actual = next(sli for sli in value["slis"] if sli["signalType"] == "actual_request_success")
    mutation(actual, value)
    with pytest.raises(validator.ContractError, match=message):
        validator.validate(value)


def test_recordings_are_non_alerting_reset_aware_replica_aggregates_without_zero_fallback():
    document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    rules = document["groups"][0]["rules"]
    assert rules and all("record" in rule and "alert" not in rule for rule in rules)
    expressions = "\n".join(rule["expr"] for rule in rules)
    assert "increase(" in expressions
    assert "sum by (environment)" in expressions
    assert "instance" not in expressions and "pod" not in expressions
    assert "vector(0)" not in expressions and "probe_success" not in expressions
    assert "> 0" in expressions  # no eligible traffic remains absent rather than successful


def test_dashboard_keeps_signal_classes_separate_and_budget_unmeasured():
    path = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"
    dashboard = json.loads(path.read_text())
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    success = panels["Actual-request success (1h observation)"]
    expression = success["targets"][0]["expr"]
    assert "sli_successful_events" in expression and "probe_success" not in expression
    assert success["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
    budget = panels["Error budget and burn"]
    assert "UNMEASURED — NO DATA" in budget["options"]["content"]
    assert not budget.get("targets")


def test_semantics_name_all_required_lifecycle_states():
    text = (ROOT / "docs/application-slis.md").read_text(encoding="utf-8").lower()
    for phrase in (
        "successful eligible traffic", "no eligible traffic", "missing telemetry",
        "incomplete history", "intentionally disabled monitoring", "failed eligible traffic",
    ):
        assert phrase in text
