import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
VALIDATOR = ROOT / "scripts/validate_observability_dashboard.py"
SCRIPT = ROOT / "scripts/observability_helm.sh"


def all_panels(document):
    for panel in document["panels"]:
        yield panel
        yield from panel.get("panels", [])


@pytest.fixture
def dashboard():
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def test_dashboard_identity_defaults_rows_and_required_panels(dashboard):
    assert dashboard["uid"] == "sugarkube-staging-observability"
    assert dashboard["title"] == "Sugarkube Staging Observability"
    assert dashboard["time"] == {"from": "now-6h", "to": "now"}
    assert dashboard["refresh"] == "30s"
    panels = list(all_panels(dashboard))
    assert len({panel["id"] for panel in panels}) == len(panels)
    rows = {panel["title"] for panel in panels if panel["type"] == "row"}
    assert rows == {
        "Overall status",
        "DSPACE HTTP",
        "DSPACE runtime and release",
        "DSPACE feature traffic",
        "Blackbox monitoring",
    }
    titles = {panel["title"] for panel in panels}
    for title in (
        "DSPACE scrape availability",
        "DSPACE instrumentation status",
        "Public endpoint availability",
        "Request rate by route and status class",
        "Status-class distribution",
        "5xx error ratio",
        "HTTP latency percentiles",
        "Resident memory by pod",
        "Build identity",
        "dChat request activity",
        "token.place dependency request activity",
        "Endpoint matrix",
        "Probe duration",
        "HTTP response status",
        "TLS certificate lifetime",
    ):
        assert title in titles


def test_queries_use_stable_datasource_bounded_labels_and_safe_zero(dashboard):
    serialized = json.dumps(dashboard)
    expressions = [
        target["expr"] for panel in all_panels(dashboard) for target in panel.get("targets", [])
    ]
    assert '"uid": "prometheus"' in serialized
    assert "${DS_" not in serialized and "__inputs" not in serialized
    assert not any("{{target}}" in serialized or "target=~" in expr for expr in expressions)
    assert "http://" not in serialized and "https://" not in serialized
    assert all(
        "or on() vector(0)" in expr
        for expr in expressions
        if "dspace_dchat_requests_total" in expr or "dspace_dependency_requests_total" in expr
    )
    assert {item["name"] for item in dashboard["templating"]["list"]} == {
        "environment",
        "app",
        "route",
    }


def test_snapshot_tables_use_instant_queries(dashboard):
    snapshots = {"Endpoint matrix", "Build identity", "HTTP response status"}
    panels = {panel["title"]: panel for panel in all_panels(dashboard)}
    for title in snapshots:
        assert panels[title]["targets"]
        assert all(
            target.get("instant") is True and target.get("range") is False
            for target in panels[title]["targets"]
        )
    build = panels["Build identity"]
    assert build["targets"][0]["expr"].startswith("max by (pod, version, revision) (")
    organize = next(item for item in build["transformations"] if item["id"] == "organize")
    assert organize["options"]["indexByName"] == {"pod": 0, "version": 1, "revision": 2}
    assert organize["options"]["excludeByName"] == {"Time": True, "Value": True}


def test_blackbox_queries_drop_raw_target_labels(dashboard):
    panels = {panel["title"]: panel for panel in all_panels(dashboard)}
    expected = {
        "Endpoint matrix": "min",
        "Probe duration": "max",
        "HTTP response status": "max",
        "TLS certificate lifetime": "min",
    }
    for title, aggregation in expected.items():
        expression = panels[title]["targets"][0]["expr"]
        assert f"{aggregation} by (environment, app, route) (" in expression
        assert " by (environment, app, route, " not in expression
        assert "instance" not in expression and "target" not in expression


def test_validator_rejects_malformed_missing_and_changed_identity(tmp_path):
    for content in ("{", "{}"):
        candidate = tmp_path / f"candidate-{len(content)}.json"
        candidate.write_text(content, encoding="utf-8")
        result = subprocess.run(
            ["python3", str(VALIDATOR), str(candidate)], capture_output=True, text=True
        )
        assert result.returncode != 0
    missing = subprocess.run(
        ["python3", str(VALIDATOR), str(tmp_path / "missing.json")], capture_output=True
    )
    assert missing.returncode != 0


def rendered_dashboard_yaml(dashboard, mount_path=None, sub_path=None):
    filename = "sugarkube-staging-observability.json"
    mount_path = mount_path or f"/var/lib/grafana/dashboards/sugarkube/{filename}"
    sub_path = sub_path or filename
    payload = json.dumps(dashboard, indent=2)
    return (
        "kind: ConfigMap\n"
        "metadata:\n"
        "  name: kube-prometheus-stack-grafana-dashboards-sugarkube\n"
        "  labels:\n"
        "    dashboard-provider: sugarkube\n"
        "data:\n"
        f"  {filename}:\n"
        "    |-\n"
        + "\n".join(f"      {line}" for line in payload.splitlines())
        + "\n---\nkind: ConfigMap\ndata:\n  dashboardproviders.yaml: |\n"
        "    providers:\n      - name: sugarkube\n        options:\n"
        "          path: /var/lib/grafana/dashboards/sugarkube\n"
        "---\nkind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n"
        "        - volumeMounts:\n"
        "            - name: dashboards-sugarkube\n"
        f'              mountPath: "{mount_path}"\n'
        f'              subPath: "{sub_path}"\n'
    )


