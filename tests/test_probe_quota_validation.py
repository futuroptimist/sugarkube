import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import validate_probe_quotas as quota

ROOT = Path(__file__).resolve().parents[1]


def contract(**changes):
    value = {
        "application": "custom",
        "environment": "prod",
        "probe": "blackbox-custom-prod-root",
        "route": "root",
        "path": "/",
        "method": "GET",
        "interval": "60s",
        "enabled": True,
        "bucket": "public",
        "limits": {"hourly": 100, "daily": 1000},
        "exemptions": [],
        "fanout": 1,
        "requestMultiplier": 1,
        "safetyMargin": 0.2,
        "unlimited": False,
    }
    value.update(changes)
    return value


def manifest(value):
    return {
        key: value[key]
        for key in ("application", "environment", "route", "path", "method", "interval", "fanout")
    }


def run_contracts(monkeypatch, tmp_path, records, active=None):
    application = records[0]["application"] if records else "custom"
    (tmp_path / "custom.json").write_text(
        json.dumps({"schemaVersion": 1, "application": application, "probes": records})
    )
    if active is None:
        active = {item["probe"]: manifest(item) for item in records if item.get("enabled")}
    monkeypatch.setattr(quota, "discover_probes", lambda environment, root=ROOT: active)
    return quota.validate("prod", tmp_path)


def test_sixty_second_probe_exhausts_daily_quota(monkeypatch, tmp_path):
    with pytest.raises(quota.ValidationError, match=r"daily volume 1440.*usable budget 800"):
        run_contracts(monkeypatch, tmp_path, [contract()])


def test_exact_method_exemptions(monkeypatch, tmp_path):
    for method in ("GET", "HEAD"):
        item = contract(method=method, exemptions=[{"path": "/", "methods": [method]}])
        run_contracts(monkeypatch, tmp_path, [item])
    for method in ("POST", "HEAD"):
        item = contract(method=method, exemptions=[{"path": "/", "methods": ["GET"]}])
        with pytest.raises(quota.ValidationError, match="volume"):
            run_contracts(monkeypatch, tmp_path, [item])


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/v1", "/ap"])
def test_exact_exemptions_do_not_match_related_paths(monkeypatch, tmp_path, path):
    item = contract(path=path, exemptions=[{"path": "/api", "methods": ["GET"]}])
    if path == "/api":
        run_contracts(monkeypatch, tmp_path, [item])
    else:
        with pytest.raises(quota.ValidationError, match="volume"):
            run_contracts(monkeypatch, tmp_path, [item])


def test_shared_bucket_aggregation_and_fanout(monkeypatch, tmp_path):
    first = contract(interval="120s", limits={"hourly": 200, "daily": 5000}, fanout=2)
    second = contract(
        probe="blackbox-custom-prod-meta",
        route="metadata",
        path="/meta",
        interval="120s",
        limits={"hourly": 200, "daily": 5000},
        fanout=2,
        requestMultiplier=2,
    )
    with pytest.raises(quota.ValidationError, match=r"hourly volume 180.*usable budget 160"):
        run_contracts(monkeypatch, tmp_path, [first, second])


@pytest.mark.parametrize(
    ("limits", "match"),
    [
        ({"hourly": 70, "daily": 2000}, "hourly volume"),
        ({"hourly": 100, "daily": 1500}, "daily volume"),
    ],
)
def test_each_window_fails_independently(monkeypatch, tmp_path, limits, match):
    with pytest.raises(quota.ValidationError, match=match):
        run_contracts(monkeypatch, tmp_path, [contract(limits=limits)])


