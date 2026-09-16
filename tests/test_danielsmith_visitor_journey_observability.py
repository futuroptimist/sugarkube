"""Focused contracts for the disabled Daniel visitor-journey integration."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts import danielsmith_visitor_journey_metrics as metrics
from scripts import validate_probe_quotas as quotas
from scripts.generate_observability_dashboards import PROFILES, render

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/observability/danielsmith-visitor-journey.json"
RULES = ROOT / "platform/observability/rules/danielsmith-visitor-journey.yaml"


def contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def enabled_producer():
    producer = copy.deepcopy(contract()["producers"][0])
    producer["enabled"] = True
    producer["requestMultiplicity"] = 1
    return producer


def result(state="success", freshness=1_000, stage=None, duration=1250):
    return {
        "state": state,
        "freshness": freshness,
        "aggregateDurationMs": duration,
        "failureStage": stage,
    }


def test_descriptors_cover_both_environments_and_remain_inactive():
    value = contract()
    assert quotas.validate_visitor_journey_contract(value) == 2
    assert {item["environment"] for item in value["producers"]} == {"staging", "prod"}
    assert all(item["enabled"] is False for item in value["producers"])
    assert all(item["requestMultiplicity"] is None for item in value["producers"])


def test_enabled_descriptor_requires_qualified_multiplicity_and_enforces_quota():
    value = contract()
    value["producers"] = [enabled_producer()]
    quotas.validate_visitor_journey_contract(value)
    value["producers"][0]["requestMultiplicity"] = None
    with pytest.raises(quotas.ContractError, match="qualified requestMultiplicity"):
        quotas.validate_visitor_journey_contract(value)
    value["producers"][0]["requestMultiplicity"] = 5
    with pytest.raises(quotas.ContractError, match="unsafe visitor journey schedule"):
        quotas.validate_visitor_journey_contract(value)


def test_contract_rejects_cadence_timeout_and_vocabulary_drift():
    for mutate, message in (
        (lambda p: p.update(timeout="5m"), "shorter than cadence"),
        (lambda p: p["failureStages"].append("response_body"), "application vocabulary"),
        (lambda p: p["optionalRendererStates"].append("webgl_details"), "finite vocabulary"),
    ):
        value = contract()
        mutate(value["producers"][0])
        with pytest.raises(quotas.ContractError, match=message):
            quotas.validate_visitor_journey_contract(value)


def test_disabled_unavailable_success_failure_stale_and_recovery_are_distinct():
    disabled = contract()["producers"][0]
    text = metrics.render_metrics(disabled, now=1_000)
    assert 'state="disabled"' in text and "_success{" not in text
    producer = enabled_producer()
    assert 'state="unavailable"' in metrics.render_metrics(producer, now=1_000)
    assert 'state="successful"' in metrics.render_metrics(producer, result(), now=1_001)
    failed = result("failure", stage="javascript_initialization")
    assert 'state="failed"' in metrics.render_metrics(producer, failed, now=1_001)
    assert 'failure_stage="javascript_initialization"' in metrics.render_metrics(
        producer, failed, now=1_001
    )
    assert 'state="stale"' in metrics.render_metrics(producer, result(freshness=1), now=1_000)
    recovered = metrics.render_metrics(producer, result(), previous_result=failed, now=1_001)
    assert 'state="recovered"' in recovered


def test_optional_renderer_is_separate_from_essential_success():
    text = metrics.render_metrics(
        enabled_producer(), result(), optional_renderer_state="unavailable", now=1_001
    )
    assert "danielsmith_visitor_journey_success{" in text
    assert "danielsmith_optional_renderer_state{" in text
    assert 'state="unavailable"' in text
    with pytest.raises(ValueError, match="optional renderer state"):
        metrics.render_metrics(
            enabled_producer(), result(), optional_renderer_state="driver_error", now=1_001
        )


def test_metric_input_is_exact_bounded_and_sanitized():
    assert metrics.validate_result(result(), now=1_001) == result()
    for key, value in (
        ("responseBody", "private"),
        ("visitor", "identity"),
        ("url", "https://example/?id=x"),
    ):
        bad = {**result(), key: value}
        with pytest.raises(ValueError, match="exact sanitized schema"):
            metrics.validate_result(bad, now=1_001)
    for duration in (float("nan"), float("inf"), -1):
        with pytest.raises(ValueError, match="aggregate duration"):
            metrics.validate_result(result(duration=duration), now=1_001)
    with pytest.raises(ValueError, match="bounded failure stage"):
        metrics.validate_result(result("failure", stage="exception text"), now=1_001)


def test_generated_dashboards_and_rules_cover_the_bounded_contract():
    for profile in PROFILES.values():
        document = json.loads(render(profile))
        titles = {panel["title"] for panel in document["panels"]}
        assert {
            "Daniel visitor journey",
            "Daniel journey lifecycle",
            "Daniel journey result and freshness",
            "Daniel journey duration",
            "Daniel failure stage",
            "Daniel optional renderer",
        } <= titles
    groups = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]
    expressions = "\n".join(rule["expr"] for group in groups for rule in group["rules"])
    assert "danielsmith_visitor_journey_monitoring_enabled" in expressions
    assert "danielsmith_visitor_journey_lifecycle_state" in expressions
    assert 'state=~"failed|stale|unavailable"' in expressions
    assert "danielsmith_optional_renderer_state" not in expressions
