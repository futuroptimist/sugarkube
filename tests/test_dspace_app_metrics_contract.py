"""Regression coverage for the repository-owned DSPACE metrics contracts.

The bounded enums below are transcribed from DSPACE revision
22f506e07e0b5abfd0cf756e9c5827c0458fb4b2, metrics implementation blob
a2a1fecf94cab58b3e05e785694a2ed745fb2831. Keeping the evidence coordinates
beside the exact assertions makes future source audits reproducible.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import observability_app_metrics as metrics
from scripts.app_chart import merged_values_document

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "platform/observability/app-metrics.json"
STAGING_VALUES = ROOT / "docs/examples/dspace.values.staging.yaml"

REQUIRED_FAMILIES = [
    "dspace_http_requests_total",
    "dspace_http_request_duration_seconds_bucket",
    "dspace_dchat_requests_total",
    "dspace_dependency_requests_total",
    "dspace_instrumentation_up",
    "dspace_build_info",
]
SOURCE_LABELS = {
    "method": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "UNKNOWN"],
    "route": [
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
    ],
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


def _document() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _dspace(environment: str) -> dict:
    return _document()["applications"]["dspace"]["environments"][environment]


def test_dspace_staging_and_production_inventory_is_valid_and_source_bounded() -> None:
    document = _document()
    metrics.validate_inventory(document)
    environments = document["applications"]["dspace"]["environments"]

    assert list(environments) == ["staging", "prod"]
    for environment in ("staging", "prod"):
        allowed = environments[environment]["allowedApplicationLabels"]
        assert {key: allowed[key] for key in SOURCE_LABELS} == SOURCE_LABELS
        assert environments[environment]["requiredMetricFamilies"] == REQUIRED_FAMILIES
        assert environments[environment]["forbiddenApplicationLabels"]


def test_dspace_staging_inventory_exactly_matches_repository_values() -> None:
    cfg = _dspace("staging")
    values = merged_values_document((str(STAGING_VALUES),))

    assert cfg["namespace"] == cfg["serviceMonitorName"] == "dspace"
    assert cfg["secret"] == {
        "name": values["metrics"]["auth"]["existingSecret"],
        "key": values["metrics"]["auth"]["secretKey"],
    }
    assert cfg["serviceMonitor"]["authorization"] == {
        "type": "Bearer",
        "credentials": cfg["secret"],
    }
    assert cfg["serviceMonitor"]["path"] == "/metrics"
    assert cfg["serviceMonitor"]["interval"] == values["serviceMonitor"]["interval"]
    assert cfg["serviceMonitor"]["scrapeTimeout"] == values["serviceMonitor"]["scrapeTimeout"]
    assert cfg["targetLabels"]["cluster"] == values["serviceMonitor"]["cluster"]


def test_dspace_staging_coordinates_are_exact_and_isolated_from_production() -> None:
    staging = _dspace("staging")
    prod = _dspace("prod")

    assert staging["expectedTargetCount"] == 2
    assert staging["retries"] == {"attempts": 6, "delaySeconds": 10}
    assert [rule["targetLabel"] for rule in staging["serviceMonitor"]["relabelings"]] == [
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
    for path in (
        ("secret", "name"),
        ("targetLabels", "cluster"),
        ("targetLabels", "environment"),
        ("publicMetrics", "url"),
    ):
        assert staging[path[0]][path[1]] != prod[path[0]][path[1]]


def test_dspace_staging_secret_check_never_requests_or_prints_secret_data(
    monkeypatch, capsys
) -> None:
    cfg = _dspace("staging")
    calls: list[list[str]] = []

    def fake_run(argv: list[str]) -> str:
        calls.append(argv)
        return "dspace\tdspace-staging-metrics-token\tnonempty"

    monkeypatch.setattr(metrics, "run", fake_run)
    metrics.check_secret(cfg)

    command = calls.pop()
    assert command[:5] == ["kubectl", "-n", "dspace", "get", "secret"]
    assert command[5] == "dspace-staging-metrics-token"
    assert command[6:8] == ["-o", "go-template"]
    assert '{{if index .data "token"}}' in command[-1]
    assert "base64decode" not in command[-1]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "Application metrics Secret contract exists (value was not returned to the verifier).\n"
    )


def test_staging_verify_and_verify_all_discover_dspace_and_tokenplace(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(metrics, "verify", lambda app, env: calls.append((app, env)))

    assert metrics.main(["verify-all", "--env", "staging"]) == 0
    assert calls == [("tokenplace", "staging"), ("dspace", "staging")]
    assert metrics.appcfg("dspace", "staging") == _dspace("staging")


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("route", "*"),
        ("route", "/chat"),
        ("route", "/build-info.json"),
        ("route", "/inventory/item/arbitrary"),
        ("provider", "token-place"),
        ("dependency", "token-place"),
        ("outcome", "error"),
        ("environment", "prod"),
        ("cluster", "sugarkube-prod"),
    ],
)
def test_dspace_staging_rejects_wildcard_obsolete_unbounded_and_cross_environment_labels(
    label: str, value: str
) -> None:
    with pytest.raises(metrics.Error, match="label enum mismatch"):
        metrics.validate_metric_labels(_dspace("staging"), {label: value})


def test_dspace_production_rejects_staging_label_cross_contamination() -> None:
    cfg = copy.deepcopy(_dspace("prod"))
    for label, value in (("environment", "staging"), ("cluster", "sugarkube-int")):
        with pytest.raises(metrics.Error, match="label enum mismatch"):
            metrics.validate_metric_labels(cfg, {label: value})
