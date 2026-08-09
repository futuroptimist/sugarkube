import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
PROD = ROOT / "clusters/prod/observability/dashboards/sugarkube-prod-observability.json"
GENERATOR = ROOT / "scripts/generate_observability_dashboards.py"
sys.path.insert(0, str(ROOT))
from scripts import validate_observability_dashboard as validator  # noqa: E402


@pytest.fixture
def dashboards():
    return json.loads(STAGING.read_text()), json.loads(PROD.read_text())


def panel(document, title):
    return next(item for item in document["panels"] if item["title"] == title)


def write_candidate(tmp_path, document):
    path = tmp_path / f'{document["uid"]}.json'
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_generator_check_and_outputs_are_deterministic(dashboards):
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"], cwd=ROOT, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    staging, prod = dashboards
    assert staging["panels"] == prod["panels"]
    assert len(staging["panels"]) == 60
    assert sum(item["type"] == "row" for item in staging["panels"]) == 11
    assert sum(item["type"] != "row" for item in staging["panels"]) == 49


def test_profiles_differ_only_by_allowlisted_identity(dashboards):
    staging, prod = dashboards
    differing = {key for key in staging if staging[key] != prod[key]}
    assert differing == validator.PROFILE_DIFFERENCES
    assert (staging["uid"], staging["title"], staging["tags"][-1]) == (
        "sugarkube-staging-observability",
        "Sugarkube Staging Observability",
        "staging",
    )
    assert (prod["uid"], prod["title"], prod["tags"][-1]) == (
        "sugarkube-prod-observability",
        "Sugarkube Production Observability",
        "prod",
    )
    for document, environment, cluster in (
        (staging, "staging", "sugarkube-int"),
        (prod, "prod", "sugarkube-prod"),
    ):
        variables = document["templating"]["list"]
        assert [item["name"] for item in variables] == ["environment", "cluster", "app", "route"]
        assert variables[0]["query"] == environment
        assert variables[1]["query"] == cluster
        assert all(item["hide"] == 2 and item["type"] == "constant" for item in variables[:2])
        assert all(item["allValue"] == ".*" for item in variables[2:])


def test_canonical_order_ids_grid_and_defaults(dashboards):
    staging, _ = dashboards
    rows = [item["title"] for item in staging["panels"] if item["type"] == "row"]
    assert rows == [
        "Cluster and service health",
        "Workload health",
        "Node and Prometheus capacity",
        "Observability build identity",
        "DSPACE HTTP",
        "DSPACE runtime and release",
        "DSPACE feature traffic",
        "Blackbox monitoring",
        "DSPACE release integrity",
        "token.place relay and compute capacity",
        "token.place HTTP and release",
    ]
    assert [item["id"] for item in staging["panels"]] == list(range(1, 61))
    assert panel(staging, "DSPACE instrumentation health")
    assert panel(staging, "DSPACE build identity")
    assert all(
        item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
        for item in staging["panels"]
        if item["type"] not in {"row", "text"}
    )
    validator.validate_dashboard(STAGING)
    validator.validate_dashboard(PROD)


def test_all_ten_tables_are_simultaneous_single_frames(dashboards):
    staging, _ = dashboards
    tables = [item for item in staging["panels"] if item["type"] == "table"]
    assert len(tables) == 10
    for table in tables:
        assert len(table["targets"]) == 1
        assert table["targets"][0]["format"] == "table"
        assert table["targets"][0]["instant"] is True
        assert table["targets"][0]["range"] is False
        assert [item["id"] for item in table["transformations"]] == ["organize"]
        options = table["transformations"][0]["options"]
        assert options["indexByName"] and options["renameByName"]
        assert options["excludeByName"]["Time"] is True
        assert options["excludeByName"]["__name__"] is True


