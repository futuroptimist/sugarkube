import copy
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import danielsmith_visitor_metrics as metrics
from scripts import validate_probe_quotas as quotas

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


@pytest.mark.parametrize("mutation", ["empty", "deleted-prod", "changed-application"])
def test_descriptor_requires_both_exact_daniel_identities(mutation):
    data = inventory()
    if mutation == "empty":
        data["producers"] = []
    elif mutation == "deleted-prod":
        data["producers"].pop()
    else:
        data["producers"][0]["application"] = "other"
    with pytest.raises(quotas.ContractError, match="required staging and prod identities"):
        quotas.validate_visitor_contract(data)


def test_custom_config_keeps_optional_absence_but_explicit_missing_fails(tmp_path, monkeypatch):
    (tmp_path / "probe-quotas.yaml").write_text(
        yaml.safe_dump({"version": 1, "probes": []}), encoding="utf-8"
    )
    probes = tmp_path / "probes.yaml"
    probes.write_text("", encoding="utf-8")
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(quotas, "load_modules", lambda environment: ({}, 1))
    assert quotas.main(["--env", "staging", "--probes", str(probes)]) == 0
    assert (
        quotas.main(
            [
                "--env",
                "staging",
                "--probes",
                str(probes),
                "--visitor-contract",
                str(tmp_path / "missing.json"),
            ]
        )
        == 1
    )
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


