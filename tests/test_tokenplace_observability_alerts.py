"""Static contracts for production token.place capacity alerting."""

import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "platform/observability/rules/tokenplace-production.yaml"
METRICS = ROOT / "platform/observability/app-metrics.json"
PROD_VALUES = ROOT / "docs/examples/tokenplace.values.prod.yaml"


def test_production_metrics_contract_extends_authenticated_staging_contract():
    inventory = json.loads(METRICS.read_text(encoding="utf-8"))
    environments = inventory["applications"]["tokenplace"]["environments"]
    staging, prod = environments["staging"], environments["prod"]
    assert prod["namespace"] == "tokenplace"
    assert prod["secret"] == {"name": "tokenplace-prod-metrics-token", "key": "token"}
    assert prod["publicMetrics"] == {
        "url": "https://token.place/metrics",
        "expectedUnauthenticatedStatus": 401,
    }
    assert prod["serviceMonitor"]["interval"] == staging["serviceMonitor"]["interval"] == "30s"
    assert prod["serviceMonitor"]["scrapeTimeout"] == "10s"
    assert prod["requiredMetricFamilies"] == staging["requiredMetricFamilies"]
    assert prod["forbiddenApplicationLabels"] == staging["forbiddenApplicationLabels"]
    assert prod["targetLabels"] == {
        "app": "tokenplace",
        "environment": "prod",
        "release": "tokenplace",
        "cluster": "sugarkube-prod",
        "namespace": "tokenplace",
    }


def test_production_chart_values_enable_authenticated_metrics_and_monitor():
    values = yaml.safe_load(PROD_VALUES.read_text(encoding="utf-8"))
    assert values["metrics"] == {
        "enabled": True,
        "auth": {"existingSecret": "tokenplace-prod-metrics-token", "secretKey": "token"},
    }
    assert values["serviceMonitor"] == {
        "enabled": True,
        "interval": "30s",
        "scrapeTimeout": "10s",
        "additionalLabels": {"release": "kube-prometheus-stack"},
        "relabelings": {
            "app": "tokenplace",
            "environment": "prod",
            "release": "tokenplace",
            "cluster": "sugarkube-prod",
        },
    }


def test_capacity_rule_is_explicit_zero_and_telemetry_gated():
    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"][0]["rules"]
    alerts = {rule["alert"]: rule for rule in rules}
    zero = alerts["TokenplaceNoHealthyComputeNodes"]
    assert zero["for"] == "5m"
    assert "tokenplace_compute_nodes_healthy" in zero["expr"]
    assert "tokenplace_instrumentation_up" in zero["expr"]
    assert "up{" in zero["expr"]
    assert "== 0" in zero["expr"] and "== 1" in zero["expr"]
    assert not any(term in zero["expr"] for term in ("absent(", "vector(0)", "queue"))
    assert zero["labels"] == {
        "application": "tokenplace",
        "environment": "prod",
        "cluster": "sugarkube-prod",
        "severity": "critical",
    }
    down = alerts["TokenplaceMetricsTargetDown"]
    assert down["for"] == "10m"
    assert "kube_pod_container_status_ready" in down["expr"] and " unless " in down["expr"]


def test_prometheus_rule_scenarios():
    result = subprocess.run(
        [
            "promtool",
            "test",
            "rules",
            str(ROOT / "tests/prometheus/tokenplace-production.test.yaml"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
