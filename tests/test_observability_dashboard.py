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
TEMPLATE = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"
sys.path.insert(0, str(ROOT))
from scripts import generate_observability_dashboards as generator  # noqa: E402
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


def test_public_availability_summary_includes_gitshelves_in_every_expression(dashboards):
    expected_fleet = "blackbox-(dspace|tokenplace|danielsmith|jobbot3000|gitshelves)"
    documents = [json.loads(TEMPLATE.read_text(encoding="utf-8")), *dashboards]
    for document in documents:
        expressions = [
            target["expr"]
            for target in panel(document, "Public availability summary")["targets"]
        ]
        assert len(expressions) == 3
        assert all(expected_fleet in expression for expression in expressions)


def test_finalized_staging_evidence_link_is_current(dashboards):
    expected = "deployment-evidence/dspace/staging/main-22f506e-20260817T094911Z.json"
    stale = "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"
    for document in dashboards:
        rendered = json.dumps(document)
        assert expected in rendered
        assert stale not in rendered


def test_generator_write_check_and_stale_exit_paths(tmp_path, monkeypatch, capsys):
    profiles = {
        name: {**profile, "path": tmp_path / f"{name}.json"}
        for name, profile in generator.PROFILES.items()
    }
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator, "PROFILES", profiles)

    monkeypatch.setattr(sys, "argv", [str(GENERATOR), "--check"])
    assert generator.main() == 1
    assert "staging, prod" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", [str(GENERATOR), "--write"])
    assert generator.main() == 0
    assert capsys.readouterr().out.count("wrote") == 2

    monkeypatch.setattr(sys, "argv", [str(GENERATOR), "--check"])
    assert generator.main() == 0
    assert "are current" in capsys.readouterr().out


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
    for title in (
        "Image-pin agreement",
        "DSPACE metrics-target health",
        "/chat synthetic result and freshness",
    ):
        assert all(
            expression.endswith(validator.CAPABILITY_PRESENCE_GATE)
            for expression in expressions[title]
        )
    image_pin = expressions["Image-pin agreement"][0]
    assert '"^(docker-pullable://)?(.*)$"' in image_pin
    assert '"image_id", "unknown"' in image_pin
    assert '"image_spec", "unknown"' in image_pin
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


def test_http_5xx_ratios_use_request_family_gated_zero(dashboards):
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for document in (template, *dashboards):
        for title, expected in validator.HTTP_5XX_EXPRESSIONS.items():
            expression = panel(document, title)["targets"][0]["expr"]
            assert expression == expected
            assert "or on() (0 * sum(rate(" in expression
            assert "or vector(0)" not in expression

    dspace = validator.HTTP_5XX_EXPRESSIONS["5xx error ratio"]
    assert dspace.count("dspace_http_requests_total") == 3
    assert dspace.count('environment=~"$environment"') == 3
    assert dspace.count('status_class="5xx"') == 1

    tokenplace = validator.HTTP_5XX_EXPRESSIONS["token.place HTTP 5xx ratio"]
    assert tokenplace.count("tokenplace_http_requests_total") == 3
    for label_filter in (
        'app="tokenplace"',
        'environment=~"$environment"',
        'release="tokenplace"',
        'cluster=~"$cluster"',
        'namespace="tokenplace"',
    ):
        assert tokenplace.count(label_filter) == 3
    assert tokenplace.count('status_class="5xx"') == 1


