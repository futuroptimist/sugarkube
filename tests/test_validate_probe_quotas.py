import copy
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
METHODS = {"get": "GET", "head": "HEAD", "post": "POST"}


def probe(name="probe", *, app="custom", route="/", interval="60s", module="get", env="staging"):
    return {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "Probe",
        "metadata": {"name": name, "labels": {"app": app, "environment": env, "route": "root"}},
        "spec": {
            "interval": interval,
            "module": module,
            "targets": {"staticConfig": {"static": [f"https://public.example{route}"]}},
        },
    }


def declaration(name="probe", *, app="custom", route="/", interval="60s", method="GET"):
    return {
        "application": app,
        "environment": "staging",
        "probe": name,
        "route_class": "root",
        "route": route,
        "method": method,
        "interval": interval,
        "enabled": True,
        "bucket": "public",
        "limits": {"hourly": 1000, "daily": 1000},
        "exemptions": [],
        "scrape_fanout": 1,
        "request_multiplier": 1,
        "safety_margin": 0.1,
        "unlimited_operational": False,
    }


def run(probes, declarations, *, replicas=1, methods=METHODS):
    rendered = yaml.safe_dump_all(probes)
    return quotas.validate(
        "staging", rendered, {"version": 1, "probes": declarations}, methods, replicas
    )


def test_render_active_returns_output_and_reports_render_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(quotas, "ROOT", tmp_path)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="rendered probe")

    assert quotas.render_active("staging", runner) == "rendered probe"
    assert calls == [
        (
            ["kubectl", "kustomize", str(tmp_path / "clusters/staging/observability/probes")],
            {"capture_output": True, "text": True, "check": False},
        )
    ]

    def failing_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1)

    with pytest.raises(quotas.ContractError, match="unable to render active staging"):
        quotas.render_active("staging", failing_runner)


