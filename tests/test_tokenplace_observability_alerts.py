import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "platform/observability/rules/tokenplace-production.yaml"
VALUES = ROOT / "docs/examples/tokenplace.values.prod.yaml"
INVENTORY = ROOT / "platform/observability/app-metrics.json"


def yaml_load(path):
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
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_production_metrics_contract_and_values_are_exact():
    cfg = json.loads(INVENTORY.read_text())["applications"]["tokenplace"]["environments"]["prod"]
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
    assert {
        "tokenplace_compute_nodes_registered",
        "tokenplace_compute_nodes_healthy",
        "tokenplace_compute_node_lease_age_seconds",
        "tokenplace_instrumentation_up",
    } <= set(cfg["requiredMetricFamilies"])
    values = yaml_load(VALUES)
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


def test_rules_are_production_only_explicit_and_telemetry_safe():
    alerts = {rule["alert"]: rule for rule in yaml_load(RULES)["groups"][0]["rules"]}
    assert set(alerts) == {"TokenplaceNoHealthyComputeNodes", "TokenplaceMetricsTargetDown"}
    zero = alerts["TokenplaceNoHealthyComputeNodes"]
    assert zero["for"] == "5m"
    assert "tokenplace_compute_nodes_healthy" in zero["expr"]
    assert "tokenplace_instrumentation_up" in zero["expr"] and "up{" in zero["expr"]
    assert all(needle not in zero["expr"] for needle in ("absent(", "vector(0)", "queue"))
    down = alerts["TokenplaceMetricsTargetDown"]
    assert down["for"] == "10m"
    assert (
        "kube_pod_container_status_ready" in down["expr"]
        and "unless on (namespace, pod)" in down["expr"]
    )
    for rule in alerts.values():
        assert rule["labels"] == {
            "application": "tokenplace",
            "environment": "prod",
            "cluster": "sugarkube-prod",
            "severity": "critical",
        }
        assert rule["annotations"]["runbook_url"].startswith(
            "https://github.com/futuroptimist/sugarkube/blob/main/docs/apps/tokenplace.md#"
        )