@pytest.mark.parametrize("title", validator.HTTP_5XX_EXPRESSIONS)
def test_validator_rejects_ungated_5xx_ratio(tmp_path, dashboards, title):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    target = panel(changed, title)["targets"][0]
    target["expr"] = target["expr"].replace("0 * sum(rate(", "sum(rate(", 1)
    with pytest.raises(SystemExit, match="request-family-gated zero"):
        validator._validate_semantics(changed)


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
    ("title", "target_index"),
    [
        ("Image-pin agreement", 0),
        ("DSPACE metrics-target health", 0),
        ("/chat synthetic result and freshness", 0),
        ("/chat synthetic result and freshness", 1),
    ],
)
def test_capability_outer_presence_gate_is_required(tmp_path, dashboards, title, target_index):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    target = panel(changed, title)["targets"][target_index]
    assert target["expr"].endswith(validator.CAPABILITY_PRESENCE_GATE)
    target["expr"] = target["expr"][: -len(validator.CAPABILITY_PRESENCE_GATE)].rstrip()
    with pytest.raises(SystemExit, match="capability-presence"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


def test_raw_ip_legend_is_rejected(tmp_path, dashboards):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    panel(changed, "Scrape availability by job")["targets"][0]["legendFormat"] = "{{ip}}"
    with pytest.raises(SystemExit, match="forbidden raw identity label"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


@pytest.mark.parametrize(
    "mutation",
    [
        "object-count",
        "ids",
        "grid-type",
        "grid-bounds",
        "grid-overlap",
        "table-count",
        "table-target",
        "table-transform-count",
        "table-columns",
        "table-exclusions",
        "variable-shape",
        "constant-variable",
        "query-variable",
        "build-info",
        "external-cluster",
        "token-scope",
        "token-zero",
        "event-capability",
        "image-zero",
        "image-prefix",
        "image-metadata",
        "chat-capability",
        "blackbox-environment",
    ],
)
def test_semantic_contract_rejects_invalid_dashboard_mutations(dashboards, mutation):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    scrape_table = panel(changed, "Scrape availability by job")
    if mutation == "object-count":
        changed["panels"].pop()
    elif mutation == "ids":
        changed["panels"][0]["id"] = 99
    elif mutation == "grid-type":
        changed["panels"][1]["gridPos"]["x"] = "0"
    elif mutation == "grid-bounds":
        changed["panels"][1]["gridPos"]["w"] = 25
    elif mutation == "grid-overlap":
        changed["panels"][2]["gridPos"] = changed["panels"][1]["gridPos"]
    elif mutation == "table-count":
        scrape_table["type"] = "stat"
    elif mutation == "table-target":
        scrape_table["targets"][0]["range"] = True
    elif mutation == "table-transform-count":
        scrape_table["transformations"] = []
    elif mutation == "table-columns":
        scrape_table["transformations"][0]["options"]["indexByName"] = {}
    elif mutation == "table-exclusions":
        scrape_table["transformations"][0]["options"]["excludeByName"].pop("Time")
    elif mutation == "variable-shape":
        changed["templating"]["list"][3]["name"] = "path"
    elif mutation == "constant-variable":
        changed["templating"]["list"][0]["hide"] = 0
    elif mutation == "query-variable":
        changed["templating"]["list"][2]["includeAll"] = False
    elif mutation == "build-info":
        changed["panels"][1]["targets"][0]["expr"] = "kube_state_metrics_build_info"
    elif mutation == "external-cluster":
        changed["panels"][1]["targets"][0]["expr"] = 'up{cluster="remote"}'
    elif mutation == "token-scope":
        panel(changed, next(iter(validator.TOKENPLACE_DATA_TITLES)))["targets"][0]["expr"] = "up"
    elif mutation == "token-zero":
        panel(changed, next(iter(validator.TOKENPLACE_DATA_TITLES)))["targets"][0][
            "expr"
        ] += " or vector(0)"
    elif mutation == "event-capability":
        panel(changed, "dChat request activity")["targets"][0][
            "expr"
        ] = "dspace_dchat_requests_total"
    elif mutation == "image-zero":
        panel(changed, "Image-pin agreement")["targets"][0]["expr"] = panel(
            changed, "Image-pin agreement"
        )["targets"][0]["expr"].replace("0 * count(", "count(", 1)
    elif mutation == "image-prefix":
        panel(changed, "Image-pin agreement")["targets"][0]["expr"] = panel(
            changed, "Image-pin agreement"
        )["targets"][0]["expr"].replace('"^(docker-pullable://)?(.*)$"', '"(.*)"')
    elif mutation == "image-metadata":
        panel(changed, "Image-pin agreement")["targets"][0]["expr"] = panel(
            changed, "Image-pin agreement"
        )["targets"][0]["expr"].replace('"image_id", "unknown"', '"image_id", "missing"')
    elif mutation == "chat-capability":
        panel(changed, "/chat synthetic result and freshness")["targets"][0]["expr"] = panel(
            changed, "/chat synthetic result and freshness"
        )["targets"][0]["expr"].replace("0 * count(", "count(", 1)
    else:
        blackbox = next(
            target
            for item in changed["panels"]
            for target in item.get("targets", [])
            if "blackbox-" in target.get("expr", "")
        )
        blackbox["expr"] = blackbox["expr"].replace("-$environment-.*", "-prod-.*")
    with pytest.raises(SystemExit):
        validator._validate_semantics(changed)


@pytest.mark.parametrize(
    "expression",
    [
        "up",
        "(up)",
        f"up {validator.CAPABILITY_PRESENCE_GATE}",
        f"(up) + 1 {validator.CAPABILITY_PRESENCE_GATE}",
        f"((up) {validator.CAPABILITY_PRESENCE_GATE}",
        f'((label_replace(up, "x", "\\"", "y", ".*"))) extra {validator.CAPABILITY_PRESENCE_GATE}',
    ],
)
def test_outer_capability_gate_parser_rejects_malformed_expressions(expression):
    assert not validator._has_outer_capability_presence_gate(expression)


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


@pytest.mark.parametrize(
    "mutation",
    [
        "dashboard-count",
        "configmap-identity",
        "provider-count",
        "provider-path",
        "mount",
        "block-marker",
        "payload",
    ],
)
def test_render_validation_fails_closed(tmp_path, dashboards, mutation):
    staging, _ = dashboards
    dashboard_json = json.dumps(staging)
    manifest = rendered_manifest(staging)
    if mutation == "dashboard-count":
        manifest = manifest.replace(f'"uid": "{staging["uid"]}"', '"uid": "wrong"')
    elif mutation == "configmap-identity":
        manifest = manifest.replace("dashboard-provider: sugarkube", "dashboard-provider: other")
    elif mutation == "provider-count":
        manifest = manifest.replace("name: sugarkube", "name: other", 1)
    elif mutation == "provider-path":
        manifest = manifest.replace(
            "/var/lib/grafana/dashboards/sugarkube\n---", "/tmp/dashboards\n---"
        )
    elif mutation == "mount":
        manifest = manifest.replace("subPath:", "otherPath:")
    elif mutation == "block-marker":
        manifest = manifest.replace("    |-\n", "    >-\n", 1)
    else:
        manifest = manifest.replace("      {\n", "      not-json\n", 1)
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(manifest)
    with pytest.raises(SystemExit):
        validator.validate_render(rendered, dashboard_json)


def test_dashboard_loading_and_profile_identity_fail_closed(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("[")
    with pytest.raises(SystemExit, match="missing or malformed"):
        validator.load_dashboard(malformed)
    non_object = tmp_path / "array.json"
    non_object.write_text("[]")
    with pytest.raises(SystemExit, match="root must be an object"):
        validator.load_dashboard(non_object)
    with pytest.raises(SystemExit, match="supported profile"):
        validator.configure_profile({"uid": "unknown", "title": "Unknown"})
