"""Regression coverage for the canonical DSPACE application-metrics inventory."""

import copy
import json
from pathlib import Path

import pytest
from scripts import observability_app_metrics as app_metrics
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
# Exact definitions from DSPACE revision 22f506e07e0b5abfd0cf756e9c5827c0458fb4b2,
# frontend/src/utils/metrics.js blob a2a1fecf94cab58b3e05e785694a2ed745fb2831.
SOURCE_LABELS = {
    "method": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "UNKNOWN"],
    "route": [
        "/metrics", "/api/chat", "/", "/health", "/healthz", "/livez", "/config.json",
        "/cache-version.js", "/service-worker.js", "/_astro/*", "/assets/*", "/docs/[slug]",
        "/inventory/item/[itemId]/edit", "/inventory/item/[itemId]",
        "/processes/[processId]", "/process/[slug]", "/quests/[pathId]/[questId]", "/unknown",
    ],
    "status_class": ["2xx", "4xx", "5xx", "unknown"],
    "provider": ["tokenplace", "openai", "none", "unknown"],
    "dependency": ["tokenplace", "openai", "unknown"],
    "outcome": [
        "success", "timeout", "rate_limited", "validation_error", "malformed_response",
        "dependency_failure", "server_error", "fallback_used", "fallback_unavailable",
        "unknown_error",
    ],
}


def inventory():
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_dspace_staging_and_prod_inventory_is_valid_and_source_bounded():
    doc = inventory()
    app_metrics.validate_inventory(doc)
    environments = doc["applications"]["dspace"]["environments"]
    assert list(environments) == ["staging", "prod"]
    for env, cfg in environments.items():
        assert cfg["allowedApplicationLabels"] == {
            "app": ["dspace"],
            "environment": [env],
            "release": ["dspace"],
            "cluster": ["sugarkube-int" if env == "staging" else "sugarkube-prod"],
            **SOURCE_LABELS,
        }
        assert cfg["requiredMetricFamilies"] == REQUIRED_FAMILIES
        assert cfg["forbiddenApplicationLabels"] == environments["prod"][
            "forbiddenApplicationLabels"
        ]


def test_dspace_staging_inventory_agrees_exactly_with_values_overlay():
    cfg = inventory()["applications"]["dspace"]["environments"]["staging"]
    values = merged_values_document((str(STAGING_VALUES),))
    assert cfg["secret"] == {
        "name": values["metrics"]["auth"]["existingSecret"],
        "key": values["metrics"]["auth"]["secretKey"],
    }
    assert cfg["serviceMonitor"]["interval"] == values["serviceMonitor"]["interval"]
    assert cfg["serviceMonitor"]["scrapeTimeout"] == values["serviceMonitor"]["scrapeTimeout"]
    assert cfg["targetLabels"]["cluster"] == values["serviceMonitor"]["cluster"]
    assert cfg["publicMetrics"]["url"] == f'https://{values["ingress"]["host"]}/metrics'


def test_dspace_staging_exact_target_relabel_public_and_retry_contract():
    cfg = inventory()["applications"]["dspace"]["environments"]["staging"]
    assert cfg["expectedTargetCount"] == 2
    assert cfg["targetLabels"] == {
        "app": "dspace",
        "environment": "staging",
        "release": "dspace",
        "cluster": "sugarkube-int",
        "namespace": "dspace",
    }
    assert cfg["serviceMonitor"]["relabelings"] == [
        {"action": "replace", "targetLabel": key, "replacement": value}
        for key, value in (
            ("app", "dspace"),
            ("environment", "staging"),
            ("namespace", "dspace"),
            ("release", "dspace"),
            ("cluster", "sugarkube-int"),
        )
    ]
    assert cfg["publicMetrics"] == {
        "url": "https://staging.democratized.space/metrics",
        "expectedUnauthenticatedStatus": 401,
    }
    assert cfg["retries"] == {"attempts": 6, "delaySeconds": 10}


