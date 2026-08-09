import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
PROD_DASHBOARD = ROOT / "clusters/prod/observability/dashboards/sugarkube-prod-observability.json"
VALIDATOR = ROOT / "scripts/validate_observability_dashboard.py"
SCRIPT = ROOT / "scripts/observability_helm.sh"
PROMETHEUS_VALUES = ROOT / "platform/observability/helm/kube-prometheus-stack.values.common.yaml"

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


def replace_panel_expression(document, title, replacement):
    panel = next(panel for panel in all_panels(document) if panel["title"] == title)
    panel["targets"][0]["expr"] = replacement


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
        "DSPACE release integrity",
        "token.place relay and compute capacity",
        "token.place HTTP and release",
    }
    titles = {panel["title"] for panel in panels}
    for title in (
        "DSPACE scrape availability",
        "Instrumentation health",
        "Public availability summary",
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
        "token.place scrape availability",
        "token.place instrumentation health",
        "token.place compute-node counts",
        "token.place oldest compute-node lease age",
        "token.place compute-node eviction rate",
        "token.place relay queue depth",
        "token.place oldest queued-request age",
        "token.place in-flight requests by pod",
        "token.place oldest in-flight age by pod",
        "token.place terminal outcome rate",
        "token.place HTTP request rate",
        "token.place HTTP 5xx ratio",
        "token.place HTTP latency percentiles",
        "token.place build identity",
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
    assert "http://" not in serialized
    assert serialized.count("https://github.com/futuroptimist/sugarkube/blob/main/") == 2
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


def test_tokenplace_queries_are_replica_safe_bounded_and_preserve_missing_data(dashboard):
    panels = {panel["title"]: panel for panel in all_panels(dashboard)}
    token_panels = [panels[title] for title in validator.TOKENPLACE_PANELS]
    expressions = [target["expr"] for panel in token_panels for target in panel["targets"]]
    selector = (
        'app="tokenplace",environment=~"$environment",release="tokenplace",'
        'cluster="sugarkube-int",namespace="tokenplace"'
    )
    assert all(selector in expression for expression in expressions)
    assert all("vector(0)" not in expression for expression in expressions)
    assert all(panel["fieldConfig"]["defaults"]["noValue"] == "NO DATA" for panel in token_panels)

    counts = panels["token.place compute-node counts"]
    assert all(target["expr"].startswith("max(") for target in counts["targets"])
    assert panels["token.place relay queue depth"]["targets"][0]["expr"].startswith(
        "max by (provider_mode)"
    )
    assert panels["token.place in-flight requests by pod"]["targets"][0]["expr"].startswith(
        "max by (pod)"
    )
    assert (
        "sum by (reason) (rate("
        in panels["token.place compute-node eviction rate"]["targets"][0]["expr"]
    )
    assert (
        "sum by (outcome) (rate("
        in panels["token.place terminal outcome rate"]["targets"][0]["expr"]
    )
    assert (
        "sum by (route, status_class) (rate("
        in panels["token.place HTTP request rate"]["targets"][0]["expr"]
    )

    latency = panels["token.place HTTP latency percentiles"]
    assert len(latency["targets"]) == 3
    assert all("histogram_quantile(" in target["expr"] for target in latency["targets"])
    assert all("sum by (le, route)" in target["expr"] for target in latency["targets"])
    rate_expressions = [expression for expression in expressions if "rate(" in expression]
    assert rate_expressions
    assert all("[$__rate_interval]" in expression for expression in rate_expressions)
    validator.validate_tokenplace_semantics(dashboard)
    build = panels["token.place build identity"]["targets"][0]
    assert build["expr"].startswith("max by (pod, version, revision)")
    assert build["legendFormat"] == "{{pod}} {{version}} {{revision}}"


@pytest.mark.parametrize(
    "title",
    ["token.place scrape availability", "token.place instrumentation health"],
)
@pytest.mark.parametrize("missing_flag", ["instant", "range"])
def test_validator_rejects_missing_health_query_flags(dashboard, title, missing_flag):
    changed = json.loads(json.dumps(dashboard))
    panel = next(panel for panel in all_panels(changed) if panel["title"] == title)
    panel["targets"][0].pop(missing_flag)
    with pytest.raises(SystemExit, match="instant-only"):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    ("title", "mutation"),
    [
        ("token.place HTTP 5xx ratio", lambda panel: panel.update(targets=[])),
        (
            "token.place terminal outcome rate",
            lambda panel: panel["targets"][0].update(
                expr=panel["targets"][0]["expr"].replace(
                    "tokenplace_relay_request_outcomes_total",
                    "tokenplace_compute_node_evictions_total",
                )
            ),
        ),
    ],
)
def test_validator_rejects_empty_or_metric_swapped_panels(dashboard, title, mutation):
    changed = json.loads(json.dumps(dashboard))
    mutation(next(panel for panel in all_panels(changed) if panel["title"] == title))
    with pytest.raises(SystemExit):
        validator.validate_tokenplace_semantics(changed)


