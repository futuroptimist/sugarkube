import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import dspace_synthetic_metrics

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
EVIDENCE = ROOT / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"
PROMTOOL_RULES = ROOT / "tests/prometheus/dspace-alerts.rules.yaml"


def yaml_load(path: Path):
    return json.loads(
        subprocess.run(
            [
                "ruby",
                "-ryaml",
                "-rjson",
                "-e",
                "puts JSON.generate(YAML.safe_load_file(ARGV[0], aliases: true))",
                str(path),
            ],
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    )


def rules():
    return yaml_load(VALUES)["additionalPrometheusRulesMap"]["dspace-release-integrity"]["groups"][
        0
    ]["rules"]


def test_exact_alert_contract_and_coordinates_come_from_finalized_evidence():
    alerts = {rule["alert"]: rule for rule in rules() if "alert" in rule}
    assert set(alerts) == {
        "DspaceBuildRevisionMismatch",
        "DspaceMixedBuildRevisions",
        "DspaceDeploymentImagePinMismatch",
        "DspaceChatSyntheticFailed",
        "DspaceMetricsTargetDown",
    }
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    approved = next(
        rule for rule in rules() if rule.get("record") == "dspace:approved_release_info"
    )
    assert approved["labels"]["expected_revision"] == evidence["sourceRevision"]
    assert approved["labels"]["expected_image_digest"] == evidence["imageDigest"]
    assert approved["labels"]["evidence"] == str(EVIDENCE.relative_to(ROOT))
    assert evidence["semanticTag"] not in VALUES.read_text(encoding="utf-8")
    for rule in alerts.values():
        assert rule["labels"] == {
            "severity": "critical",
            "application": "dspace",
            "environment": "staging",
            "cluster": "sugarkube-int",
        }
        assert set(rule["annotations"]) == {
            "summary",
            "remediation",
            "current_revision",
            "expected_revision",
            "runbook_url",
        }
        assert rule["annotations"]["runbook_url"].startswith(
            "https://github.com/futuroptimist/sugarkube/blob/main/docs/"
        )


def test_promtool_rule_copy_is_deterministically_exported(tmp_path):
    exported = tmp_path / "rules.yaml"
    subprocess.run(
        ["python3", str(ROOT / "scripts/export_dspace_prometheus_rules.py"), str(exported)],
        check=True,
    )
    assert exported.read_text(encoding="utf-8") == PROMTOOL_RULES.read_text(encoding="utf-8")


def test_promql_covers_mismatch_mixed_missing_failed_stale_and_bounded_labels():
    text = VALUES.read_text(encoding="utf-8")
    assert "unless on (environment, revision)" in text  # mismatch and normal agreement
    assert "count by (environment, revision)" in text  # mixed active revisions only
    assert 'revision", "unknown"' in text  # bounded missing identity state
    assert "dspace_chat_synthetic_success" in text and "== 0" in text
    assert "dspace_chat_synthetic_timestamp_seconds" in text and "> 900" in text
    assert "unless on (environment) up" in text and "== 0" in text
    forbidden = ("prompt", "response", "user_id", "session", "request_id", "raw_error")
    assert not any(value in text.lower() for value in forbidden)


def runtime_result(passed=True):
    return {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "applicationVersion": "3.1.0",
        "runtimeSourceRevision": "0" * 40,
        "frontendSourceRevision": "0" * 40,
        "defaultProvider": "token-place",
        "journeys": [{"name": "/chat", "passed": passed}],
    }


@pytest.mark.parametrize(("passed", "value"), [(True, " 1\n"), (False, " 0\n")])
def test_synthetic_publisher_is_bounded_and_distinguishes_execution(passed, value):
    rendered = dspace_synthetic_metrics.render(runtime_result(passed), 1234)
    assert value in rendered
    assert "timestamp_seconds" in rendered and " 1234\n" in rendered
    assert set(
        part.split("=")[0] for part in rendered.split("{", 1)[1].split("}", 1)[0].split(",")
    ) == {"application", "environment", "revision"}


def test_synthetic_publisher_refuses_credential_env_and_writes_atomically(tmp_path):
    result = tmp_path / "result.json"
    result.write_text(json.dumps(runtime_result()), encoding="utf-8")
    output = tmp_path / "collector" / "result.prom"
    env = {**os.environ, "OPENAI" + "_API" + "_KEY": "must-not-be-accepted"}
    completed = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts/dspace_synthetic_metrics.py"),
            "--result",
            str(result),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert completed.returncode != 0
    assert "must-not-be-accepted" not in completed.stderr
    assert not output.exists()