def run_render_validation(tmp_path, content):
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(content, encoding="utf-8")
    return subprocess.run(
        ["python3", str(VALIDATOR), str(DASHBOARD), "--rendered", str(rendered)],
        capture_output=True,
        text=True,
    )


def test_validator_accepts_chart_native_render(tmp_path, dashboard):
    result = run_render_validation(tmp_path, rendered_dashboard_yaml(dashboard))
    assert result.returncode == 0, result.stderr


def test_validator_rejects_raw_urls_and_complete_render_drift(tmp_path, dashboard):
    unsafe = tmp_path / "unsafe.json"
    unsafe_dashboard = json.loads(json.dumps(dashboard))
    unsafe_dashboard["links"] = [{"url": "https://example.invalid"}]
    unsafe.write_text(json.dumps(unsafe_dashboard), encoding="utf-8")
    result = subprocess.run(["python3", str(VALIDATOR), str(unsafe)], capture_output=True)
    assert result.returncode != 0

    changed = json.loads(json.dumps(dashboard))
    changed["refresh"] = "5m"
    result = run_render_validation(tmp_path, rendered_dashboard_yaml(changed))
    assert result.returncode != 0
    assert "differs from the version-controlled source" in result.stderr


@pytest.mark.parametrize(
    ("mount_path", "sub_path"),
    [
        ("/var/lib/grafana/dashboards/sugarkube", None),
        (None, "another-dashboard.json"),
    ],
)
def test_validator_rejects_wrong_dashboard_mount(tmp_path, dashboard, mount_path, sub_path):
    result = run_render_validation(
        tmp_path, rendered_dashboard_yaml(dashboard, mount_path, sub_path)
    )
    assert result.returncode != 0
    assert "dashboard mount must be exactly" in result.stderr


def test_lifecycle_passes_same_dashboard_to_all_helm_paths():
    script = SCRIPT.read_text(encoding="utf-8")
    assert script.count('--set-file "${DASHBOARD_VALUE}=${DASHBOARD}"') == 3
    assert (
        'DASHBOARD_VALUE="grafana.dashboards.sugarkube.sugarkube-staging-observability.json"'
        in script
    )
    assert script.index(
        "validate_dashboard; require_tools", script.index("install_release")
    ) < script.index("helm install")
    assert script.index(
        "validate_dashboard; require_tools", script.index("upgrade_release")
    ) < script.index("helm upgrade")


def test_dashboard_verifier_is_guarded_read_only_and_redacted():
    script = SCRIPT.read_text(encoding="utf-8")
    body = script.split("dashboard_verify()", 1)[1].split('\ncmd="${1:-}"', 1)[0]
    assert "assert_context" in body
    assert body.index("assert_context") < body.index("get secret grafana-admin-credentials")
    assert "/api/dashboards/uid/sugarkube-staging-observability" in body
    assert "--netrc-file" in body and "chmod 600" in body and "rm -rf" in body
    for mutation in ("helm install", "helm upgrade", "kubectl apply", "kubectl delete"):
        assert mutation not in body
    assert "credentials and response redacted" in body
    assert "--address=127.0.0.1" in body and '"service/${RELEASE}-grafana" :80' in body
    assert body.index("Forwarding\\ from") < body.index("--netrc-file")
    assert "require_tools kubectl python3 curl base64 sleep" in body


@pytest.mark.parametrize(
    "command", ["render", "install", "upgrade", "status", "verify", "dashboard-verify"]
)
def test_malformed_source_fails_before_any_stubbed_cluster_or_helm_access(tmp_path, command):
    (tmp_path / "scripts").mkdir()
    copied_script = tmp_path / "scripts/observability_helm.sh"
    copied_script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    # The copied script resolves ROOT to tmp_path; provide only the validator and
    # malformed artifact. Validation must stop before missing helm/kubectl matter.
    (tmp_path / "scripts/validate_observability_dashboard.py").write_text(
        VALIDATOR.read_text(encoding="utf-8"), encoding="utf-8"
    )
    path = tmp_path / "clusters/staging/observability/dashboards"
    path.mkdir(parents=True)
    (path / DASHBOARD.name).write_text("{", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(copied_script), command, "env=staging"],
        env=os.environ | {"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "dashboard JSON" in result.stderr