def test_validator_rejects_queued_age_grouped_away_from_provider_mode(dashboard):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel
        for panel in all_panels(changed)
        if panel["title"] == "token.place oldest queued-request age"
    )
    panel["targets"][0]["expr"] = panel["targets"][0]["expr"].replace(
        "by (provider_mode)", "by (pod)"
    )
    with pytest.raises(SystemExit, match="provider_mode"):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize("mutation", ["4xx", "unclamped"])
def test_validator_rejects_unsafe_http_5xx_ratio(dashboard, mutation):
    changed = json.loads(json.dumps(dashboard))
    target = next(
        panel for panel in all_panels(changed) if panel["title"] == "token.place HTTP 5xx ratio"
    )["targets"][0]
    if mutation == "4xx":
        target["expr"] = target["expr"].replace('status_class="5xx"', 'status_class="4xx"')
    else:
        target["expr"] = target["expr"].replace("clamp_min(", "(").replace(", 1e-9)", ")")
    with pytest.raises(SystemExit, match="5xx ratio"):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    ("label", "location"),
    [
        ("remote_addr", "matcher"),
        ("node_id", "grouping"),
        ("remote_addr", "legend"),
    ],
)
def test_validator_rejects_unknown_tokenplace_labels(dashboard, label, location):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel for panel in all_panels(changed) if panel["title"] == "token.place relay queue depth"
    )
    target = panel["targets"][0]
    if location == "matcher":
        target["expr"] = target["expr"].replace(
            'namespace="tokenplace"', f'namespace="tokenplace",{label}="raw"'
        )
    elif location == "grouping":
        target["expr"] = target["expr"].replace(
            "by (provider_mode)", f"by (provider_mode, {label})"
        )
    else:
        target["legendFormat"] = f"{{{{provider_mode}}}} {{{{{label}}}}}"
    with pytest.raises(SystemExit):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    "metric",
    [
        "tokenplace_relay_chat_available",
        "tokenplace_relay_schedulable_compute_nodes",
        "tokenplace_relay_chat_availability_state",
        "tokenplace_relay_state_store_up",
    ],
)
def test_validator_rejects_actual_phase_two_metrics(dashboard, metric):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel for panel in all_panels(changed) if panel["title"] == "token.place relay queue depth"
    )
    panel["description"] = f"Deferred metric: {metric}"
    with pytest.raises(SystemExit, match="Phase 2"):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    ("title", "mutation", "message"),
    [
        (
            "token.place scrape availability",
            lambda expression: f"{expression} or up",
            "bare or unverified metric selector",
        ),
        (
            "token.place scrape availability",
            lambda expression: (
                f"{expression} or tokenplace_unverified_future_metric{{"
                'app="tokenplace",environment=~"$environment",release="tokenplace",'
                'cluster="sugarkube-int",namespace="tokenplace"}'
            ),
            "intended metric family",
        ),
        (
            "token.place instrumentation health",
            lambda expression: f'label_replace({expression}, "remote_addr", "raw", "pod", "(.*)")',
            "synthesize labels",
        ),
    ],
)
def test_validator_rejects_unscoped_unverified_or_synthesized_metrics(
    dashboard, title, mutation, message
):
    changed = json.loads(json.dumps(dashboard))
    panel = next(panel for panel in all_panels(changed) if panel["title"] == title)
    panel["targets"][0]["expr"] = mutation(panel["targets"][0]["expr"])
    with pytest.raises(SystemExit, match=message):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    "addition",
    [
        "process_cpu_seconds_total",
        "probe_success",
        "sum(arbitrary_external_metric_total) + 1",
    ],
)
def test_validator_rejects_any_bare_metric_selector(dashboard, addition):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel
        for panel in all_panels(changed)
        if panel["title"] == "token.place scrape availability"
    )
    expression = panel["targets"][0]["expr"]
    panel["targets"][0]["expr"] = f"({expression}) or ({addition})"
    with pytest.raises(SystemExit, match="bare or unverified metric selector"):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    "variable",
    ["$app", "$environment", "$__range", "$__rate_interval", "${app}"],
)
def test_validator_rejects_template_variables_in_metric_position(dashboard, variable):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel
        for panel in all_panels(changed)
        if panel["title"] == "token.place scrape availability"
    )
    expression = panel["targets"][0]["expr"]
    panel["targets"][0]["expr"] = f"({expression}) or ({variable})"
    with pytest.raises(SystemExit, match="template variable outside"):
        validator.validate_tokenplace_semantics(changed)


