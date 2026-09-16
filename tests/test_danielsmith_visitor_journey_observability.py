"""Repository-side tests for the application-owned visitor journey."""

import copy
import json
import subprocess
from pathlib import Path

import pytest

from scripts import danielsmith_visitor_journey_metrics as metrics
from scripts import generate_observability_dashboards as dashboards
from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/observability/danielsmith-visitor-journey.json"


def contract():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def producer(environment="staging", enabled=True):
    value = next(x for x in contract()["producers"] if x["environment"] == environment)
    value["enabled"] = enabled
    return value


def result(state="success", stage=None, freshness=1_700_000_000):
    return {
        "state": state,
        "freshness": freshness,
        "aggregateDurationMs": 1250,
        "failureStage": stage,
    }


def test_descriptors_are_bounded_disabled_and_fail_closed():
    value = contract()
    assert {p["environment"] for p in value["producers"]} == {"staging", "prod"}
    assert all(not p["enabled"] and p["requestMultiplicity"] is None for p in value["producers"])
    assert quotas.validate_completion_contract(value, expected_stages=metrics.FAILURE_STAGES) == 2
    changed = copy.deepcopy(value)
    changed["producers"][0].update(enabled=True)
    with pytest.raises(quotas.ContractError, match="requires requestMultiplicity"):
        quotas.validate_completion_contract(changed, expected_stages=metrics.FAILURE_STAGES)


def test_cadence_timeout_concurrency_and_quota_are_enforced():
    value = contract()
    item = value["producers"][0]
    item.update(enabled=True, requestMultiplicity=30)
    with pytest.raises(quotas.ContractError, match="unsafe completion schedule"):
        quotas.validate_completion_contract(value, expected_stages=metrics.FAILURE_STAGES)
    item.update(enabled=False, requestMultiplicity=None, timeout=item["cadence"])
    with pytest.raises(quotas.ContractError, match="timeout must be shorter"):
        quotas.validate_completion_contract(value, expected_stages=metrics.FAILURE_STAGES)
    item.update(timeout="30s", concurrency=0)
    with pytest.raises(quotas.ContractError, match="concurrency"):
        quotas.validate_completion_contract(value, expected_stages=metrics.FAILURE_STAGES)


def test_disabled_is_not_success_and_unavailable_is_distinct():
    disabled = metrics.render_metrics(producer(enabled=False), now=1_700_000_000)
    unavailable = metrics.render_metrics(producer(), now=1_700_000_000)
    assert 'state="disabled"' in disabled and "journey_success" not in disabled
    assert 'state="unavailable"' in unavailable and "journey_success" not in unavailable


@pytest.mark.parametrize("stage", sorted(metrics.FAILURE_STAGES))
def test_success_failure_stale_and_recovery(stage):
    failed = metrics.render_metrics(producer(), result("failure", stage), now=1_700_000_001)
    assert 'state="failed"' in failed and f'failure_stage="{stage}"' in failed
    assert " 0\n" in failed
    assert 'state="stale"' in metrics.render_metrics(producer(), result(), now=1_700_001_000)
    recovered = metrics.render_metrics(
        producer(), result(), now=1_700_000_001, previous_state="failure"
    )
    assert 'state="recovered"' in recovered and 'failure_stage="none"' in recovered
    successful = metrics.render_metrics(producer(), result(), now=1_700_000_001)
    assert 'state="successful"' in successful and " 1\n" in successful


def test_metric_schema_rejects_sensitive_or_unbounded_data():
    for field, value in (("freshness", float("nan")), ("aggregateDurationMs", -1)):
        changed = result()
        changed[field] = value
        with pytest.raises(ValueError):
            metrics.validate_result(changed)
    changed = result()
    changed["responseBody"] = "visitor data"
    with pytest.raises(ValueError, match="exact sanitized schema"):
        metrics.validate_result(changed)
    with pytest.raises(ValueError, match="failureStage"):
        metrics.validate_result(result("failure", "secret-dependent-stage"))


def test_optional_renderer_is_not_conflated_with_essential_success():
    output = metrics.render_metrics(producer(), result(), now=1_700_000_001)
    assert "renderer" not in output
    assert "danielsmith_visitor_journey_success" in output


def test_generated_dashboards_contain_environment_scoped_contract():
    titles = {
        "Daniel visitor monitoring state",
        "Daniel essential journey success",
        "Daniel journey freshness",
        "Daniel aggregate duration",
        "Daniel bounded failure stage",
        "Daniel optional renderer separation",
    }
    for profile in dashboards.PROFILES.values():
        panels = {p["title"]: p for p in json.loads(dashboards.render(profile))["panels"]}
        assert titles <= panels.keys()
        for title in titles:
            assert 'environment="$environment"' in panels[title]["targets"][0]["expr"]
        description = panels["Daniel optional renderer separation"]["description"]
        assert "optional immersive-renderer" in description


def test_alerts_gate_on_enablement_and_keep_environments_separate():
    script = (ROOT / "scripts/observability_helm.sh").read_text(encoding="utf-8")
    assert "DANIELSMITH_JOURNEY_RULES" in script
    text = (ROOT / "platform/observability/rules/danielsmith-visitor-journey.yaml").read_text()
    assert text.count("alert: DanielsmithVisitorJourneyFailed") == 2
    assert 'monitoring_enabled{application="danielsmith"' in text
    assert 'state=~"failed|stale|unavailable"' in text
    assert "optional immersive rendering is not part" in text
    assert 'environment="staging"' in text and 'environment="prod"' in text


def test_generated_files_are_current():
    subprocess.run(
        ["python3", "scripts/generate_observability_dashboards.py", "--check"], cwd=ROOT, check=True
    )
