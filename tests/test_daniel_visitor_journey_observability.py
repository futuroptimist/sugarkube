import copy
import json
import math
from pathlib import Path

import pytest
import yaml

from scripts import daniel_visitor_journey_metrics as metrics
from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/observability/daniel-visitor-journey.json"
RULES = ROOT / "monitoring/prometheusrules/app-uptime.yaml"
DASHBOARD = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"


@pytest.fixture
def contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


@pytest.fixture
def producer(contract):
    return copy.deepcopy(contract["producers"][0])


def result(state="success", *, freshness=1_000, duration=125, stage=None):
    return {
        "state": state,
        "freshness": freshness,
        "aggregateDurationMs": duration,
        "failureStage": stage,
    }


def test_contract_is_disabled_for_both_environments_and_validates(contract):
    assert [(item["environment"], item["enabled"]) for item in contract["producers"]] == [
        ("staging", False),
        ("prod", False),
    ]
    assert all(item["requestMultiplicity"] is None for item in contract["producers"])
    assert quotas.validate_visitor_contract(contract) == 2


def test_enabled_contract_requires_multiplicity_and_enforces_quota(contract):
    enabled = copy.deepcopy(contract)
    for item in enabled["producers"]:
        item["enabled"] = True
    with pytest.raises(quotas.ContractError, match="requires requestMultiplicity"):
        quotas.validate_visitor_contract(enabled)
    for item in enabled["producers"]:
        item["requestMultiplicity"] = 1
        item["cadence"] = "61s"
    with pytest.raises(quotas.ContractError, match="unsafe completion schedule"):
        quotas.validate_visitor_contract(enabled)


def test_contract_rejects_drift_from_application_stage_vocabulary(contract):
    contract["producers"][0]["failureStages"][0] = "invented"
    with pytest.raises(quotas.ContractError, match="application vocabulary"):
        quotas.validate_visitor_contract(contract)


def test_disabled_and_unavailable_are_not_success(producer):
    disabled = metrics.render_metrics(producer, now=1_000)
    assert 'state="disabled"' in disabled
    assert "daniel_visitor_journey_success" not in disabled
    producer["enabled"] = True
    unavailable = metrics.render_metrics(producer, now=1_000)
    assert 'state="unavailable"' in unavailable
    assert "daniel_visitor_journey_success" not in unavailable


def test_success_failure_stale_and_recovery_are_distinct(producer):
    producer["enabled"] = True
    successful = metrics.render_metrics(producer, result(), now=1_010)
    failed = metrics.render_metrics(
        producer,
        result("failure", stage="resume_pdf"),
        now=1_010,
    )
    stale = metrics.render_metrics(producer, result(), now=2_000)
    recovered = metrics.render_metrics(producer, result(), now=1_010, previous_failed=True)
    assert 'state="successful"' in successful
    assert 'state="failed"' in failed and 'failure_stage="resume_pdf"' in failed
    assert 'state="stale"' in stale
    assert 'state="recovered"' in recovered


def test_optional_renderer_remains_separate_from_essential_success(producer):
    producer["enabled"] = True
    producer["optionalRendererEnabled"] = True
    rendered = metrics.render_metrics(
        producer, result(), now=1_010, optional_renderer_state="failure"
    )
    assert "daniel_visitor_journey_success" in rendered
    assert "daniel_visitor_journey_optional_renderer_state{" in rendered
    assert 'state="failure"' in rendered


@pytest.mark.parametrize("value", [math.nan, math.inf, -1])
def test_nonfinite_or_negative_metric_values_fail_closed(producer, value):
    producer["enabled"] = True
    with pytest.raises(ValueError):
        metrics.render_metrics(producer, result(duration=value), now=1_010)


def test_unknown_fields_and_sensitive_labels_are_rejected(producer):
    producer["enabled"] = True
    evidence = result()
    evidence["responseBody"] = "private"
    with pytest.raises(ValueError, match="exact sanitized schema"):
        metrics.render_metrics(producer, evidence, now=1_010)
    rendered = metrics.render_metrics(producer, result(), now=1_010)
    assert all(label not in rendered for label in ("visitor=", "url=", "request_id="))


def test_generated_dashboard_contains_bounded_panels_and_separation():
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    panels = {item["title"]: item for item in dashboard["panels"]}
    expected = {
        "Daniel visitor journey lifecycle",
        "Daniel visitor journey success and freshness",
        "Daniel visitor journey result age",
        "Daniel visitor journey duration",
        "Daniel visitor journey failure and optional renderer",
    }
    assert expected <= panels.keys()
    expressions = json.dumps([panels[title]["targets"] for title in expected])
    assert "daniel_visitor_journey_failure_stage" in expressions
    assert "daniel_visitor_journey_optional_renderer_state" in expressions


def test_alerts_gate_on_enablement_and_keep_optional_renderer_noncritical():
    groups = yaml.safe_load(RULES.read_text(encoding="utf-8"))["spec"]["groups"]
    rules = {rule["alert"]: rule for group in groups for rule in group["rules"]}
    for name in (
        "DanielVisitorJourneyFailed",
        "DanielVisitorJourneyStale",
        "DanielOptionalRendererUnavailable",
    ):
        assert "daniel_visitor_journey_monitoring_enabled" in rules[name]["expr"]
    assert rules["DanielVisitorJourneyFailed"]["labels"]["severity"] == "critical"
    assert rules["DanielOptionalRendererUnavailable"]["labels"]["severity"] == "warning"