def test_validator_rejects_canonical_matchers_hidden_in_backtick_value(dashboard):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel
        for panel in all_panels(changed)
        if panel["title"] == "token.place scrape availability"
    )
    panel["targets"][0]["expr"] = (
        "min by (pod) (up{route=`"
        'app="tokenplace",environment=~"$environment",release="tokenplace",'
        'cluster="sugarkube-int",namespace="tokenplace"`})'
    )
    with pytest.raises(SystemExit, match="canonical target selector"):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    "extra_matcher",
    [
        'route=~"$app"',
        'route=~"$environment"',
        'pod=~"$__range"',
        'app="tokenplace"',
        'route="unexpected"',
    ],
)
def test_validator_rejects_extra_dynamic_matchers(dashboard, extra_matcher):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel
        for panel in all_panels(changed)
        if panel["title"] == "token.place scrape availability"
    )
    panel["targets"][0]["expr"] = panel["targets"][0]["expr"].replace(
        'namespace="tokenplace"', f'namespace="tokenplace",{extra_matcher}'
    )
    with pytest.raises(SystemExit, match="canonical target selector"):
        validator.validate_tokenplace_semantics(changed)


def test_validator_rejects_single_quoted_matcher(dashboard):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel
        for panel in all_panels(changed)
        if panel["title"] == "token.place scrape availability"
    )
    panel["targets"][0]["expr"] = panel["targets"][0]["expr"].replace(
        'app="tokenplace"', "app='tokenplace'"
    )
    with pytest.raises(SystemExit, match="canonical target selector"):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda expression: f"{expression}[$__rate_interval]",
        lambda expression: f"{expression} + rate([$__rate_interval])",
    ],
)
def test_validator_rejects_stray_rate_ranges(dashboard, mutation):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel
        for panel in all_panels(changed)
        if panel["title"] == "token.place scrape availability"
    )
    panel["targets"][0]["expr"] = mutation(panel["targets"][0]["expr"])
    with pytest.raises(SystemExit):
        validator.validate_tokenplace_semantics(changed)