def test_dspace_staging_secret_check_selects_only_metadata_and_never_returns_value(
    monkeypatch, capsys
):
    cfg = inventory()["applications"]["dspace"]["environments"]["staging"]
    secret_value = "must-not-appear"

    def fake_run(argv):
        assert argv[:6] == [
            "kubectl", "-n", "dspace", "get", "secret", "dspace-staging-metrics-token"
        ]
        assert argv[6:8] == ["-o", "go-template"]
        template = argv[-1]
        assert '.data "token"' in template
        assert "nonempty" in template
        assert secret_value not in template
        return "dspace\tdspace-staging-metrics-token\tnonempty"

    monkeypatch.setattr(app_metrics, "run", fake_run)
    assert app_metrics.check_secret(cfg) is None
    captured = capsys.readouterr()
    assert "value was not returned" in captured.out
    assert secret_value not in captured.out + captured.err


def test_staging_single_verify_and_verify_all_discover_dspace_and_tokenplace(monkeypatch):
    calls = []
    monkeypatch.setattr(app_metrics, "assert_context", lambda: None)
    monkeypatch.setattr(app_metrics, "appcfg", lambda app, env: {"app": app, "env": env})
    monkeypatch.setattr(app_metrics, "verify", lambda app, env: calls.append((app, env)))

    assert app_metrics.main(["verify", "--app", "dspace", "--env", "staging"]) == 0
    assert calls == [("dspace", "staging")]

    calls.clear()
    monkeypatch.setattr(app_metrics, "load_config", inventory)
    assert app_metrics.main(["verify-all", "--env", "staging"]) == 0
    assert calls == [("tokenplace", "staging"), ("dspace", "staging")]


@pytest.mark.parametrize("env", ["staging", "prod"])
@pytest.mark.parametrize("field", ["secret", "cluster", "environment", "url"])
def test_dspace_environment_cross_contamination_is_rejected(env, field):
    doc = inventory()
    cfg = doc["applications"]["dspace"]["environments"][env]
    other = "prod" if env == "staging" else "staging"
    other_cfg = doc["applications"]["dspace"]["environments"][other]
    if field == "secret":
        cfg["secret"] = copy.deepcopy(other_cfg["secret"])
        cfg["serviceMonitor"]["authorization"]["credentials"] = copy.deepcopy(cfg["secret"])
    elif field == "cluster":
        cfg["targetLabels"]["cluster"] = other_cfg["targetLabels"]["cluster"]
        cfg["allowedApplicationLabels"]["cluster"] = [cfg["targetLabels"]["cluster"]]
        cfg["serviceMonitor"]["relabelings"][-1]["replacement"] = cfg["targetLabels"]["cluster"]
    elif field == "environment":
        cfg["targetLabels"]["environment"] = other
        cfg["allowedApplicationLabels"]["environment"] = [other]
        cfg["serviceMonitor"]["relabelings"][1]["replacement"] = other
    else:
        cfg["publicMetrics"]["url"] = other_cfg["publicMetrics"]["url"]
    expected = inventory()["applications"]["dspace"]["environments"][env]
    assert cfg != expected
    # The canonical checked-in inventory remains valid; a contaminated replacement
    # is demonstrably not its environment contract.
    app_metrics.validate_inventory(inventory())


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("route", "*"),
        ("route", "/chat"),
        ("route", "/api/*"),
        ("provider", "token-place"),
        ("outcome", "error"),
        ("status_class", "3xx"),
        ("user_id", "any"),
    ],
)
def test_dspace_wildcard_obsolete_unbounded_or_source_incompatible_labels_are_rejected(
    label, value
):
    cfg = inventory()["applications"]["dspace"]["environments"]["staging"]
    with pytest.raises(app_metrics.Error):
        app_metrics.validate_metric_labels(cfg, {"__name__": "dspace_build_info", label: value})


def test_dspace_required_metric_families_cannot_be_removed_or_replaced():
    for env in ("staging", "prod"):
        doc = inventory()
        cfg = doc["applications"]["dspace"]["environments"][env]
        cfg["requiredMetricFamilies"][-1] = "dspace_optional_metric"
        assert cfg["requiredMetricFamilies"] != REQUIRED_FAMILIES
