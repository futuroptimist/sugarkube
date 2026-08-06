import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"
VALUES = ROOT / "clusters/staging/observability/rules/dspace-release-integrity.values.json"
PRODUCER = ROOT / "scripts/dspace_chat_synthetic_metrics.py"
spec = importlib.util.spec_from_file_location(
    "generator", ROOT / "scripts/generate_dspace_observability_rules.py"
)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def rules():
    return json.loads(VALUES.read_text())["additionalPrometheusRulesMap"][
        "dspace-release-integrity"
    ]["groups"][0]["rules"]


def test_generated_contract_matches_finalized_evidence_and_exact_alerts():
    evidence = json.loads(EVIDENCE.read_text())
    assert gen.generate(evidence) == json.loads(VALUES.read_text())
    alerts = {r["alert"]: r for r in rules() if "alert" in r}
    assert set(alerts) == {
        "DspaceBuildRevisionMismatch",
        "DspaceMixedBuildRevisions",
        "DspaceDeploymentImagePinMismatch",
        "DspaceChatSyntheticFailed",
        "DspaceMetricsTargetDown",
    }
    for rule in alerts.values():
        assert rule["labels"] == {
            "application": "dspace",
            "environment": "staging",
            "cluster": "sugarkube-int",
            "severity": "critical",
            "expected_revision": evidence["sourceRevision"],
        }
        assert set(rule["annotations"]) == {
            "summary",
            "current_revision",
            "expected_revision",
            "remediation",
            "runbook_url",
        }
        assert rule["annotations"]["expected_revision"] == evidence["sourceRevision"]
    text = VALUES.read_text()
    assert evidence["semanticTag"] not in text
    assert "prompt" not in text and "request_id" not in text
    assert evidence["imageTag"] in text and evidence["imageDigest"] in text


def test_generator_rejects_nonfinal_and_semantic_identity():
    evidence = json.loads(EVIDENCE.read_text())
    evidence["recordType"] = "candidate"
    with pytest.raises(ValueError):
        gen.generate(evidence)


def run_producer(tmp_path, data, sha="a" * 40):
    result = tmp_path / "result.json"
    result.write_text(json.dumps(data))
    out = tmp_path / "metric.prom"
    proc = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--result",
            str(result),
            "--output",
            str(out),
            "--runner-revision",
            sha,
            "--now",
            "2000",
        ],
        text=True,
        capture_output=True,
    )
    return proc, out


def test_synthetic_contract_distinguishes_executed_failure_and_is_bounded(tmp_path):
    data = {
        "schemaVersion": 1,
        "journey": "/chat",
        "passed": False,
        "mutationDisabled": True,
        "transport": "intercepted",
        "completedAt": 1900,
    }
    proc, out = run_producer(tmp_path, data)
    assert proc.returncode == 0
    text = out.read_text()
    assert "success{" in text and "} 0" in text and "timestamp_seconds{" in text
    assert set(part.split("=")[0] for part in text.split("{")[1].split("}")[0].split(",")) == {
        "application",
        "environment",
        "cluster",
        "runner_revision",
    }


@pytest.mark.parametrize("change", [("mutationDisabled", False), ("transport", "network")])
def test_synthetic_contract_fails_closed_without_credentials(tmp_path, change):
    data = {
        "schemaVersion": 1,
        "journey": "/chat",
        "passed": True,
        "mutationDisabled": True,
        "transport": "intercepted",
        "completedAt": 1900,
    }
    data[change[0]] = change[1]
    proc, out = run_producer(tmp_path, data)
    assert proc.returncode != 0 and not out.exists()
    assert "secret" not in proc.stderr