def test_offline_entry_point_validates_and_atomically_publishes_temp_files(tmp_path):
    descriptor = tmp_path / "descriptor.json"
    data = inventory()
    data["producers"][0]["enabled"] = True
    data["producers"][0]["requestMultiplicity"] = 1
    descriptor.write_text(json.dumps(data), encoding="utf-8")
    sanitized = tmp_path / "result.json"
    sanitized.write_text(
        json.dumps(result(freshness=int(__import__("time").time()))), encoding="utf-8"
    )
    output = tmp_path / "collector" / "visitor.prom"
    completed = subprocess.run(
        [
            "python3",
            "scripts/danielsmith_visitor_metrics.py",
            "--descriptor",
            str(descriptor),
            "--environment",
            "staging",
            "--result",
            str(sanitized),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert 'state="success"} 1' in output.read_text(encoding="utf-8")
    assert list(output.parent.iterdir()) == [output]

    invalid = json.loads(sanitized.read_text(encoding="utf-8"))
    invalid["url"] = "https://sensitive.example"
    sanitized.write_text(json.dumps(invalid), encoding="utf-8")
    completed = subprocess.run(
        completed.args, cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert completed.returncode != 0
    assert output.read_text(encoding="utf-8").endswith('state="success"} 1\n')


@pytest.mark.skipif(shutil.which("promtool") is None, reason="promtool is not installed")
def test_actual_alert_promql_fires_and_clears_for_both_environments(tmp_path):
    for environment in ("staging", "prod"):
        rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))
        declaration = rules["groups"][0]["rules"][0 if environment == "staging" else 1]
        declaration["expr"] = "vector(1)"
        rules_path = tmp_path / f"rules-{environment}.yaml"
        rules_path.write_text(yaml.safe_dump(rules, sort_keys=False), encoding="utf-8")
        name = f"danielsmith-visitor-journey-{environment}"
        labels = f'application="danielsmith",environment="{environment}",name="{name}"'
        common = {
            "interval": "1m",
            "input_series": [],
            "alert_rule_test": [],
        }
        missing = copy.deepcopy(common)
        missing["name"] = f"{environment} missing result"
        missing["alert_rule_test"] = _alert_checks(environment, name, "stale", "4m", "5m")

        success = copy.deepcopy(common)
        success["name"] = f"{environment} fresh success"
        success["input_series"] = [
            {
                "series": f"danielsmith_visitor_journey_freshness_timestamp_seconds{{{labels}}}",
                "values": "10000x30",
            },
            {
                "series": f'danielsmith_visitor_journey_state{{{labels},state="success"}}',
                "values": "1x30",
            },
        ]
        success["alert_rule_test"] = [
            {"eval_time": "10m", "alertname": alert, "exp_alerts": []}
            for alert in (
                "DanielsmithVisitorJourneyFailed",
                "DanielsmithVisitorJourneyStaleOrUnavailable",
            )
        ]

        failure = copy.deepcopy(success)
        failure["name"] = f"{environment} fresh failure and recovery"
        failure["input_series"][1] = {
            "series": f'danielsmith_visitor_journey_state{{{labels},state="failure"}}',
            "values": "1x5 0x25",
        }
        failure["alert_rule_test"] = _alert_checks(environment, name, "failure", "4m", "5m") + [
            {"eval_time": "6m", "alertname": "DanielsmithVisitorJourneyFailed", "exp_alerts": []}
        ]

        frozen = copy.deepcopy(success)
        frozen["name"] = f"{environment} frozen success"
        frozen["input_series"][0]["values"] = "0x30"
        frozen["alert_rule_test"] = _alert_checks(environment, name, "stale", "22m", "23m")

        expired_failure = copy.deepcopy(frozen)
        expired_failure["name"] = f"{environment} expired failure"
        expired_failure["input_series"][1][
            "series"
        ] = f'danielsmith_visitor_journey_state{{{labels},state="failure"}}'
        expired_failure["alert_rule_test"] = (
            _alert_checks(environment, name, "failure", "4m", "5m")
            + [
                {
                    "eval_time": "18m",
                    "alertname": "DanielsmithVisitorJourneyFailed",
                    "exp_alerts": [],
                }
            ]
            + _alert_checks(environment, name, "stale", "22m", "23m")
        )
        tests = [missing, success, failure, frozen, expired_failure]
        fixture = tmp_path / f"promtool-{environment}.yaml"
        fixture.write_text(
            yaml.safe_dump(
                {"rule_files": [str(rules_path)], "evaluation_interval": "1m", "tests": tests},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["promtool", "test", "rules", str(fixture)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    disabled_fixture = tmp_path / "promtool-disabled.yaml"
    disabled_fixture.write_text(
        yaml.safe_dump(
            {
                "rule_files": [str(RULES)],
                "evaluation_interval": "1m",
                "tests": [
                    {
                        "name": f"{environment} disabled",
                        "interval": "1m",
                        "input_series": [],
                        "alert_rule_test": [
                            {"eval_time": "10m", "alertname": alert, "exp_alerts": []}
                            for alert in (
                                "DanielsmithVisitorJourneyFailed",
                                "DanielsmithVisitorJourneyStaleOrUnavailable",
                            )
                        ],
                    }
                    for environment in ("staging", "prod")
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["promtool", "test", "rules", str(disabled_fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _alert_checks(environment, name, kind, pending_time, firing_time):
    alert = (
        "DanielsmithVisitorJourneyFailed"
        if kind == "failure"
        else "DanielsmithVisitorJourneyStaleOrUnavailable"
    )
    severity = "critical" if kind == "failure" else "warning"
    annotations = {
        "summary": (
            "danielsmith.io essential visitor journey failed"
            if kind == "failure"
            else "danielsmith.io visitor journey result is stale or unavailable"
        ),
        "description": (
            "The application-owned essential visitor contract failed; optional immersive-rendering availability is not part of this alert."
            if kind == "failure"
            else "An enabled producer has no current sanitized result; an intentionally disabled producer does not alert."
        ),
        "remediation": (
            "Inspect only the bounded failure-stage metric, then qualify recovery before changing activation."
            if kind == "failure"
            else "Verify the producer schedule and bounded result handoff without executing an unauthorized probe."
        ),
        "runbook_url": "https://github.com/futuroptimist/sugarkube/blob/main/docs/danielsmith-visitor-journey.md#alerts",
    }
    return [
        {"eval_time": pending_time, "alertname": alert, "exp_alerts": []},
        {
            "eval_time": firing_time,
            "alertname": alert,
            "exp_alerts": [
                {
                    "exp_labels": {
                        "application": "danielsmith",
                        "environment": environment,
                        "name": name,
                        "severity": severity,
                    },
                    "exp_annotations": annotations,
                }
            ],
        },
    ]
