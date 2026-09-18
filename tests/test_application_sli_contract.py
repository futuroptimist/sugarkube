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
    assert validator.validate(value) == 8
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
        (lambda sli, doc: sli.update(application=""), "non-empty string"),
        (lambda sli, doc: sli.update(exclusions=[""]), "non-empty string list"),
        (lambda sli, doc: sli.update(observationWindow="60minutes"), "invalid duration"),
        (
            lambda sli, doc: sli.update(numerator="sum(metric) or on(environment) 0 * sum(metric)"),
            "eligible-traffic predicate",
        ),
    ],
)
def test_validator_rejects_unsafe_or_fabricated_contracts(mutation, message):
    value = copy.deepcopy(contract())
    actual = next(sli for sli in value["slis"] if sli["signalType"] == "actual_request_success")
    mutation(actual, value)
    with pytest.raises(validator.ContractError, match=message):
        validator.validate(value)


def test_recordings_are_non_alerting_reset_aware_and_guarded_by_complete_fresh_history():
    document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    rules = document["groups"][0]["rules"]
    assert rules and all("record" in rule and "alert" not in rule for rule in rules)
    expressions = "\n".join(rule["expr"] for rule in rules)
    assert "increase(" in expressions
    assert "sum by (environment)" in expressions
    assert "kube_pod_container_status_ready" in expressions
    assert "kube_pod_status_phase" in expressions
    assert "unless on (namespace, pod) kube_pod_deletion_timestamp" in expressions
    assert "count ((kube_pod_" in expressions
    assert "vector(0)" not in expressions and "probe_success" not in expressions
    assert "count_over_time(" in expressions and ">= 120" in expressions
    assert "resets(" in expressions
    assert any(rule["record"] == "sugarkube:sli_observation_state" for rule in rules)
    assert "sli_source_current" in expressions
    assert "sli_source_history_complete" in expressions
    assert "count_over_time(up{" in expressions
    assert "> 0" in expressions  # no eligible traffic remains absent rather than successful


def test_expected_ready_sources_are_matched_for_current_and_full_window_coverage():
    expressions = RULES.read_text(encoding="utf-8")
    for namespace, container in (("tokenplace", "relay"), ("dspace", "dspace")):
        selector = f'kube_pod_container_status_ready{{namespace="{namespace}",container="{container}"}}'
        assert selector in expressions
        assert f"max_over_time({selector}[1h])" in expressions
    assert expressions.count("and on (namespace, pod)") >= 8
    assert "count by (environment) ((kube_pod_" not in expressions


def test_missing_telemetry_state_is_derived_from_expected_ready_sources():
    document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    missing_rules = [
        rule for rule in document["groups"][0]["rules"]
        if rule.get("labels", {}).get("observation_state") == "missing_or_stale_telemetry"
    ]
    assert len(missing_rules) == 2
    for rule in missing_rules:
        assert "kube_pod_container_status_ready" in rule["expr"]
        assert "sli_source_current" in rule["expr"]
        assert "up{" not in rule["expr"]


def test_success_recordings_have_only_an_eligible_traffic_zero_fallback():
    document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    success_rules = [
        rule for rule in document["groups"][0]["rules"]
        if "sli_successful_events" in rule["record"]
    ]
    assert len(success_rules) == 2
    for rule in success_rules:
        assert "0 * (sum by (environment) (increase(" in rule["expr"]
        assert "> 0" in rule["expr"]


def test_observation_states_are_exclusive_and_contract_labelled():
    document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    states = [rule for rule in document["groups"][0]["rules"] if rule["record"].endswith("observation_state")]
    assert {rule["labels"]["observation_state"] for rule in states} == {
        "successful_eligible_traffic", "failed_eligible_traffic", "no_eligible_traffic",
        "missing_or_stale_telemetry", "reset_or_incomplete_history",
        "intentionally_disabled_monitoring",
    }
    assert all({"application", "sli", "signal_type", "observation_state"} <= rule["labels"].keys() for rule in states)
    identities = {(rule["labels"]["sli"], rule["labels"]["signal_type"]) for rule in states}
    assert identities == {
        ("tokenplace-request-success", "actual_request_success"),
        ("dspace-chat-request-success", "actual_request_success"),
        ("tokenplace-encrypted-completion", "synthetic_completion"),
    }
    assert sum(rule["labels"]["signal_type"] == "actual_request_success" for rule in states) == 10


def test_dashboard_keeps_signal_classes_separate_and_budget_unmeasured():
    path = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"
    dashboard = json.loads(path.read_text())
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    success = panels["Application SLI observation state"]
    expression = success["targets"][0]["expr"]
    assert "sli_observation_state" in expression and "probe_success" not in expression
    assert success["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
    assert "two actual-request SLIs" in success["description"]
    assert "probe, DSPACE synthetic, and Daniel visitor panels" in success["description"]
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
