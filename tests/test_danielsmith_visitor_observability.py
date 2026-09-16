import copy
import json
import math
from pathlib import Path

import pytest
import yaml

from scripts import danielsmith_visitor_metrics as metrics
from scripts import validate_probe_quotas as quotas
from scripts.generate_observability_dashboards import PROFILES, render

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/observability/danielsmith-visitor-journey.json"
RULES = ROOT / "platform/observability/rules/danielsmith-visitor-journey.yaml"
STAGES = {
    "homepage_delivery",
    "javascript_initialization",
    "essential_assets",
    "accessible_fallback",
    "resume_pdf",
    "timeout",
    "producer_interrupted",
}


def inventory():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def producer(enabled=True):
    value = copy.deepcopy(inventory()["producers"][0])
    value["enabled"] = enabled
    value["requestMultiplicity"] = 7 if enabled else None
    return value


def result(**updates):
    value = {
        "state": "success",
        "freshness": 1_000,
        "aggregateDurationMs": 1234.5,
        "failureStage": None,
    }
    value.update(updates)
    return value


def test_descriptor_is_pinned_disabled_and_quota_validated():
    data = inventory()
    assert data["sourceRevision"] == "7c972a57d5235591b0449d5d2a81dd8359bd97a5"
    assert {(p["environment"], p["enabled"]) for p in data["producers"]} == {
        ("staging", False),
        ("prod", False),
    }
    assert all(
        (p["cadence"], p["timeout"], p["concurrency"]) == ("15m", "120s", 1)
        for p in data["producers"]
    )
    assert all(set(p["failureStages"]) == STAGES for p in data["producers"])
    assert quotas.validate_visitor_contract(data) == 2


def test_descriptor_fails_closed_for_contract_drift_and_unsafe_schedule():
    data = inventory()
    data["sourceRevision"] = "0" * 40
    with pytest.raises(quotas.ContractError, match="source revision"):
        quotas.validate_visitor_contract(data)
    data = inventory()
    data["producers"][0].update(enabled=True, requestMultiplicity=1000, cadence="121s")
    with pytest.raises(quotas.ContractError, match="unsafe completion schedule"):
        quotas.validate_visitor_contract(data)


def test_disabled_unavailable_success_failure_stale_and_recovery_are_distinct():
    disabled = metrics.render_metrics(producer(False), now=1_010)
    assert 'monitoring_enabled{application="danielsmith",environment="staging"' in disabled
    assert 'state="disabled"} 1' in disabled and "_success{" not in disabled
    assert 'state="unavailable"} 1' in metrics.render_metrics(producer(), now=1_010)
    success = metrics.render_metrics(producer(), result(), now=1_010)
    assert 'state="success"} 1' in success and "_success{" in success
    failed = result(state="failure", failureStage="resume_pdf")
    assert 'state="failure"} 1' in metrics.render_metrics(producer(), failed, now=1_010)
    assert 'state="stale"} 1' in metrics.render_metrics(producer(), result(), now=2_100)
    recovered = metrics.render_metrics(producer(), result(), now=1_010, previous_state="failure")
    assert 'state="recovered"} 1' in recovered


def test_result_schema_is_sanitized_finite_and_exact():
    for field in ("visitor", "response", "request_id", "url", "token"):
        value = result()
        value[field] = "sensitive"
        with pytest.raises(ValueError, match="exact sanitized schema"):
            metrics.validate_result(value, now=1_010)
    for duration in (-1, math.inf, math.nan, True):
        with pytest.raises(ValueError, match="duration"):
            metrics.validate_result(result(aggregateDurationMs=duration), now=1_010)
    with pytest.raises(ValueError, match="failure stage"):
        metrics.validate_result(result(state="failure", failureStage="renderer"), now=1_010)


def test_optional_renderer_is_separate_from_essential_metrics():
    output = metrics.render_metrics(producer(), result(), now=1_010)
    assert "renderer" not in output and "immersive" not in output
    assert 'failure_stage="none"' in output


def test_generated_dashboards_and_rules_cover_bounded_contract():
    for profile in PROFILES.values():
        assert profile["path"].read_text(encoding="utf-8") == render(profile)
        document = json.loads(render(profile))
        panels = {p["title"]: p for p in document["panels"]}
        assert {
            "Daniel visitor journey state",
            "Daniel visitor journey success",
            "Daniel visitor journey freshness",
            "Daniel visitor journey aggregate duration",
            "Daniel visitor journey classified failure",
        } <= panels.keys()
    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"][0]["rules"]
    assert {r["alert"] for r in rules} == {
        "DanielsmithVisitorJourneyFailed",
        "DanielsmithVisitorJourneyStaleOrUnavailable",
    }
    text = RULES.read_text(encoding="utf-8")
    assert 'monitoring_enabled{application="danielsmith"} == 1' in text
    assert 'state=~"stale|unavailable"' in text
    assert not any(word in text.lower() for word in ("request_id", "cookie", "visitor_id"))
