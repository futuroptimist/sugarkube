import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"


def test_dashboard_structure_metrics_and_safe_labels():
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    assert dashboard["uid"] == "sugarkube-staging-observability"
    assert dashboard["title"] == "Sugarkube Staging Observability"
    assert dashboard["time"]["from"] == "now-6h" and dashboard["refresh"] == "30s"
    ids = [panel["id"] for panel in dashboard["panels"]]
    assert len(ids) == len(set(ids))
    text = json.dumps(dashboard)
    for metric in (
        "dspace_http_requests_total",
        "dspace_http_request_duration_seconds_bucket",
        "dspace_build_info",
        "dspace_dchat_requests_total",
        "dspace_dependency_requests_total",
        "probe_success",
        "probe_duration_seconds",
        "probe_http_status_code",
        "probe_ssl_earliest_cert_expiry",
    ):
        assert metric in text
    assert "vector(0)" in text and "${DS_" not in text
    assert "instance}}" not in text and "target}}" not in text
    assert "http://" not in text and "https://" not in text


def test_offline_validator_accepts_dashboard_and_rejects_malformed(tmp_path):
    validator = ROOT / "scripts/validate_observability_dashboard.py"
    assert subprocess.run([validator, DASHBOARD], check=False).returncode == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert subprocess.run([validator, bad], check=False).returncode != 0


def test_lifecycle_and_read_only_verifier_contract():
    script = (ROOT / "scripts/observability_helm.sh").read_text(encoding="utf-8")
    assert script.count('"${DASHBOARD_ARGS[@]}"') == 3
    assert "--set-file" in script and "grafana.dashboards.default" in script
    verifier = script.split("dashboard_api_check()", 1)[1].split('cmd="${1:-}"', 1)[0]
    for mutation in (
        "helm install",
        "helm upgrade",
        "kubectl apply",
        "kubectl delete",
        "kubectl patch",
    ):
        assert mutation not in verifier
    assert "assert_context" in verifier and "curl --config" in verifier
    assert "credentials and response content were not printed" in verifier


def test_no_regression_to_unrelated_staging_configuration():
    common = (
        ROOT / "platform/observability/helm/kube-prometheus-stack.values.common.yaml"
    ).read_text(encoding="utf-8")
    policy = (
        ROOT
        / "clusters/staging/observability/network-policies/prometheus-to-blackbox-exporter.yaml"
    ).read_text(encoding="utf-8")
    assert "enabled: false" in common and "nodePort: 30300" in common
    assert "policyTypes:\n    - Ingress" in policy and "Egress" not in policy
    assert not (ROOT / "clusters/prod/observability/dashboards").exists()
