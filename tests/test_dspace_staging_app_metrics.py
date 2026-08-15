"""Regression coverage for the canonical DSPACE staging metrics contract."""

import json
from pathlib import Path

import pytest

from scripts import app_chart
from scripts import observability_app_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "platform/observability/app-metrics.json"
REQUIRED = [
    "dspace_http_requests_total",
    "dspace_http_request_duration_seconds_bucket",
    "dspace_dchat_requests_total",
    "dspace_dependency_requests_total",
    "dspace_instrumentation_up",
    "dspace_build_info",
]
ROUTES = [
    "/metrics",
    "/api/chat",
    "/",
    "/health",
    "/healthz",
    "/livez",
    "/config.json",
    "/cache-version.js",
    "/service-worker.js",
    "/_astro/*",
    "/assets/*",
    "/docs/[slug]",
    "/inventory/item/[itemId]/edit",
    "/inventory/item/[itemId]",
    "/processes/[processId]",
    "/process/[slug]",
    "/quests/[pathId]/[questId]",
    "/unknown",
]


def inventory():
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_dspace_staging_and_prod_inventory_contracts_are_exact():
    doc = inventory()
    metrics.validate_inventory(doc)
    environments = doc["applications"]["dspace"]["environments"]
    assert list(environments) == ["staging", "prod"]
    staging, prod = environments["staging"], environments["prod"]
    assert staging["namespace"] == staging["serviceMonitorName"] == "dspace"
    assert staging["expectedTargetCount"] == prod["expectedTargetCount"] == 2
    assert staging["secret"] == {"name": "dspace-staging-metrics-token", "key": "token"}
    assert staging["serviceMonitor"]["authorization"] == {
        "type": "Bearer",
        "credentials": staging["secret"],
    }
    assert staging["serviceMonitor"]["selectorMatchLabels"] == {
        "app.kubernetes.io/instance": "dspace",
        "app.kubernetes.io/name": "dspace",
    }
    assert staging["serviceMonitor"]["path"] == "/metrics"
    assert staging["serviceMonitor"]["interval"] == "30s"
    assert staging["serviceMonitor"]["scrapeTimeout"] == "10s"
    assert [r["targetLabel"] for r in staging["serviceMonitor"]["relabelings"]] == [
        "app",
        "environment",
        "namespace",
        "release",
        "cluster",
    ]
    assert staging["targetLabels"] == {
        "app": "dspace",
        "environment": "staging",
        "release": "dspace",
        "cluster": "sugarkube-int",
        "namespace": "dspace",
    }
    assert staging["publicMetrics"] == {
        "url": "https://staging.democratized.space/metrics",
        "expectedUnauthenticatedStatus": 401,
    }
    assert staging["retries"] == {"attempts": 6, "delaySeconds": 10}
    assert staging["requiredMetricFamilies"] == prod["requiredMetricFamilies"] == REQUIRED
    assert staging["forbiddenApplicationLabels"] == prod["forbiddenApplicationLabels"]
    assert staging["derivedApplicationLabels"] == prod["derivedApplicationLabels"] == {}


def test_dspace_staging_inventory_matches_values_overlay():
    values = app_chart.merged_values_document(("docs/examples/dspace.values.staging.yaml",))
    cfg = inventory()["applications"]["dspace"]["environments"]["staging"]
    assert values["environment"] == cfg["targetLabels"]["environment"]
    assert values["metrics"]["auth"] == {
        "existingSecret": cfg["secret"]["name"],
        "secretKey": cfg["secret"]["key"],
    }
    assert values["serviceMonitor"]["interval"] == cfg["serviceMonitor"]["interval"]
    assert values["serviceMonitor"]["scrapeTimeout"] == cfg["serviceMonitor"]["scrapeTimeout"]
    assert values["serviceMonitor"]["cluster"] == cfg["targetLabels"]["cluster"]
    assert f'https://{values["ingress"]["host"]}/metrics' == cfg["publicMetrics"]["url"]


def test_dspace_labels_match_immutable_source_contract_and_reject_stale_values():
    shared = {
        "method": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "UNKNOWN"],
        "route": ROUTES,
        "status_class": ["2xx", "4xx", "5xx", "unknown"],
        "provider": ["tokenplace", "openai", "none", "unknown"],
        "dependency": ["tokenplace", "openai", "unknown"],
        "outcome": [
            "success",
            "timeout",
            "rate_limited",
            "validation_error",
            "malformed_response",
            "dependency_failure",
            "server_error",
            "fallback_used",
            "fallback_unavailable",
            "unknown_error",
        ],
    }
    for cfg in inventory()["applications"]["dspace"]["environments"].values():
        for label, values in shared.items():
            assert cfg["allowedApplicationLabels"][label] == values
        for label, bad in (
            ("route", "/chat"),
            ("route", "*"),
            ("route", "/arbitrary/*"),
            ("provider", "token-place"),
            ("dependency", "token-place"),
            ("outcome", "error"),
            ("outcome", "anything"),
        ):
            with pytest.raises(metrics.Error, match="enum mismatch"):
                metrics.validate_metric_labels(cfg, {label: bad})


@pytest.mark.parametrize(
    "field,staging_value,prod_value",
    [
        ("secret", "dspace-prod-metrics-token", "dspace-staging-metrics-token"),
        ("cluster", "sugarkube-prod", "sugarkube-int"),
        ("environment", "prod", "staging"),
        ("url", "https://democratized.space/metrics", "https://staging.democratized.space/metrics"),
    ],
)
def test_dspace_environment_cross_contamination_is_rejected(field, staging_value, prod_value):
    for env, value in (("staging", staging_value), ("prod", prod_value)):
        doc = inventory()
        cfg = doc["applications"]["dspace"]["environments"][env]
        if field == "secret":
            cfg["secret"]["name"] = value
            cfg["serviceMonitor"]["authorization"]["credentials"]["name"] = value
        elif field == "url":
            cfg["publicMetrics"]["url"] = value
        else:
            cfg["targetLabels"][field] = value
        with pytest.raises(metrics.Error):
            metrics.validate_inventory(doc)


def test_dspace_staging_secret_check_returns_only_redacted_status(monkeypatch, capsys):
    cfg = inventory()["applications"]["dspace"]["environments"]["staging"]
    seen = []
    monkeypatch.setattr(
        metrics,
        "run",
        lambda args: seen.append(args) or "dspace\tdspace-staging-metrics-token\tnonempty",
    )
    metrics.check_secret(cfg)
    command = seen[0]
    assert command[:7] == [
        "kubectl",
        "-n",
        "dspace",
        "get",
        "secret",
        "dspace-staging-metrics-token",
        "-o",
    ]
    assert command[7] == "go-template"
    assert 'index .data "token"' in command[-1]
    assert "json" not in command
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        "Application metrics Secret contract exists " "(value was not returned to the verifier).\n"
    )


def test_staging_verify_and_verify_all_discover_tokenplace_and_dspace(monkeypatch):
    doc, called = inventory(), []
    monkeypatch.setattr(metrics, "load_config", lambda: doc)
    monkeypatch.setattr(metrics, "verify", lambda app, env: called.append((app, env)))
    monkeypatch.setattr(metrics, "assert_context", lambda: None)
    assert metrics.main(["verify", "--app", "dspace", "--env", "staging"]) == 0
    assert called == [("dspace", "staging")]
    called.clear()
    assert metrics.main(["verify-all", "--env", "staging"]) == 0
    assert called == [("tokenplace", "staging"), ("dspace", "staging")]