def test_usable_budget_boundary_fails_and_below_threshold_passes(monkeypatch, tmp_path):
    boundary = contract(interval="90s", limits={"hourly": 50, "daily": 2000})
    with pytest.raises(quota.ValidationError, match=r"hourly volume 40.*usable budget 40"):
        run_contracts(monkeypatch, tmp_path, [boundary])
    below = contract(interval="120s", limits={"hourly": 50, "daily": 2000})
    run_contracts(monkeypatch, tmp_path, [below])


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"interval": "minute"}, "duration"),
        ({"interval": "0s"}, "duration"),
        ({"interval": "-1s"}, "duration"),
        ({"method": "TRACE"}, "unknown method"),
        ({"limits": {"hourly": 0, "daily": 1}}, "positive integer"),
        ({"safetyMargin": -0.1}, "safetyMargin"),
        ({"safetyMargin": 1}, "safetyMargin"),
        ({"fanout": 0}, "positive integer"),
        ({"requestMultiplier": -1}, "positive integer"),
        ({"limits": {"daily": 1000}}, "exact hourly and daily"),
    ],
)
def test_malformed_or_missing_quota_metadata_fails_closed(monkeypatch, tmp_path, changes, match):
    with pytest.raises(quota.ValidationError, match=match):
        run_contracts(monkeypatch, tmp_path, [contract(**changes)])


def test_missing_and_ambiguous_metadata_fails_closed(monkeypatch, tmp_path):
    missing = contract()
    missing.pop("bucket")
    with pytest.raises(quota.ValidationError, match="missing required fields: bucket"):
        run_contracts(monkeypatch, tmp_path, [missing])
    first = contract(interval="10m", limits={"hourly": 100, "daily": 1000})
    second = contract(
        probe="blackbox-custom-prod-meta",
        route="metadata",
        path="/meta",
        interval="10m",
        limits={"hourly": 101, "daily": 1000},
    )
    with pytest.raises(quota.ValidationError, match="contradictory limits or margins"):
        run_contracts(monkeypatch, tmp_path, [first, second])


def test_duplicates_undeclared_and_orphaned_contracts_fail(monkeypatch, tmp_path):
    item = contract(exemptions=[{"path": "/", "methods": ["GET"]}])
    with pytest.raises(quota.ValidationError, match="duplicate probe identity"):
        run_contracts(monkeypatch, tmp_path, [item, copy.deepcopy(item)])
    with pytest.raises(quota.ValidationError, match="lacks a quota declaration"):
        run_contracts(monkeypatch, tmp_path, [], {item["probe"]: manifest(item)})
    with pytest.raises(quota.ValidationError, match="has no active Probe"):
        run_contracts(monkeypatch, tmp_path, [item], {})


def test_disabled_and_explicit_unlimited_probes(monkeypatch, tmp_path):
    disabled = contract(enabled=False)
    run_contracts(monkeypatch, tmp_path, [disabled], {})
    unlimited = contract(unlimited=True, limits={"hourly": None, "daily": None})
    run_contracts(monkeypatch, tmp_path, [unlimited])


def test_both_repository_rendered_graphs_validate():
    config = ROOT / "platform/observability/probe-quotas"
    assert quota.validate("staging", config) == [
        "validated 21 active staging Probes (2 exact exemptions)"
    ]
    assert quota.validate("prod", config) == [
        "validated 11 active prod Probes (2 exact exemptions)"
    ]


def test_tokenplace_production_requires_each_corrected_exemption(monkeypatch, tmp_path):
    source = json.loads((ROOT / "platform/observability/probe-quotas/tokenplace.json").read_text())
    prod = [record for record in source["probes"] if record["environment"] == "prod"]
    active = {record["probe"]: manifest(record) for record in prod}
    run_contracts(monkeypatch, tmp_path, prod, active)
    for route in ("root", "metadata"):
        changed = copy.deepcopy(prod)
        next(record for record in changed if record["route"] == route)["exemptions"] = []
        with pytest.raises(quota.ValidationError, match="volume"):
            run_contracts(monkeypatch, tmp_path, changed, active)


def test_custom_config_and_errors_do_not_disclose_target_data(monkeypatch, tmp_path, capsys):
    sentinel = "https://private.invalid/secret?authorization=sentinel"
    item = contract(interval=sentinel)
    with pytest.raises(quota.ValidationError) as caught:
        run_contracts(monkeypatch, tmp_path, [item])
    assert sentinel not in str(caught.value)


def test_cli_validates_both_environments():
    result = subprocess.run(
        [sys.executable, "scripts/validate_probe_quotas.py", "--env", "staging", "--env", "prod"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "21 active staging" in result.stdout
    assert "11 active prod" in result.stdout
