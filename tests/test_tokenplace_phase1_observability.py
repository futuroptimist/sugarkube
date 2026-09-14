"""Repository contracts for the token.place Phase 1 metrics integration."""

import json
import subprocess
from pathlib import Path

from scripts.generate_observability_dashboards import PROFILES, render

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "platform/observability/app-metrics.json"
TEMPLATE = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"

METRIC_FAMILIES = {
    "tokenplace_compute_nodes_registered",
    "tokenplace_compute_nodes_healthy",
    "tokenplace_compute_node_lease_age_seconds",
    "tokenplace_compute_node_evictions_total",
    "tokenplace_relay_queue_depth",
    "tokenplace_relay_oldest_queued_request_age_seconds",
    "tokenplace_relay_in_flight_requests",
    "tokenplace_relay_oldest_in_flight_age_seconds",
    "tokenplace_relay_request_outcomes_total",
    "tokenplace_http_requests_total",
    "tokenplace_http_request_duration_seconds_bucket",
    "tokenplace_instrumentation_up",
    "tokenplace_build_info",
}
BOUNDED_LABELS = {
    "reason": {"stale_lease", "unregistered", "capacity_loss"},
    "provider_mode": {"relay", "direct", "unknown"},
    "outcome": {
        "completed",
        "cancelled",
        "expired",
        "timed_out",
        "rate_limited",
        "dependency_failure",
        "failed",
    },
}


def yaml_load(path: Path):
    result = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e",
         "puts JSON.generate(YAML.safe_load_file(ARGV[0], aliases: false))", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def inventory():
    return json.loads(INVENTORY.read_text(encoding="utf-8"))["applications"]["tokenplace"]


def dashboard_expressions(document):
    return {
        panel["title"]: [target["expr"] for target in panel.get("targets", [])]
        for panel in document["panels"]
    }


def test_staging_and_production_scrape_contracts_use_secret_references_only():
    configs = inventory()["environments"]
    for environment, cluster in (("staging", "sugarkube-int"), ("prod", "sugarkube-prod")):
        cfg = configs[environment]
        secret = {"name": f"tokenplace-{environment}-metrics-token", "key": "token"}
        monitor = cfg["serviceMonitor"]
        assert cfg["secret"] == secret
        assert monitor["authorization"] == {"type": "Bearer", "credentials": secret}
        assert monitor["credentialsLocation"] == "authorization.credentials"
        assert monitor["selectorMatchLabels"] == {
            "app.kubernetes.io/instance": "tokenplace",
            "app.kubernetes.io/name": "tokenplace",
        }
        assert (monitor["interval"], monitor["scrapeTimeout"], monitor["path"]) == (
            "30s",
            "10s",
            "/metrics",
        )
        assert cfg["targetLabels"] == {
            "app": "tokenplace",
            "environment": environment,
            "release": "tokenplace",
            "cluster": cluster,
            "namespace": "tokenplace",
        }

        values = yaml_load(ROOT / f"docs/examples/tokenplace.values.{environment}.yaml")
        assert values["metrics"] == {
            "enabled": True,
            "auth": {"existingSecret": secret["name"], "secretKey": "token"},
        }
        assert values["serviceMonitor"]["enabled"] is True
        assert values["serviceMonitor"]["interval"] == "30s"
        assert values["serviceMonitor"]["scrapeTimeout"] == "10s"
        assert values["serviceMonitor"]["additionalLabels"] == {
            "release": "kube-prometheus-stack"
        }
        assert values["serviceMonitor"]["relabelings"] == {
            "app": "tokenplace",
            "environment": environment,
            "release": "tokenplace",
            "cluster": cluster,
        }
        serialized = json.dumps(values).lower()
        assert not any(key in values for key in ("secret", "data", "stringData"))
        assert "bearer " not in serialized


def test_each_environment_requires_all_phase1_families_and_bounded_dimensions():
    for cfg in inventory()["environments"].values():
        assert set(cfg["requiredMetricFamilies"]) == METRIC_FAMILIES
        for label, values in BOUNDED_LABELS.items():
            assert set(cfg["allowedApplicationLabels"][label]) == values
        assert BOUNDED_LABELS.keys() <= cfg["allowedApplicationLabels"].keys()
        assert {"token", "authorization", "user", "email"} <= set(
            cfg["forbiddenApplicationLabels"]
        )


def test_dashboard_covers_phase1_promql_with_bounded_aggregations_and_no_data():
    document = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    expressions = dashboard_expressions(document)
    combined = "\n".join(expr for targets in expressions.values() for expr in targets)
    assert all(family in combined for family in METRIC_FAMILIES)
    assert "sum by (reason) (rate(tokenplace_compute_node_evictions_total" in combined
    for family in (
        "tokenplace_relay_queue_depth",
        "tokenplace_relay_oldest_queued_request_age_seconds",
        "tokenplace_relay_in_flight_requests",
        "tokenplace_relay_oldest_in_flight_age_seconds",
    ):
        assert f"max by (provider_mode) ({family}" in combined
    assert "sum by (outcome) (rate(tokenplace_relay_request_outcomes_total" in combined
    assert "sum by (route, status_class) (rate(tokenplace_http_requests_total" in combined
    assert 'status_class="5xx"' in combined
    assert "histogram_quantile(.95" in combined
    tokenplace_expressions = "\n".join(
        expr for title, targets in expressions.items() if title.startswith("token.place")
        for expr in targets
    )
    assert "or vector(0)" not in tokenplace_expressions
    for panel in document["panels"]:
        if panel["type"] not in {"row", "text"}:
            assert panel["fieldConfig"]["defaults"]["noValue"] == "NO DATA"


def test_checked_in_dashboards_are_exact_generator_outputs():
    for profile in PROFILES.values():
        assert profile["path"].read_text(encoding="utf-8") == render(profile)