def test_load_modules_rejects_an_unknown_http_method(tmp_path, monkeypatch):
    values = tmp_path / "clusters/staging/observability"
    values.mkdir(parents=True)
    (values / "prometheus-blackbox-exporter.values.yaml").write_text(
        yaml.safe_dump({"config": {"modules": {"trace": {"http": {"method": "TRACE"}}}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(quotas, "ROOT", tmp_path)

    with pytest.raises(quotas.ContractError, match="invalid or missing method"):
        quotas.load_modules("staging")


def test_validate_rejects_an_unknown_environment():
    with pytest.raises(quotas.ContractError, match="environment must be staging or prod"):
        quotas.validate("development", "", {"version": 1, "probes": []}, {}, 1)


def test_sixty_second_probe_exhausts_daily_quota_but_exact_get_exemption_passes():
    item = declaration()
    with pytest.raises(quotas.ContractError, match="window=daily volume=1440"):
        run([probe()], [item])
    item["exemptions"] = [{"route": "/", "method": "GET"}]
    run([probe()], [item])


def test_exact_exemptions_enforce_method_and_route():
    for method, module in (("POST", "post"), ("HEAD", "head")):
        item = declaration(method=method)
        item["exemptions"] = [{"route": "/", "method": "GET"}]
        with pytest.raises(quotas.ContractError, match="unsafe schedule"):
            run([probe(module=module)], [item])
    item = declaration(method="HEAD")
    item["exemptions"] = [{"route": "/", "method": "HEAD"}]
    run([probe(module="head")], [item])
    for route in ("/api", "/api/", "/api/v1", "/xapi"):
        item = declaration(route=route)
        item["exemptions"] = [{"route": "/api", "method": "GET"}]
        if route == "/api":
            run([probe(route=route)], [item])
        else:
            with pytest.raises(quotas.ContractError, match="unsafe schedule"):
                run([probe(route=route)], [item])


def test_shared_bucket_aggregates_probes_and_fanout():
    items = [declaration("one", interval="10s"), declaration("two", interval="10s")]
    docs = [probe("one", interval="10s"), probe("two", interval="10s")]
    items[0]["limits"] = items[1]["limits"] = {"hourly": 700, "daily": 20000}
    with pytest.raises(quotas.ContractError, match="window=hourly volume=720"):
        run(docs, items)
    one = declaration(interval="120s")
    one.update(scrape_fanout=2, request_multiplier=3)
    one["limits"] = {"hourly": 10000, "daily": 3000}
    with pytest.raises(quotas.ContractError, match="volume=4320"):
        run([probe(interval="120s")], [one], replicas=2)


def test_hourly_and_daily_limits_are_independent():
    item = declaration(interval="60s")
    item["limits"] = {"hourly": 60, "daily": 100000}
    item["safety_margin"] = 0
    with pytest.raises(quotas.ContractError, match="window=hourly"):
        run([probe()], [item])
    item["limits"] = {"hourly": 100, "daily": 1440}
    with pytest.raises(quotas.ContractError, match="window=daily"):
        run([probe()], [item])


def test_usable_budget_boundary_fails_and_below_threshold_passes():
    item = declaration(interval="100s")
    item["limits"] = {"hourly": 40, "daily": 1000}
    item["safety_margin"] = 0.1  # ceil(3600/100) == 36 == usable hourly budget
    with pytest.raises(quotas.ContractError, match="window=hourly"):
        run([probe(interval="100s")], [item])
    item["limits"]["hourly"] = 41
    run([probe(interval="100s")], [item])


@pytest.mark.parametrize(
    ("window", "boundary_interval", "lower_interval", "higher_interval"),
    [
        ("hourly", "120s", "125s", "119s"),
        ("daily", "2880s", "3000s", "2879s"),
    ],
)
def test_exact_decimal_margin_boundary_fails_and_strictly_lower_volume_passes(
    window, boundary_interval, lower_interval, higher_interval
):
    item = declaration(interval=boundary_interval)
    item["limits"] = {"hourly": 100000, "daily": 100000}
    item["limits"][window] = 100
    item["safety_margin"] = 0.7

    with pytest.raises(quotas.ContractError, match=f"window={window}.*volume=30"):
        run([probe(interval=boundary_interval)], [item])

    item["interval"] = lower_interval
    run([probe(interval=lower_interval)], [item])

    item["interval"] = higher_interval
    with pytest.raises(quotas.ContractError, match=f"window={window}.*volume=31"):
        run([probe(interval=higher_interval)], [item])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interval", "60seconds"),
        ("interval", "0s"),
        ("interval", "-1s"),
        ("method", "TRACE"),
        ("safety_margin", -0.1),
        ("safety_margin", 1),
        ("scrape_fanout", 0),
        ("request_multiplier", -1),
        ("limits", {"hourly": 0, "daily": 10}),
        ("limits", {"daily": 10}),
    ],
)
def test_malformed_or_missing_metadata_fails_closed(field, value):
    item = declaration()
    item[field] = value
    with pytest.raises(quotas.ContractError):
        run([probe(interval=value if field == "interval" else "60s")], [item])


def test_duplicates_orphans_and_undeclared_active_probes_fail():
    item = declaration()
    with pytest.raises(quotas.ContractError, match="duplicated"):
        run([probe()], [item, copy.deepcopy(item)])
    with pytest.raises(quotas.ContractError, match="orphaned"):
        run([], [item])
    with pytest.raises(quotas.ContractError, match="lacks quota declaration"):
        run([probe()], [])


def test_fanout_must_match_effective_prometheus_replicas():
    with pytest.raises(quotas.ContractError, match="scrape_fanout contradicts"):
        run([probe()], [declaration()], replicas=2)


def test_exempt_declarations_must_share_the_same_metered_bucket_policy():
    items = [declaration("one"), declaration("two")]
    docs = [probe("one"), probe("two")]
    for item in items:
        item["exemptions"] = [{"route": "/", "method": "GET"}]
    items[1]["limits"]["daily"] = 2000
    with pytest.raises(quotas.ContractError, match="contradictory shared-bucket policy"):
        run(docs, items)


def test_unlimited_and_metered_declarations_cannot_share_a_bucket():
    items = [declaration("unlimited"), declaration("metered")]
    docs = [probe("unlimited"), probe("metered")]
    items[0].update(unlimited_operational=True, limits=None)
    with pytest.raises(quotas.ContractError, match="contradictory shared-bucket policy"):
        run(docs, items)


def test_disabled_probe_is_valid_and_zero_volume_and_unlimited_is_explicit():
    item = declaration()
    item["enabled"] = False
    run([], [item])
    item = declaration()
    item.update(unlimited_operational=True, limits=None)
    run([probe()], [item])


def test_repository_staging_and_production_rendered_graphs_validate():
    if shutil.which("kubectl") is None:
        # TODO: Environments missing kubectl should install it to exercise active graph rendering.
        # Root cause: kubectl is unavailable in some local test environments.
        # Estimated fix: Install the CI-pinned kubectl v1.28.7 and rerun this integration test.
        pytest.skip("kubectl is required to exercise active Kustomize graph rendering")
    contract = yaml.safe_load((ROOT / "config/observability/probe-quotas.yaml").read_text())
    for env in ("staging", "prod"):
        rendered = subprocess.run(
            ["kubectl", "kustomize", f"clusters/{env}/observability/probes"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        selected = {
            "version": 1,
            "probes": [x for x in contract["probes"] if x["environment"] == env],
        }
        methods, replicas = quotas.load_modules(env)
        quotas.validate(env, rendered, selected, methods, replicas)


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_validator_runs_without_site_packages_against_fixture(environment):
    result = subprocess.run(
        [
            "python3",
            "-S",
            "scripts/validate_probe_quotas.py",
            "--env",
            environment,
            "--probes",
            f"clusters/{environment}/observability/probes/public-apps.yaml",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"probe quota validation passed: environment={environment}\n"


def test_strict_yaml_reader_rejects_duplicate_members():
    with pytest.raises(quotas.YAMLInputError):
        quotas._yaml_documents("version: 1\nversion: 1\n")


def test_tokenplace_production_requires_both_corrected_exact_exemptions():
    contract = yaml.safe_load((ROOT / "config/observability/probe-quotas.yaml").read_text())
    rendered = (ROOT / "clusters/prod/observability/probes/public-apps.yaml").read_text()
    selected = {
        "version": 1,
        "probes": [x for x in contract["probes"] if x["environment"] == "prod"],
    }
    methods, replicas = quotas.load_modules("prod")
    tokenplace = [x for x in selected["probes"] if x["application"] == "tokenplace"]
    metered = [x for x in tokenplace if x["bucket"] == "public-information"]
    assert metered
    assert all(x["limits"] == {"hourly": 60, "daily": 1000} for x in metered)
    quotas.validate("prod", rendered, selected, methods, replicas)
    for name in ("blackbox-tokenplace-prod-root", "blackbox-tokenplace-prod-metadata"):
        broken = copy.deepcopy(selected)
        next(x for x in broken["probes"] if x["probe"] == name)["exemptions"] = []
        with pytest.raises(quotas.ContractError, match="unsafe schedule"):
            quotas.validate("prod", rendered, broken, methods, replicas)


def test_error_never_echoes_target_or_unrelated_secret_sentinels():
    doc = probe()
    doc["spec"]["targets"]["staticConfig"]["static"] = ["https://private.invalid/?secret=SENTINEL"]
    with pytest.raises(quotas.ContractError) as error:
        run([doc], [declaration()])
    assert "private.invalid" not in str(error.value)
    assert "SENTINEL" not in str(error.value)


def assert_private_input_is_hidden(capsys, expected_diagnostic, *sentinels):
    output = capsys.readouterr()
    combined = output.out + output.err
    assert expected_diagnostic in output.err
    assert output.out == ""
    assert "Traceback" not in combined
    for sentinel in sentinels:
        assert sentinel not in combined


def test_main_privacy_hides_malformed_inventory_details(tmp_path, monkeypatch, capsys):
    contracts = tmp_path / "contracts.yaml"
    contracts.write_text(
        "probes:\n  - target: https://private.inventory.invalid/\n   secret: INVENTORY_SENTINEL\n",
        encoding="utf-8",
    )
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text("", encoding="utf-8")
    monkeypatch.setattr(quotas, "load_modules", lambda environment: ({}, 1))

    assert (
        quotas.main(["--env", "staging", "--contracts", str(contracts), "--probes", str(rendered)])
        == 1
    )
    assert_private_input_is_hidden(
        capsys,
        "probe quota validation failed: YAML input is malformed",
        "private.inventory.invalid",
        "INVENTORY_SENTINEL",
        "target:",
    )


def test_main_privacy_hides_malformed_rendered_probe_details(tmp_path, monkeypatch, capsys):
    contracts = tmp_path / "contracts.yaml"
    contracts.write_text(
        yaml.safe_dump({"version": 1, "probes": [declaration()]}), encoding="utf-8"
    )
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(
        "kind: Probe\nspec:\n  target: https://private.probe.invalid/\n   secret: PROBE_SENTINEL\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quotas, "load_modules", lambda environment: ({"get": "GET"}, 1))

    assert (
        quotas.main(["--env", "staging", "--contracts", str(contracts), "--probes", str(rendered)])
        == 1
    )
    assert_private_input_is_hidden(
        capsys,
        "probe quota validation failed: YAML input is malformed",
        "private.probe.invalid",
        "PROBE_SENTINEL",
        "target:",
    )


def test_main_privacy_hides_missing_input_path(tmp_path, capsys):
    private_path = tmp_path / "private-host.invalid-MISSING_SENTINEL.yaml"

    assert quotas.main(["--env", "staging", "--contracts", str(private_path)]) == 1
    assert_private_input_is_hidden(
        capsys,
        "probe quota validation failed: unable to read an input file",
        "private-host.invalid",
        "MISSING_SENTINEL",
        str(private_path),
    )


def test_custom_application_loads_from_temporary_config_directory(tmp_path, monkeypatch):
    (tmp_path / "probe-quotas.yaml").write_text(
        yaml.safe_dump({"version": 1, "probes": [declaration(app="new-app")]}),
        encoding="utf-8",
    )
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(yaml.safe_dump(probe(app="new-app", module="https_2xx")), encoding="utf-8")
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(tmp_path))
    # Defaults are evaluated per invocation, matching the generic app-config convention.
    assert quotas.main(["--env", "staging", "--probes", str(rendered)]) == 1
    item = declaration(app="new-app")
    item["exemptions"] = [{"route": "/", "method": "GET"}]
    (tmp_path / "probe-quotas.yaml").write_text(
        yaml.safe_dump({"version": 1, "probes": [item]}), encoding="utf-8"
    )
    assert quotas.main(["--env", "staging", "--probes", str(rendered)]) == 0


@pytest.mark.parametrize(
    "malformed",
    [
        "not-an-object",
        {key: value for key, value in declaration().items() if key != "environment"},
        {**declaration(), "environment": "development"},
    ],
)
def test_main_rejects_malformed_unselected_declarations(tmp_path, monkeypatch, malformed):
    inventory = {"version": 1, "probes": [{**declaration(), "environment": "prod"}, malformed]}
    contracts = tmp_path / "contracts.yaml"
    contracts.write_text(yaml.safe_dump(inventory), encoding="utf-8")
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text("", encoding="utf-8")
    monkeypatch.setattr(quotas, "load_modules", lambda environment: ({}, 1))

    assert (
        quotas.main(
            [
                "--env",
                "prod",
                "--contracts",
                str(contracts),
                "--probes",
                str(rendered),
            ]
        )
        == 1
    )


@pytest.mark.parametrize("environment", ["staging", "prod"])
@pytest.mark.parametrize(
    "inventory_change",
    [
        lambda inventory: inventory.update(extra=True),
        lambda inventory: inventory["probes"].append(copy.deepcopy(inventory["probes"][0])),
        lambda inventory: inventory["probes"][0].update(route="/?debug=true"),
        lambda inventory: inventory["probes"][0]["exemptions"].append(
            {"route": "/#status", "method": "GET"}
        ),
    ],
)
def test_every_environment_rejects_malformed_complete_inventory(
    tmp_path, monkeypatch, environment, inventory_change
):
    item = declaration()
    item["environment"] = "prod" if environment == "staging" else "staging"
    item["exemptions"] = [{"route": "/", "method": "GET"}]
    inventory = {"version": 1, "probes": [item]}
    inventory_change(inventory)
    contracts = tmp_path / "contracts.yaml"
    contracts.write_text(yaml.safe_dump(inventory), encoding="utf-8")
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text("", encoding="utf-8")
    monkeypatch.setattr(quotas, "load_modules", lambda selected_environment: ({}, 1))

    assert (
        quotas.main(
            ["--env", environment, "--contracts", str(contracts), "--probes", str(rendered)]
        )
        == 1
    )


def test_empty_app_config_environment_variable_uses_repository_default(tmp_path, monkeypatch):
    (tmp_path / "probe-quotas.yaml").write_text("version: 999\n", encoding="utf-8")
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", "")
    monkeypatch.setattr(quotas, "load_modules", lambda environment: ({}, 1))
    monkeypatch.setattr(quotas, "validate", lambda *args: 0)

    assert quotas.main(["--env", "staging", "--probes", str(rendered)]) == 0


def test_load_modules_uses_common_values_then_environment_override(tmp_path, monkeypatch):
    common = tmp_path / "platform" / "observability" / "helm"
    environment = tmp_path / "clusters" / "staging" / "observability"
    common.mkdir(parents=True)
    environment.mkdir(parents=True)
    (environment / "prometheus-blackbox-exporter.values.yaml").write_text(
        yaml.safe_dump({"config": {"modules": {"get": {"http": {"method": "GET"}}}}}),
        encoding="utf-8",
    )
    (common / "kube-prometheus-stack.values.common.yaml").write_text(
        yaml.safe_dump({"prometheus": {"prometheusSpec": {"replicas": 3}}}),
        encoding="utf-8",
    )
    override = environment / "kube-prometheus-stack.values.yaml"
    override.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(quotas, "ROOT", tmp_path)

    assert quotas.load_modules("staging") == ({"get": "GET"}, 3)
    override.write_text(
        yaml.safe_dump({"prometheus": {"prometheusSpec": {"replicas": 2}}}),
        encoding="utf-8",
    )
    assert quotas.load_modules("staging") == ({"get": "GET"}, 2)