def test_validator_rejects_selector_range_outside_rate(dashboard):
    changed = json.loads(json.dumps(dashboard))
    panel = next(
        panel
        for panel in all_panels(changed)
        if panel["title"] == "token.place scrape availability"
    )
    panel["targets"][0]["expr"] = panel["targets"][0]["expr"].replace("})", "}[$__rate_interval])")
    with pytest.raises(SystemExit, match="range outside"):
        validator.validate_tokenplace_semantics(changed)


@pytest.mark.parametrize(
    ("title", "mutation", "message"),
    [
        (
            "token.place compute-node eviction rate",
            lambda panel: panel["targets"][0].update(
                expr=panel["targets"][0]["expr"].replace("[$__rate_interval]", "")
            ),
            "rate ranges",
        ),
        (
            "token.place scrape availability",
            lambda panel: panel["targets"][0].update(
                expr=f'({panel["targets"][0]["expr"]}) + [5m]'
            ),
            "invalid range",
        ),
        (
            "token.place instrumentation health",
            lambda panel: panel["targets"][0].update(expr="1"),
            "intended metric family",
        ),
        (
            "token.place relay queue depth",
            lambda panel: panel["targets"][0].update(
                expr=panel["targets"][0]["expr"].replace("max by", "min by")
            ),
            "explicit max deduplication",
        ),
        (
            "token.place compute-node counts",
            lambda panel: panel["targets"][0].update(
                expr=panel["targets"][0]["expr"].replace("max(", "max by (pod) (")
            ),
            "direct max deduplication",
        ),
        (
            "token.place compute-node eviction rate",
            lambda panel: panel["targets"][0].update(
                expr=panel["targets"][0]["expr"].replace("sum by (reason)", "min")
            ),
            "summed rate",
        ),
        (
            "token.place terminal outcome rate",
            lambda panel: panel["targets"][0].update(expr=f'({panel["targets"][0]["expr"]})'),
            "directly use",
        ),
        (
            "token.place HTTP request rate",
            lambda panel: panel["targets"][0].update(
                expr=panel["targets"][0]["expr"].replace(
                    "sum by (route, status_class)", "sum by (route)"
                )
            ),
            "group by route",
        ),
        (
            "token.place build identity",
            lambda panel: panel["targets"][0].update(instant=False),
            "build identity",
        ),
        (
            "token.place HTTP latency percentiles",
            lambda panel: panel["targets"][0].update(legendFormat="p90 {{route}}"),
            "latency",
        ),
        (
            "token.place relay queue depth",
            lambda panel: panel["fieldConfig"]["defaults"].update(noValue="0"),
            "NO DATA",
        ),
        (
            "token.place scrape availability",
            lambda panel: panel["targets"][0].update(legendFormat="{{remote_addr}}"),
            "unsafe label",
        ),
    ],
)
def test_validator_rejects_tokenplace_contract_mutations(dashboard, title, mutation, message):
    changed = json.loads(json.dumps(dashboard))
    panel = next(panel for panel in all_panels(changed) if panel["title"] == title)
    mutation(panel)
    with pytest.raises(SystemExit, match=message):
        validator.validate_tokenplace_semantics(changed)


def test_validator_rejects_duplicate_panel_and_non_row_heading(dashboard):
    duplicate = json.loads(json.dumps(dashboard))
    duplicate["panels"].append(
        next(
            panel
            for panel in all_panels(duplicate)
            if panel["title"] == "token.place scrape availability"
        )
    )
    with pytest.raises(SystemExit, match="exactly one"):
        validator.validate_tokenplace_semantics(duplicate)

    non_row = json.loads(json.dumps(dashboard))
    heading = next(
        panel
        for panel in all_panels(non_row)
        if panel["title"] == "token.place relay and compute capacity"
    )
    heading["type"] = "stat"
    with pytest.raises(SystemExit, match="section headings"):
        validator.validate_tokenplace_semantics(non_row)


