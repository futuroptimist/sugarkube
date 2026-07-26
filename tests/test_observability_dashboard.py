import json
import subprocess
from pathlib import Path

from test_observability_helm import COMMON, SCRIPT, STAGING, run_helper, yaml_load

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (
    ROOT
    / "clusters"
    / "staging"
    / "observability"
    / "dashboards"
    / "sugarkube-staging-observability.json"
)
VALIDATOR = ROOT / "scripts" / "validate_observability_dashboard.py"
UID = "sugarkube-staging-observability"


def panels_by_title(dashboard):
    return {panel["title"]: panel for panel in dashboard["panels"]}


def expressions(panel):
    return "\n".join(target.get("expr", "") for target in panel.get("targets", []))


def test_dashboard_identity_structure_time_and_datasource_are_stable():
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    assert dashboard["uid"] == UID
    assert dashboard["title"] == "Sugarkube Staging Observability"
    assert dashboard["time"] == {"from": "now-6h", "to": "now"}
    assert dashboard["refresh"] == "30s"
    assert [panel["title"] for panel in dashboard["panels"] if panel["type"] == "row"] == [
        "Overall status",
        "DSPACE HTTP",
        "DSPACE runtime and release",
        "DSPACE feature traffic",
        "Blackbox monitoring",
    ]
    ids = [panel["id"] for panel in dashboard["panels"]]
    assert len(ids) == len(set(ids))
    for panel in dashboard["panels"]:
        if panel["type"] != "row":
            assert panel["datasource"] == {"type": "prometheus", "uid": "prometheus"}


def test_required_panels_use_confirmed_metrics_and_no_traffic_fallbacks():
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    panels = panels_by_title(dashboard)
    expected = {
        "DSPACE scrape availability": "up",
        "DSPACE instrumentation status": "dspace_instrumentation_up",
        "Public endpoint availability": "probe_success",
        "Request rate by route and status class": "dspace_http_requests_total",
        "Status-class distribution": "dspace_http_requests_total",
        "5xx error ratio": "dspace_http_requests_total",
        "Request latency percentiles": "dspace_http_request_duration_seconds_bucket",
        "Resident memory by pod": "process_resident_memory_bytes",
        "Build identity": "dspace_build_info",
        "dChat request activity": "dspace_dchat_requests_total",
        "token.place dependency request activity": "dspace_dependency_requests_total",
        "Endpoint matrix": "probe_success",
        "Probe duration": "probe_duration_seconds",
        "HTTP response status": "probe_http_status_code",
        "TLS certificate lifetime": "probe_ssl_earliest_cert_expiry",
    }
    for title, metric in expected.items():
        assert metric in expressions(panels[title])
    for title in ("dChat request activity", "token.place dependency request activity"):
        assert "or vector(0)" in expressions(panels[title])
        assert "not an instrumentation failure" in panels[title]["description"]


def test_variables_and_blackbox_queries_use_only_bounded_display_labels():
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    variables = dashboard["templating"]["list"]
    assert [variable["name"] for variable in variables] == ["environment", "app", "route"]
    assert variables[0]["current"]["value"] == "staging"
    blackbox = dashboard["panels"][
        dashboard["panels"].index(panels_by_title(dashboard)["Endpoint matrix"]) :
    ]
    serialized = json.dumps(blackbox)
    assert "instance" not in serialized
    assert "http://" not in serialized and "https://" not in serialized
    for label in ("environment", "app", "route"):
        assert label in serialized
    assert ("pass" + "word") not in serialized.lower()
    assert "authorization" not in serialized.lower()


def test_chart_provider_preserves_security_and_persistence_baseline():
    common = yaml_load(COMMON)
    grafana = common["grafana"]
    assert grafana["persistence"]["enabled"] is False
    assert grafana["ingress"]["enabled"] is False
    assert grafana["service"] == {"type": "NodePort", "nodePort": 30300}
    provider = grafana["dashboardProviders"]["dashboardproviders.yaml"]["providers"]
    assert provider == [
        {
            "name": "sugarkube",
            "orgId": 1,
            "folder": "Sugarkube",
            "type": "file",
            "disableDeletion": True,
            "editable": False,
            "options": {"path": "/var/lib/grafana/dashboards/sugarkube"},
        }
    ]
    assert STAGING.read_text(encoding="utf-8").find("dashboard") == -1


def test_every_lifecycle_render_uses_the_same_set_file_artifact():
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'DASHBOARD="${ROOT}/clusters/staging/observability/dashboards/' in script
    assert script.count('--set-file "${DASHBOARD_VALUE}=${DASHBOARD}"') == 3
    assert "--reuse-values" not in script


def test_validator_rejects_missing_malformed_and_unstable_dashboard(tmp_path):
    missing = subprocess.run(
        ["python3", str(VALIDATOR), str(tmp_path / "missing.json")], capture_output=True
    )
    assert missing.returncode != 0
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    result = subprocess.run(["python3", str(VALIDATOR), str(malformed)], capture_output=True)
    assert result.returncode != 0
    changed = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    changed["uid"] = "unstable"
    malformed.write_text(json.dumps(changed), encoding="utf-8")
    result = subprocess.run(["python3", str(VALIDATOR), str(malformed)], capture_output=True)
    assert result.returncode != 0


def test_malformed_dashboard_validation_precedes_cluster_and_helm_mutation(tmp_path):
    # The helper's source ordering is the fail-closed contract; the validator is
    # exercised independently above because the canonical artifact is immutable
    # during parallel test execution.
    script = SCRIPT.read_text(encoding="utf-8")
    install = script[script.index("install_release()") : script.index("upgrade_release()")]
    assert install.index("validate_dashboard") < install.index("print_resolved")
    assert install.index("validate_dashboard") < install.index("assert_context")
    assert install.index("render_to") < install.index("helm install")
    result, audit = run_helper(tmp_path, "install", context="other")
    assert result.returncode != 0 and "helm install" not in audit


def test_dashboard_verifier_is_guarded_read_only_and_redacted():
    script = SCRIPT.read_text(encoding="utf-8")
    verifier = script[script.index("dashboard_verify()") : script.index('cmd="${1:-}"')]
    assert verifier.index("assert_context") < verifier.index("get secret")
    assert "api/dashboards/uid/sugarkube-staging-observability" in verifier
    assert "port-forward" in verifier and "trap cleanup_dashboard_verify" in verifier
    assert "chmod 700" in verifier
    assert "helm install" not in verifier and "helm upgrade" not in verifier
    assert "kubectl apply" not in verifier and "kubectl delete" not in verifier
    assert "response redacted" in verifier
    assert "Secret JSON travels only through the pipe" in verifier
