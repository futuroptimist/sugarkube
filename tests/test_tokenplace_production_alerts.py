import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "platform/observability/rules/tokenplace-production.yaml"
PROD_VALUES = ROOT / "clusters/prod/observability/kube-prometheus-stack.values.yaml"
APP_METRICS = ROOT / "platform/observability/app-metrics.json"


def yaml_load(path: Path):
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load_file(ARGV[0], aliases: false))",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_tokenplace_alerts_are_production_only_and_fail_open_for_missing_capacity_telemetry():
    rules = yaml_load(RULES)["groups"][0]["rules"]
    alerts = {rule["alert"]: rule for rule in rules}
    assert set(alerts) == {"TokenplaceNoHealthyComputeNodes", "TokenplaceMetricsTargetDown"}
    capacity = alerts["TokenplaceNoHealthyComputeNodes"]
    assert capacity["for"] == "5m"
    assert "tokenplace_compute_nodes_healthy" in capacity["expr"]
    assert "tokenplace_instrumentation_up" in capacity["expr"]
    assert "up{" in capacity["expr"]
    assert 'environment="prod"' in capacity["expr"]
    assert 'cluster="sugarkube-prod"' in capacity["expr"]
    expression = " ".join(capacity["expr"].split())
    stable_labels = r"app\s*,\s*environment\s*,\s*cluster\s*,\s*namespace\s*,\s*release"
    target_labels = stable_labels + r"\s*,\s*instance\s*,\s*job"
    assert len(re.findall(rf"max\s+by\s*\(\s*{stable_labels}\s*\)", expression)) == 1
    assert len(re.findall(rf"and\s+on\s*\(\s*{target_labels}\s*\)", expression)) == 2
    assert re.search(r"tokenplace_compute_nodes_healthy\{.*?\}\s+and\s+on", expression)
    assert re.search(r"max\s+by\s*\(.*?\)\s*\(.*\)\s*==\s*0$", expression)
    for fallback in ("absent(", "vector(0)", "queue_depth"):
        assert fallback not in capacity["expr"]
    assert alerts["TokenplaceMetricsTargetDown"]["for"] == "10m"


def test_production_route_is_an_exact_tokenplace_allowlist():
    prod = yaml_load(PROD_VALUES)
    routes = prod["alertmanager"]["config"]["route"]["routes"]
    route = next(route for route in routes if route["receiver"] == "pagerduty-tokenplace")
    assert route["matchers"] == [
        'alertname=~"^(TokenplaceNoHealthyComputeNodes|TokenplaceMetricsTargetDown)$"',
        'application="tokenplace"',
        'environment="prod"',
        'cluster="sugarkube-prod"',
        'severity="critical"',
    ]
    assert all(
        "tokenplace" not in str(route).lower()
        for route in yaml_load(
            ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
        )["alertmanager"]["config"]["route"]["routes"]
    )


def test_production_authenticated_metrics_contract_matches_values_overlay():
    inventory = json.loads(APP_METRICS.read_text(encoding="utf-8"))
    cfg = inventory["applications"]["tokenplace"]["environments"]["prod"]
    assert cfg["namespace"] == "tokenplace"
    assert cfg["secret"] == {"name": "tokenplace-prod-metrics-token", "key": "token"}
    assert cfg["publicMetrics"] == {
        "url": "https://token.place/metrics",
        "expectedUnauthenticatedStatus": 401,
    }
    assert cfg["serviceMonitor"]["interval"] == "30s"
    assert cfg["serviceMonitor"]["scrapeTimeout"] == "10s"
    assert cfg["targetLabels"] == {
        "app": "tokenplace",
        "environment": "prod",
        "release": "tokenplace",
        "cluster": "sugarkube-prod",
        "namespace": "tokenplace",
    }
    values = yaml_load(ROOT / "docs/examples/tokenplace.values.prod.yaml")
    assert values["metrics"] == {
        "enabled": True,
        "auth": {"existingSecret": "tokenplace-prod-metrics-token", "secretKey": "token"},
    }
    assert values["serviceMonitor"]["enabled"] is True
    assert values["serviceMonitor"]["relabelings"] == {
        "app": "tokenplace",
        "environment": "prod",
        "release": "tokenplace",
        "cluster": "sugarkube-prod",
    }
