import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
VALIDATOR = ROOT / "scripts/validate_observability_dashboard.py"
SCRIPT = ROOT / "scripts/observability_helm.sh"

# Import the validator so pytest-cov attributes its execution to the production
# module. Subprocess-only checks prove the command-line contract, but their
# coverage data is not collected by the parent pytest process.
sys.path.insert(0, str(ROOT))
from scripts import validate_observability_dashboard as validator  # noqa: E402


def all_panels(document):
    for panel in document["panels"]:
        yield panel
        yield from panel.get("panels", [])


def replace_metric_expression(document, metric, replacement):
    target = next(
        target
        for panel in all_panels(document)
        for target in panel.get("targets", [])
        if metric in target.get("expr", "")
    )
    target["expr"] = replacement


def panel_named(document, title):
    return next(panel for panel in all_panels(document) if panel.get("title") == title)


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
        "Instrumentation health",
        "Public endpoint availability",
        "User request rate by route and status class",
        "Operational request rate",
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


def test_selected_window_traffic_and_availability_semantics(dashboard):
    panels = {panel["title"]: panel for panel in all_panels(dashboard)}
    distribution = panels["Status-class distribution"]
    assert distribution["type"] in {"barchart", "piechart"}
    assert all(
        target["instant"] is True and target["range"] is False for target in distribution["targets"]
    )
    assert "increase(dspace_http_requests_total" in distribution["targets"][0]["expr"]
    assert {
        override["matcher"]["options"] for override in distribution["fieldConfig"]["overrides"]
    } == {
        "^2xx$",
        "^4xx$",
        "^5xx$",
    }

    user_expression = panels["User request rate by route and status class"]["targets"][0]["expr"]
    operational_expression = panels["Operational request rate"]["targets"][0]["expr"]
    assert 'route!~"/(healthz|livez|metrics)"' in user_expression
    assert 'route=~"/(healthz|livez|metrics)"' in operational_expression

    availability = panels["Public endpoint availability"]
    assert {target["legendFormat"] for target in availability["targets"]} == {
        "Healthy endpoints",
        "Failed endpoints",
    }
    assert len(availability["targets"]) == 2
    assert all(
        target["instant"] is True and target["range"] is False for target in availability["targets"]
    )
    assert all("vector" not in target["expr"] for target in availability["targets"])
    assert panels["Endpoint matrix"]["type"] == "table"
    labels = {item["name"]: item["label"] for item in dashboard["templating"]["list"]}
    assert labels == {
        "environment": "Environment",
        "app": "Probe application",
        "route": "Probe route",
    }


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

    for content in ("{", "[]"):
        candidate = tmp_path / f"direct-{len(content)}.json"
        candidate.write_text(content, encoding="utf-8")
        with pytest.raises(SystemExit, match="dashboard JSON"):
            validator.load_dashboard(candidate)
    with pytest.raises(SystemExit, match="dashboard JSON"):
        validator.load_dashboard(tmp_path / "direct-missing.json")


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

    rendered = tmp_path / "direct-rendered.yaml"
    rendered.write_text(rendered_dashboard_yaml(dashboard), encoding="utf-8")
    dashboard_json = validator.validate_dashboard(DASHBOARD)
    validator.validate_render(rendered, dashboard_json)


def test_validator_accepts_single_quoted_render_scalars(tmp_path, dashboard):
    rendered = tmp_path / "single-quoted.yaml"
    content = rendered_dashboard_yaml(dashboard).replace(
        "path: /var/lib/grafana/dashboards/sugarkube",
        "path: '/var/lib/grafana/dashboards/sugarkube'",
    )
    rendered.write_text(content, encoding="utf-8")
    validator.validate_render(rendered, DASHBOARD.read_text(encoding="utf-8"))