def test_missing_application_capabilities_produce_no_series_not_healthy_zero(dashboards):
    _, prod = dashboards
    expressions = {
        item["title"]: [target.get("expr", "") for target in item.get("targets", [])]
        for item in prod["panels"]
    }
    for title in ("Image-pin agreement", "DSPACE metrics-target health"):
        assert "0 * count(dspace_release_approved_info" in expressions[title][0]
        assert "vector(0)" not in expressions[title][0]
    assert (
        "0 * count(dspace_release_approved_info"
        in expressions["/chat synthetic result and freshness"][0]
    )
    for title in ("dChat request activity", "token.place dependency request activity"):
        assert "0 * count(dspace_instrumentation_up" in expressions[title][0]
    token_expressions = [
        expr
        for title, values in expressions.items()
        if title.startswith("token.place")
        for expr in values
    ]
    assert not any("vector(0)" in expr for expr in token_expressions)
    # Production has no capability producer in this task; gated RHS therefore has no output.
    assert prod["templating"]["list"][0]["query"] == "prod"
    assert all(
        item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
        for item in prod["panels"]
        if item["type"] not in {"row", "text"}
    )


def test_query_scoping_and_safe_labels(dashboards):
    staging, _ = dashboards
    serialized = json.dumps(staging)
    expressions = [
        target["expr"] for item in staging["panels"] for target in item.get("targets", [])
    ]
    assert all("-$environment-.*" in expr for expr in expressions if "blackbox-" in expr)
    token_titles = validator.TOKENPLACE_DATA_TITLES
    token_expressions = [
        target["expr"] for title in token_titles for target in panel(staging, title)["targets"]
    ]
    assert all(
        'environment=~"$environment"' in expr and 'cluster=~"$cluster"' in expr
        for expr in token_expressions
    )
    core = [expr for expr in expressions if "$cluster" not in expr]
    assert not any("cluster=" in expr or "cluster=~" in expr for expr in core)
    assert "kube_state_metrics_build_info" not in serialized
    assert not any(f"{{{{{label}}}}}" in serialized for label in validator.FORBIDDEN_LABELS)


@pytest.mark.parametrize(
    "kind",
    ["title", "query", "grid", "type", "transformation", "noValue", "variable", "target-mode"],
)
def test_one_sided_canonical_mutations_fail(tmp_path, dashboards, kind):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    if kind == "title":
        changed["panels"][1]["title"] += " drift"
    elif kind == "query":
        changed["panels"][1]["targets"][0]["expr"] = "up"
    elif kind == "grid":
        changed["panels"][1]["gridPos"]["x"] += 1
    elif kind == "type":
        changed["panels"][1]["type"] = "gauge"
    elif kind == "transformation":
        panel(changed, "Scrape availability by job")["transformations"][0]["id"] = "merge"
    elif kind == "noValue":
        changed["panels"][1]["fieldConfig"]["defaults"].pop("noValue")
    elif kind == "variable":
        changed["templating"]["list"][0]["query"] = "prod"
    else:
        panel(changed, "Scrape availability by job")["targets"][0]["instant"] = False
    with pytest.raises(SystemExit):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


def rendered_manifest(document):
    uid = document["uid"]
    payload = json.dumps(document, indent=2)
    return (
        "kind: ConfigMap\nmetadata:\n"
        "  name: kube-prometheus-stack-grafana-dashboards-sugarkube\n"
        "  labels:\n    dashboard-provider: sugarkube\ndata:\n"
        f"  {uid}.json:\n    |-\n"
        + "\n".join(f"      {line}" for line in payload.splitlines())
        + "\n---\nkind: ConfigMap\ndata:\n  dashboardproviders.yaml: |\n"
        "    providers:\n      - name: sugarkube\n        options:\n"
        "          path: /var/lib/grafana/dashboards/sugarkube\n"
        "---\nkind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n"
        "        - volumeMounts:\n"
        "            - name: dashboards-sugarkube\n"
        f'              mountPath: "/var/lib/grafana/dashboards/sugarkube/{uid}.json"\n'
        f'              subPath: "{uid}.json"\n'
    )


@pytest.mark.parametrize("source", [STAGING, PROD])
def test_source_rendered_configmap_equality(tmp_path, source):
    document = json.loads(source.read_text())
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(rendered_manifest(document))
    dashboard_json = validator.validate_dashboard(source)
    validator.validate_render(rendered, dashboard_json)
    drifted = copy.deepcopy(document)
    drifted["panels"][1]["title"] += " drift"
    rendered.write_text(rendered_manifest(drifted))
    with pytest.raises(SystemExit, match="differs"):
        validator.validate_render(rendered, dashboard_json)