@pytest.mark.parametrize(
    ("title", "replacement", "message"),
    [
        (
            "token.place compute-node counts",
            "sum(tokenplace_compute_nodes_registered)",
            "canonical target selector",
        ),
        (
            "token.place terminal outcome rate",
            "sum(rate(tokenplace_relay_request_outcomes_total{"
            'app="tokenplace",environment=~"$environment",release="tokenplace",'
            'cluster="sugarkube-int",namespace="tokenplace"}[$__rate_interval])) '
            "or vector(0)",
            "substituting zero",
        ),
        (
            "token.place compute-node eviction rate",
            "sum(rate(tokenplace_compute_node_evictions_total{"
            'app="tokenplace",environment=~"$environment",release="tokenplace",'
            'cluster="sugarkube-int",namespace="tokenplace"}[$__rate_interval]))',
            "bounded reason",
        ),
        (
            "token.place in-flight requests by pod",
            "sum(tokenplace_relay_in_flight_requests{"
            'app="tokenplace",environment=~"$environment",release="tokenplace",'
            'cluster="sugarkube-int",namespace="tokenplace"})',
            "per pod",
        ),
    ],
)
def test_validator_rejects_unsafe_tokenplace_query_regressions(
    dashboard, title, replacement, message
):
    changed = json.loads(json.dumps(dashboard))
    next(panel for panel in all_panels(changed) if panel["title"] == title)["targets"][0][
        "expr"
    ] = replacement
    with pytest.raises(SystemExit, match=message):
        validator.validate_tokenplace_semantics(changed)


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
    assert distribution["type"] == "piechart"
    assert all(
        target.get("instant") is True and target.get("range") is False
        for target in distribution["targets"]
    )
    assert "increase(" in distribution["targets"][0]["expr"]
    assert "$__range" in distribution["targets"][0]["expr"]
    colors = {
        override["matcher"]["options"]: override["properties"][0]["value"]["fixedColor"]
        for override in distribution["fieldConfig"]["overrides"]
    }
    assert colors == {"2xx": "green", "4xx": "orange", "5xx": "red"}

    user_expression = panels["User request rate by route and status class"]["targets"][0]["expr"]
    operational_expression = panels["Operational request rate"]["targets"][0]["expr"]
    assert 'route!~"/(healthz|livez|metrics)"' in user_expression
    assert 'route=~"/(healthz|livez|metrics)"' in operational_expression

    summary = panels["Public availability summary"]
    assert len(summary["targets"]) == 3
    assert all(
        target["instant"] is True and target["range"] is False for target in summary["targets"]
    )
    assert {target["legendFormat"] for target in summary["targets"]} == {
        "Healthy endpoints",
        "Failed endpoints",
        "Missing probe data",
    }
    summary_expressions = {target["legendFormat"]: target["expr"] for target in summary["targets"]}
    assert "sum(" in summary_expressions["Healthy endpoints"]
    assert "== bool 1" in summary_expressions["Healthy endpoints"]
    failed_expression = summary_expressions["Failed endpoints"]
    assert "sum(" in failed_expression and "== bool 0" in failed_expression
    missing_expression = summary_expressions["Missing probe data"]
    assert "max_over_time(up{" in missing_expression
    retention = next(
        line.split(":", 1)[1].strip()
        for line in PROMETHEUS_VALUES.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("retention:")
    )
    assert f"[{retention}]" in missing_expression
    assert ">= bool 0" in missing_expression
    assert " - (sum(" in missing_expression
    assert "probe_success{" in missing_expression
    assert "or vector(0)" in missing_expression
    assert all(
        'job=~"probe/monitoring/blackbox-(dspace|tokenplace|danielsmith|jobbot3000)-staging-.*"'
        in expression
        for expression in summary_expressions.values()
    )
    missing_override = next(
        override
        for override in summary["fieldConfig"]["overrides"]
        if override["matcher"]["options"] == "Missing probe data"
    )
    assert missing_override["properties"][0]["value"]["fixedColor"] == "yellow"
    assert summary["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
    assert panels["Endpoint matrix"]["type"] == "table"

    variables = {item["name"]: item for item in dashboard["templating"]["list"]}
    assert variables["app"]["label"] == "Probe application"
    assert variables["route"]["label"] == "Probe route"


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
            lambda item: next(
                variable for variable in item["templating"]["list"] if variable["name"] == "app"
            ).update(label="Application"),
            "probe-specific visible labels",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Status-class distribution"
            ).update(type="timeseries"),
            "categorical visualization",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Status-class distribution"
            )["targets"][0].update(expr="sum(dspace_http_requests_total)"),
            "summarize the selected window",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Status-class distribution"
            )["fieldConfig"].update(overrides=[]),
            "explicit status-class colors",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Operational request rate"
            )["targets"][0].update(expr="sum(dspace_http_requests_total)"),
            "retain health and metrics routes",
        ),
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
            lambda item: next(
                target
                for panel in item["panels"]
                if panel["title"] == "Public availability summary"
                for target in panel["targets"]
                if target["legendFormat"] == "Missing probe data"
            ).update(
                expr=next(
                    target["expr"]
                    for panel in item["panels"]
                    if panel["title"] == "Public availability summary"
                    for target in panel["targets"]
                    if target["legendFormat"] == "Missing probe data"
                ).replace("[7d]", "[5m]")
            ),
            "retention-backed discovered probes",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Status-class distribution"
            )["targets"][0].update(instant=False, range=True),
            "instant selected-window query",
        ),
        (
            lambda item: next(
                panel
                for panel in item["panels"]
                if panel["title"] == "User request rate by route and status class"
            )["targets"][0].update(
                expr='sum(rate(dspace_http_requests_total{environment=~"$environment"}[5m]))'
            ),
            "exclude operational routes",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Public availability summary"
            ).update(targets=[]),
            "three-value instant aggregate summary",
        ),
        (
            lambda item: next(
                target
                for panel in item["panels"]
                if panel["title"] == "Public availability summary"
                for target in panel["targets"]
                if target["legendFormat"] == "Healthy endpoints"
            ).update(
                expr=next(
                    target["expr"]
                    for panel in item["panels"]
                    if panel["title"] == "Public availability summary"
                    for target in panel["targets"]
                    if target["legendFormat"] == "Healthy endpoints"
                ).replace("== bool 1", "== 1")
            ),
            "boolean healthy and failed sums",
        ),
        (
            lambda item: next(
                target
                for panel in item["panels"]
                if panel["title"] == "Public availability summary"
                for target in panel["targets"]
                if target["legendFormat"] == "Healthy endpoints"
            ).update(expr='count(probe_success{environment=~"$environment"} == 1)'),
            "three-value instant aggregate summary",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Public availability summary"
            )["fieldConfig"]["defaults"].update(noValue="0"),
            "distinguish healthy, failed, and no data",
        ),
        (
            lambda item: next(
                override
                for panel in item["panels"]
                if panel["title"] == "Public availability summary"
                for override in panel["fieldConfig"]["overrides"]
                if override["matcher"]["options"] == "Missing probe data"
            )["properties"][0]["value"].update(fixedColor="green"),
            "compact yellow summary value",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Endpoint matrix"
            ).update(type="stat"),
            "retain the detailed endpoint matrix",
        ),
        (
            lambda item: next(
                target
                for panel in item["panels"]
                if panel["title"] == "Public availability summary"
                for target in panel["targets"]
                if target["legendFormat"] == "Missing probe data"
            ).update(
                expr=(
                    "sum(min by (environment, app, route) (probe_success{"
                    'job=~"probe/monitoring/blackbox-'
                    '(dspace|tokenplace|danielsmith|jobbot3000)-staging-.*",'
                    'environment=~"$environment",app=~"$app",route=~"$route"'
                    "}) == bool 1)"
                )
            ),
            "missing probe data must compare",
        ),
        (
            lambda item: next(
                target
                for panel in item["panels"]
                if panel["title"] == "Public availability summary"
                for target in panel["targets"]
                if target["legendFormat"] == "Failed endpoints"
            ).pop("expr"),
            "three-value instant aggregate summary",
        ),
        (
            lambda item: next(
                panel for panel in item["panels"] if panel["title"] == "Endpoint matrix"
            ).update(title="Removed matrix"),
            "exactly one 'Endpoint matrix' panel",
        ),
        (
            lambda item: next(
                panel
                for panel in item["panels"]
                if panel["title"] == "Active build revisions by pod"
            )["targets"].clear(),
            "must contain exactly one PromQL target",
        ),
        (
            lambda item: replace_panel_expression(
                item,
                "Active build revisions by pod",
                'max by (pod, revision) (dspace_build_info{environment=~"$environment"})',
            ),
            "active build revisions must include only serving DSPACE pods",
        ),
        (
            lambda item: replace_panel_expression(
                item,
                "Image-pin agreement",
                next(
                    panel["targets"][0]["expr"]
                    for panel in all_panels(item)
                    if panel["title"] == "Image-pin agreement"
                ).replace(" or on() vector(0)", ""),
            ),
            "image-pin agreement must filter serving pods and return a healthy zero",
        ),
        (
            lambda item: replace_panel_expression(
                item,
                "DSPACE metrics-target health",
                'sum(up{namespace="dspace",service=~"dspace.*"}) / '
                'count(up{namespace="dspace",service=~"dspace.*"}) or on() vector(0)',
            ),
            "metrics-target health must count down or missing serving targets",
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


def test_validator_directly_rejects_overlapping_panels(tmp_path, dashboard):
    positioned = [panel for panel in dashboard["panels"] if panel.get("type") != "row"]
    positioned[1]["gridPos"] = dict(positioned[0]["gridPos"])
    candidate = tmp_path / "overlap.json"
    candidate.write_text(json.dumps(dashboard), encoding="utf-8")

    with pytest.raises(SystemExit, match="overlap"):
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
    assert 'DASHBOARD_VALUE="grafana.dashboards.sugarkube.${DASHBOARD_UID}.json"' in script
    assert str(DASHBOARD.relative_to(ROOT)) in script
    assert str(PROD_DASHBOARD.relative_to(ROOT)) in script
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
    assert "/api/dashboards/uid/${DASHBOARD_UID}" in body
    assert "--netrc-file" in body and "chmod 600" in body and "rm -rf" in body
    for mutation in ("helm install", "helm upgrade", "kubectl apply", "kubectl delete"):
        assert mutation not in body
    assert "credentials and response redacted" in body
    assert "--address=127.0.0.1" in body and '"service/${RELEASE}-grafana" :80' in body
    assert body.index("Forwarding\\ from") < body.index("--netrc-file")
    assert "require_tools kubectl python3 curl base64 sleep" in body


def test_production_dashboard_profile_is_live_backed_and_fail_closed():
    document = json.loads(PROD_DASHBOARD.read_text(encoding="utf-8"))
    assert validator.validate_production_dashboard(PROD_DASHBOARD)
    assert document["uid"] == "sugarkube-prod-observability"
    assert document["title"] == "Sugarkube Production Observability"
    assert document["templating"]["list"] == []
    assert {p["title"] for p in all_panels(document) if p["type"] == "row"} == validator.PROD_ROWS
    assert {p["title"] for p in all_panels(document) if p["type"] != "row"} == set(
        validator.PROD_QUERIES
    )
    changed = json.loads(json.dumps(document))
    next(p for p in all_panels(changed) if p["title"] == "Ready nodes")["targets"][0][
        "expr"
    ] += ' + up{cluster="sugarkube-prod"}'
    path = PROD_DASHBOARD.parent / ".invalid-test.json"
    try:
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(SystemExit, match="PromQL contract"):
            validator.validate_production_dashboard(path)
    finally:
        path.unlink(missing_ok=True)


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
