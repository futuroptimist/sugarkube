import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
PRODUCER = ROOT / "scripts/dspace_observability_metrics.py"
EVIDENCE = ROOT / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"


def runtime_result(passed=True, revision="018687f5a7f4de45508c6e36eb28afb3e44da24d"):
    return {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "applicationVersion": "3.1.0",
        "runtimeSourceRevision": revision,
        "frontendSourceRevision": revision,
        "defaultProvider": "token-place",
        "journeys": [
            {"name": "/build-meta.json", "passed": True},
            {"name": "/", "passed": True},
            {"name": "/chat", "passed": passed},
        ],
    }


def run(tmp_path, result, *extra):
    source = tmp_path / "result.json"
    source.write_text(json.dumps(result))
    output = tmp_path / "dspace.prom"
    command = [
        "python3",
        str(PRODUCER),
        "--evidence",
        str(EVIDENCE),
        "--result",
        str(source),
        "--deployment-image-tag",
        "main-018687f",
        "--deployment-image-digest",
        "sha256:2b95b7fdccdd011553c8d8617e3090ee27323996c532148fdb147cb9fd6e1b6c",
        "--timestamp",
        "1785988800",
        "--output",
        str(output),
        *extra,
    ]
    return subprocess.run(command, text=True, capture_output=True), output


def test_exact_alert_contract_and_bounded_promql():
    text = VALUES.read_text()
    names = [
        "DspaceBuildRevisionMismatch",
        "DspaceMixedBuildRevisions",
        "DspaceDeploymentImagePinMismatch",
        "DspaceChatSyntheticFailed",
        "DspaceMetricsTargetDown",
    ]
    assert all(text.count(f"alert: {name}") == 1 for name in names)
    assert "absent(dspace_chat_synthetic_timestamp_seconds" in text
    assert "time() - dspace_chat_synthetic_timestamp_seconds" in text
    assert "count by (environment, revision)" in text
    for forbidden in ("prompt", "response", "session", "request_id", "semanticTag"):
        assert forbidden not in text
    for field in (
        "application:",
        "environment:",
        "cluster:",
        "severity:",
        "current_revision:",
        "expected_revision:",
        "runbook_url:",
        "remediation:",
    ):
        assert field in text


def test_producer_derives_coordinates_and_records_pass_fail(tmp_path):
    for passed in (True, False):
        result, output = run(tmp_path, runtime_result(passed))
        assert result.returncode == 0, result.stderr
        metrics = output.read_text()
        assert 'expected_revision="018687f5a7f4de45508c6e36eb28afb3e44da24d"' in metrics
        assert 'image_tag="main-018687f"' in metrics
        assert "v3.1.0" not in metrics
        assert "dspace_chat_synthetic_success{" in metrics
        samples = [
            line
            for line in metrics.splitlines()
            if line.startswith("dspace_chat_synthetic_success{")
        ]
        assert len(samples) == 1 and samples[0].endswith(str(int(passed)))


def test_producer_fails_closed_without_exact_chat_or_with_semantic_image(tmp_path):
    value = runtime_result()
    value["journeys"] = value["journeys"][:-1]
    result, output = run(tmp_path, value)
    assert result.returncode != 0 and not output.exists()
    evidence = json.loads(EVIDENCE.read_text())
    evidence["imageTag"] = "v3.1.0"
    bad = tmp_path / "evidence.json"
    bad.write_text(json.dumps(evidence))
    source = tmp_path / "result.json"
    source.write_text(json.dumps(runtime_result()))
    result = subprocess.run(
        [
            "python3",
            str(PRODUCER),
            "--evidence",
            str(bad),
            "--result",
            str(source),
            "--deployment-image-tag",
            "v3.1.0",
            "--deployment-image-digest",
            evidence["imageDigest"],
            "--timestamp",
            "1",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
