"""Tests for declarative, rendered-manifest probe quota validation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import validate_probe_quotas as quotas


def raw_contract(**overrides: object) -> dict:
    value = {
        "application": "example",
        "environment": "prod",
        "probe": "probe-a",
        "route_class": "root",
        "path": "/",
        "method": "GET",
        "interval": "60s",
        "enabled": True,
        "bucket": "public",
        "limits": {"hourly": 100, "daily": 1000},
        "exemptions": [],
        "fanout": 1,
        "request_multiplier": 1,
        "safety_margin": 0,
        "unlimited": False,
        "unlimited_reason": None,
    }
    value.update(overrides)
    return value


def contract(**overrides: object) -> dict:
    return quotas.validate_contract(raw_contract(**overrides), "example", "prod")


def probe_from(item: dict) -> dict:
    return {
        key: item[key]
        for key in ("application", "environment", "route_class", "path", "method", "interval")
    }


def run_contracts(*items: dict) -> None:
    quotas.validate("prod", {item["probe"]: probe_from(item) for item in items}, list(items))


def test_sixty_second_probe_exceeds_non_exempt_daily_quota() -> None:
    with pytest.raises(quotas.ValidationError, match=r"daily volume 1440 .* 1000"):
        run_contracts(contract())


def test_exact_get_exemption_passes_and_method_mismatch_fails() -> None:
    run_contracts(contract(exemptions=[{"path": "/", "method": "GET"}]))
    with pytest.raises(quotas.ValidationError, match="daily volume"):
        run_contracts(contract(method="POST", exemptions=[{"path": "/", "method": "GET"}]))


def test_head_requires_its_own_exact_exemption() -> None:
    with pytest.raises(quotas.ValidationError, match="daily volume"):
        run_contracts(contract(method="HEAD", exemptions=[{"path": "/", "method": "GET"}]))
    run_contracts(contract(method="HEAD", exemptions=[{"path": "/", "method": "HEAD"}]))


@pytest.mark.parametrize(
    "exempt_path", ["/api", "/api/v1/meta/", "/api/v1/metadata", "/x/api/v1/meta"]
)
def test_paths_do_not_inherit_an_exact_exemption(exempt_path: str) -> None:
    with pytest.raises(quotas.ValidationError, match="daily volume"):
        run_contracts(
            contract(path="/api/v1/meta", exemptions=[{"path": exempt_path, "method": "GET"}])
        )


def test_shared_bucket_aggregates_probes_and_fanout_multipliers() -> None:
    first = contract(interval="2h", limits={"hourly": 5, "daily": 100}, fanout=2)
    second = contract(
        probe="probe-b",
        route_class="meta",
        path="/meta",
        interval="2h",
        limits={"hourly": 5, "daily": 100},
        request_multiplier=3,
    )
    with pytest.raises(quotas.ValidationError, match=r"hourly volume 5 .* 5"):
        run_contracts(first, second)


def test_hourly_and_daily_limits_are_independent() -> None:
    with pytest.raises(quotas.ValidationError, match="hourly"):
        run_contracts(contract(interval="30m", limits={"hourly": 2, "daily": 1000}))
    with pytest.raises(quotas.ValidationError, match="daily"):
        run_contracts(contract(interval="1h", limits={"hourly": 100, "daily": 24}))


def test_usable_budget_boundary_fails_and_below_threshold_passes() -> None:
    with pytest.raises(quotas.ValidationError, match=r"hourly volume 1 .* 2"):
        run_contracts(
            contract(interval="2h", limits={"hourly": 2, "daily": 100}, safety_margin=0.5)
        )
    run_contracts(contract(interval="2h", limits={"hourly": 3, "daily": 100}, safety_margin=0.5))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"interval": "minute"}, "interval"),
        ({"interval": "0s"}, "interval"),
        ({"interval": "-1s"}, "interval"),
        ({"limits": {"hourly": 0, "daily": 1}}, "hourly limit"),
        ({"safety_margin": 1}, "safety_margin"),
        ({"safety_margin": -0.1}, "safety_margin"),
        ({"method": "TRACE"}, "method"),
        ({"bucket": ""}, "bucket"),
    ],
)
def test_malformed_contract_values_fail_closed(change: dict, message: str) -> None:
    with pytest.raises(quotas.ValidationError, match=message):
        contract(**change)


def test_missing_ambiguous_duplicate_and_orphan_metadata_fail_closed() -> None:
    incomplete = raw_contract()
    incomplete.pop("limits")
    with pytest.raises(quotas.ValidationError, match="missing"):
        quotas.validate_contract(incomplete, "example", "prod")
    item = contract()
    with pytest.raises(quotas.ValidationError, match="duplicate contract"):
        quotas.validate("prod", {item["probe"]: probe_from(item)}, [item, deepcopy(item)])
    with pytest.raises(quotas.ValidationError, match="undeclared active"):
        quotas.validate("prod", {item["probe"]: probe_from(item)}, [])
    with pytest.raises(quotas.ValidationError, match="orphaned"):
        quotas.validate("prod", {}, [item])


def test_contradictory_shared_bucket_metadata_fails_closed() -> None:
    first = contract(interval="2h")
    second = contract(
        probe="probe-b", route_class="meta", path="/meta", interval="2h", safety_margin=0.2
    )
    with pytest.raises(quotas.ValidationError, match="contradictory"):
        run_contracts(first, second)


def test_disabled_probe_contributes_zero_and_explicit_unlimited_passes() -> None:
    run_contracts(contract(enabled=False))
    run_contracts(
        contract(
            unlimited=True,
            limits=None,
            unlimited_reason="Dedicated health endpoint has no application quota.",
        )
    )


def active_environment(environment: str) -> tuple[dict[str, dict], list[dict]]:
    path = quotas.ROOT / f"clusters/{environment}/observability/probes/public-apps.yaml"
    documents = quotas.render_probes(environment, path)
    probes = quotas.active_probe_facts(documents, environment, quotas.module_methods(environment))
    contracts = quotas.load_contracts(
        {probe["application"] for probe in probes.values()}, environment
    )
    return probes, contracts


@pytest.mark.parametrize(("environment", "count"), [("staging", 21), ("prod", 11)])
def test_active_rendered_environment_contracts_validate(environment: str, count: int) -> None:
    probes, contracts = active_environment(environment)
    assert len(probes) == count
    quotas.validate(environment, probes, contracts)


@pytest.mark.parametrize("route", ["root", "metadata"])
def test_tokenplace_production_requires_each_corrected_get_exemption(route: str) -> None:
    probes, contracts = active_environment("prod")
    target = next(
        item
        for item in contracts
        if item["application"] == "tokenplace" and item["route_class"] == route
    )
    target["exemption_pairs"].remove((target["path"], "GET"))
    with pytest.raises(quotas.ValidationError, match=r"tokenplace prod .* daily volume 1440"):
        quotas.validate("prod", probes, contracts)


def test_custom_application_config_directory_needs_no_shared_code_change(tmp_path: Path) -> None:
    (tmp_path / "custom.env").write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=custom",
                "SUGARKUBE_RELEASE=custom",
                "SUGARKUBE_NAMESPACE=custom",
                "SUGARKUBE_CHART=oci://example.invalid/custom",
                "SUGARKUBE_VERSION=1.2.3",
                "SUGARKUBE_VALUES_DEV=dev.yaml",
                "SUGARKUBE_VALUES_STAGING=staging.yaml",
                "SUGARKUBE_VALUES_PROD=prod.yaml",
                f"SUGARKUBE_PROBE_QUOTA_CONFIG={tmp_path / 'custom.json'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    custom = raw_contract(
        application="custom",
        probe="custom-probe",
        unlimited=True,
        limits=None,
        unlimited_reason="Dedicated operational endpoint has no application quota.",
        exemptions=[],
        bucket="health-operational",
        route_class="healthz",
        path="/healthz",
    )
    (tmp_path / "custom.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "application": "custom",
                "environments": {"staging": [], "prod": [custom]},
            }
        ),
        encoding="utf-8",
    )
    contracts = quotas.load_contracts({"custom"}, "prod", tmp_path)
    quotas.validate("prod", {"custom-probe": probe_from(contracts[0])}, contracts)


def test_errors_do_not_echo_secret_or_private_target_sentinels() -> None:
    document = {
        "kind": "Probe",
        "metadata": {
            "name": "safe-name",
            "labels": {"app": "example", "environment": "prod", "route": "root"},
        },
        "spec": {
            "interval": "60s",
            "module": "https_2xx",
            "targets": {
                "staticConfig": {
                    "static": ["https://private-endpoint-sentinel.invalid/?secret-sentinel"]
                }
            },
        },
    }
    with pytest.raises(quotas.ValidationError) as error:
        quotas.active_probe_facts([document], "prod", {"https_2xx": "GET"})
    assert "secret-sentinel" not in str(error.value)
    assert "private-endpoint-sentinel" not in str(error.value)