def test_validator_main_validates_source_and_render(monkeypatch, tmp_path, dashboard):
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(rendered_dashboard_yaml(dashboard), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(VALIDATOR), str(DASHBOARD)])
    validator.main()
    monkeypatch.setattr(sys, "argv", [str(VALIDATOR), str(DASHBOARD), "--rendered", str(rendered)])
    validator.main()


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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.update(uid="wrong"), "dashboard title"),
        (lambda item: item.update(panels=[]), "panel IDs"),
        (
            lambda item: replace_metric_expression(item, "process_resident_memory_bytes", "0"),
            "missing required PromQL metrics",
        ),
        (
            lambda item: replace_metric_expression(
                item, "dspace_dchat_requests_total", "dspace_dchat_requests_total"
            ),
            "must use a safe zero fallback",
        ),
        (lambda item: item.update(links=[{"url": "https://example.invalid"}]), "raw URLs"),
        (lambda item: item.update(description="${DS_PROMETHEUS}"), "datasource placeholder"),
        (lambda item: item.update(datasource={"uid": "unexpected"}), "datasource references"),
        (
            lambda item: panel_named(item, "Status-class distribution")["targets"][0].update(
                instant=False, range=True
            ),
            "categorical instant",
        ),
        (
            lambda item: panel_named(item, "User request rate by route and status class")[
                "targets"
            ][0].update(
                expr='sum(rate(dspace_http_requests_total{environment=~"$environment"}[5m]))'
            ),
            "exclude health",
        ),
        (
            lambda item: panel_named(item, "Public endpoint availability").update(
                targets=panel_named(item, "Endpoint matrix")["targets"]
            ),
            "aggregate, fail-closed",
        ),
        (
            lambda item: item["panels"].remove(panel_named(item, "Endpoint matrix")),
            "missing required panel 'Endpoint matrix'",
        ),
    ],
)
def test_validator_directly_rejects_unsafe_dashboard_sources(
    tmp_path, dashboard, mutation, message
):
    candidate = tmp_path / "candidate.json"
    mutation(dashboard)
    candidate.write_text(json.dumps(dashboard), encoding="utf-8")
    with pytest.raises(SystemExit, match=message):
        validator.validate_dashboard(candidate)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda text: text.replace("kind: ConfigMap", "kind: Secret", 1), "intended"),
        (lambda text: text.replace("name: sugarkube", "name: other"), "one Sugarkube"),
        (
            lambda text: text.replace(
                "path: /var/lib/grafana/dashboards/sugarkube", "path: /tmp/dashboard"
            ),
            "provider path",
        ),
        (lambda text: text.replace("    |-", "    >-", 1), "block scalar is malformed"),
        (lambda text: text.replace('"refresh": "30s"', '"refresh": "5m"'), "differs"),
    ],
)
def test_validator_directly_rejects_unsafe_render_shapes(tmp_path, dashboard, mutation, message):
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(mutation(rendered_dashboard_yaml(dashboard)), encoding="utf-8")
    with pytest.raises(SystemExit, match=message):
        validator.validate_render(rendered, DASHBOARD.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda text: text.replace(
                'mountPath: "/var/lib/grafana/dashboards/sugarkube/',
                'mountPath: "/tmp/',
            ),
            "dashboard mount must be exactly",
        ),
        (
            lambda text: text.replace(
                "path: /var/lib/grafana/dashboards/sugarkube", 'path: "unterminated'
            ),
            "malformed YAML scalars",
        ),
        (lambda text: text.replace("    |-", "  |-", 1), "block scalar is misplaced"),
        (
            lambda text: text.replace('"refresh": "30s",', '"refresh": ,'),
            "contains malformed JSON",
        ),
    ],
)
def test_validator_directly_rejects_remaining_render_branches(
    tmp_path, dashboard, mutation, message
):
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(mutation(rendered_dashboard_yaml(dashboard)), encoding="utf-8")
    with pytest.raises(SystemExit, match=message):
        validator.validate_render(rendered, DASHBOARD.read_text(encoding="utf-8"))


def test_validator_directly_rejects_missing_or_empty_render(tmp_path):
    dashboard_json = DASHBOARD.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="rendered Helm output"):
        validator.validate_render(tmp_path / "missing.yaml", dashboard_json)
    rendered = tmp_path / "empty.yaml"
    rendered.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly one custom dashboard"):
        validator.validate_render(rendered, dashboard_json)


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
