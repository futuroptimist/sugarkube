import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "platform/observability/rules/tokenplace-production-capacity.yaml"
PROD_VALUES = ROOT / "clusters/prod/observability/kube-prometheus-stack.values.yaml"
CONTRACTS = ROOT / "platform/observability/app-metrics.json"


def test_production_metrics_contract_extends_staging_safely():
    contracts = json.loads(CONTRACTS.read_text())["applications"]["tokenplace"]["environments"]
    staging, prod = contracts["staging"], contracts["prod"]
    assert prod["secret"] == {"name": "tokenplace-prod-metrics-token", "key": "token"}
    assert prod["publicMetrics"] == {
        "url": "https://token.place/metrics",
        "expectedUnauthenticatedStatus": 401,
    }
    assert prod["targetLabels"] == {
        "app": "tokenplace",
        "environment": "prod",
        "release": "tokenplace",
        "cluster": "sugarkube-prod",
        "namespace": "tokenplace",
    }
    for field in (
        "expectedTargetCount",
        "requiredMetricFamilies",
        "forbiddenApplicationLabels",
        "retries",
    ):
        assert prod[field] == staging[field]
    monitor = prod["serviceMonitor"]
    assert (monitor["interval"], monitor["scrapeTimeout"]) == ("30s", "10s")
    assert monitor["authorization"]["credentials"] == prod["secret"]


def test_production_rules_are_exact_and_telemetry_safe():
    canonical = yaml.safe_load(RULES.read_text())
    rendered = yaml.safe_load(PROD_VALUES.read_text())["additionalPrometheusRulesMap"][
        "tokenplace-production-capacity"
    ]
    assert rendered == canonical
    alerts = {r["alert"]: r for r in canonical["groups"][0]["rules"]}
    assert set(alerts) == {"TokenplaceNoHealthyComputeNodes", "TokenplaceMetricsTargetDown"}
    zero = alerts["TokenplaceNoHealthyComputeNodes"]
    assert zero["for"] == "5m"
    assert all(
        signal in zero["expr"]
        for signal in ("tokenplace_compute_nodes_healthy", "tokenplace_instrumentation_up", "up{")
    )
    assert not any(fallback in zero["expr"] for fallback in ("absent(", "vector(0)", "or vector"))
    assert zero["labels"] == {
        "application": "tokenplace",
        "environment": "prod",
        "cluster": "sugarkube-prod",
        "severity": "critical",
    }
    assert alerts["TokenplaceMetricsTargetDown"]["for"] == "10m"
