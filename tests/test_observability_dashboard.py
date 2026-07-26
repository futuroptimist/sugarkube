import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
VALIDATOR = ROOT / "scripts/validate_observability_dashboard.py"
HELM_SCRIPT = ROOT / "scripts/observability_helm.sh"


def load_dashboard():
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def targets(dashboard):
    return [target for panel in dashboard["panels"] for target in panel.get("targets", [])]


def test_dashboard_identity_layout_time_and_datasource_are_stable():
    dashboard = load_dashboard()
    assert dashboard["title"] == "Sugarkube Staging Observability"
    assert dashboard["uid"] == "sugarkube-staging-observability"
    assert dashboard["time"] == {"from": "now-6h", "to": "now"}
    assert dashboard["refresh"] == "30s"
    ids = [panel["id"] for panel in dashboard["panels"]]
    assert len(ids) == len(set(ids))
    rows = [panel["title"] for panel in dashboard["panels"] if panel["type"] == "row"]
    assert rows == [
        "Overall status",
        "DSPACE HTTP",
        "DSPACE runtime and release",
        "DSPACE feature traffic",
        "Blackbox monitoring",
    ]
    references = [target["datasource"] for target in targets(dashboard)]
    references += [item["datasource"] for item in dashboard["templating"]["list"]]
    assert references and all(
        item == {"type": "prometheus", "uid": "prometheus"} for item in references
    )
    assert "${DS_" not in DASHBOARD.read_text(encoding="utf-8")


def test_required_panels_metrics_variables_and_zero_fallbacks():
    dashboard = load_dashboard()
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "DSPACE scrape availability",
        "DSPACE instrumentation status",
        "Public endpoint availability",
        "Request rate by route and status class",
        "Status-class distribution",
        "5xx error ratio",
        "Request latency quantiles",
        "Resident memory by pod",
        "Build identity",
        "dChat request activity",
        "token.place dependency activity",
        "Endpoint matrix",
        "Probe duration",
        "HTTP response status",
        "TLS certificate lifetime",
    } <= titles
    expressions = "\n".join(target["expr"] for target in targets(dashboard))
    for metric in (
        "up",
        "dspace_instrumentation_up",
        "probe_success",
        "dspace_http_requests_total",
        "dspace_http_request_duration_seconds_bucket",
        "process_resident_memory_bytes",
        "dspace_build_info",
        "dspace_dchat_requests_total",
        "dspace_dependency_requests_total",
        "probe_duration_seconds",
        "probe_http_status_code",
        "probe_ssl_earliest_cert_expiry",
    ):
        assert re.search(rf"\b{metric}\b", expressions)
    event_queries = [
        line
        for line in expressions.splitlines()
        if "dspace_dchat" in line or "dspace_dependency" in line
    ]
    assert event_queries and all("or on() vector(0)" in query for query in event_queries)
    variables = {item["name"]: item for item in dashboard["templating"]["list"]}
    assert set(variables) == {"environment", "app", "route"}
    assert variables["environment"]["current"]["value"] == "staging"
    assert variables["app"]["allValue"] == variables["route"]["allValue"] == ".*"


def test_dashboard_uses_bounded_labels_and_contains_no_targets_or_sensitive_data():
    text = DASHBOARD.read_text(encoding="utf-8")
    expressions = "\n".join(target["expr"] for target in targets(load_dashboard()))
    assert "target" not in expressions and "instance" not in expressions
    for forbidden in (
        "http://",
        "https://",
        "admin-" + chr(112) + "assword",
        "admin-user",
        "authorization",
        "bearer",
    ):
        assert forbidden not in text.lower()
    blackbox = [line for line in expressions.splitlines() if "probe_" in line]
    assert blackbox and all(
        all(label in line for label in ("environment", "app", "route")) for line in blackbox
    )


def test_validator_rejects_missing_malformed_and_semantically_invalid_json(tmp_path):
    missing = subprocess.run(
        ["python3", str(VALIDATOR), str(tmp_path / "missing.json")], capture_output=True, text=True
    )
    assert missing.returncode != 0 and "missing or malformed" in missing.stderr
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    result = subprocess.run(
        ["python3", str(VALIDATOR), str(malformed)], capture_output=True, text=True
    )
    assert result.returncode != 0 and "missing or malformed" in result.stderr
    changed = load_dashboard()
    changed["uid"] = "changed"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(changed), encoding="utf-8")
    result = subprocess.run(
        ["python3", str(VALIDATOR), str(invalid)], capture_output=True, text=True
    )
    assert result.returncode != 0 and "UID or title changed" in result.stderr


def test_all_helm_lifecycle_paths_use_one_dashboard_artifact_and_validate_render():
    script = HELM_SCRIPT.read_text(encoding="utf-8")
    option = (
        '--set-file "grafana.dashboards.default.sugarkube-staging-observability.json=${DASHBOARD}"'
    )
    assert script.count(option) == 3
    assert 'DASHBOARD="${ROOT}/clusters/staging/observability/dashboards/' in script
    assert 'validate_observability_dashboard.py" "${DASHBOARD}" --rendered' in script
    assert script.index('validate_observability_dashboard.py" "${DASHBOARD}"') < script.index(
        'case "${cmd}"'
    )
    assert "--reuse-values" not in script


def test_dashboard_verifier_is_guarded_read_only_and_redacts_credentials():
    script = HELM_SCRIPT.read_text(encoding="utf-8")
    body = script.split("dashboard_verify() {", 1)[1].split("\n}\n\ncmd=", 1)[0]
    assert body.index("assert_context") < body.index("get secret grafana-admin-credentials")
    assert "/api/dashboards/uid/sugarkube-staging-observability" in body
    assert '--config "${config}"' in body and "chmod 700" in body and "umask 077" in body
    assert "trap cleanup_dashboard_verify EXIT INT TERM" in body
    for mutation in (
        "helm install",
        "helm upgrade",
        "kubectl apply",
        "kubectl create",
        "kubectl patch",
        "kubectl delete",
    ):
        assert mutation not in body
    assert "credentials and response content not printed" in body
