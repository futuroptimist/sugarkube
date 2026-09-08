import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "probe_quotas", ROOT / "scripts/validate_probe_quotas.py"
)
quota = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quota)


def probe(name="probe", path="/", method="GET", interval="60s", app="custom", route_class="root"):
    return {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "Probe",
        "metadata": {
            "name": name,
            "labels": {"app": app, "environment": "staging", "route": route_class},
        },
        "spec": {
            "interval": interval,
            "module": method.lower(),
            "targets": {"staticConfig": {"static": [f"https://private.invalid{path}"]}},
        },
    }


def contract(probes, *, daily=1000, hourly=1000, margin="0", exemptions=None, unlimited=None):
    declarations = []
    for doc in probes:
        labels, spec = doc["metadata"]["labels"], doc["spec"]
        path = quota.urlsplit(spec["targets"]["staticConfig"]["static"][0]).path or "/"
        declarations.append(
            {
                "application": labels["app"],
                "environment": "staging",
                "probe": doc["metadata"]["name"],
                "route_class": labels["route"],
                "route": path,
                "method": spec["module"].upper(),
                "interval": spec["interval"],
                "enabled": True,
                "quota_bucket": "shared",
                "scrape_fanout": 1,
                "request_multiplier": 1,
            }
        )
    return {
        "schema_version": 1,
        "environment": "staging",
        "quota_policies": [
            {
                "application": "custom",
                "bucket": "shared",
                "limits": {"hourly": hourly, "daily": daily},
                "safety_margin": margin,
                "exemptions": exemptions or [],
                "unlimited_endpoints": unlimited or [],
            }
        ],
        "probes": declarations,
    }


METHODS = {method.lower(): method for method in quota.METHODS}


def check(probes, policy):
    return quota.validate("staging", probes, policy, METHODS)


def test_sixty_second_daily_quota_fails_but_exact_get_exemption_passes():
    docs = [probe()]
    with pytest.raises(quota.ValidationError, match="daily.*calculated_volume=1440"):
        check(docs, contract(docs))
    assert check(docs, contract(docs, exemptions=[{"route": "/", "method": "GET"}])) == 1


@pytest.mark.parametrize("method", ["POST", "HEAD"])
def test_exemption_is_method_exact(method):
    docs = [probe(method=method)]
    with pytest.raises(quota.ValidationError):
        check(docs, contract(docs, exemptions=[{"route": "/", "method": "GET"}]))
    if method == "HEAD":
        assert check(docs, contract(docs, exemptions=[{"route": "/", "method": "HEAD"}])) == 1


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/v1", "/xapi"])
def test_exemption_is_path_exact(path):
    docs = [probe(path=path)]
    with pytest.raises(quota.ValidationError):
        check(
            docs,
            (
                contract(docs, exemptions=[{"route": "/api", "method": "GET"}])
                if path != "/api"
                else contract(docs, exemptions=[{"route": "/", "method": "GET"}])
            ),
        )


def test_shared_bucket_aggregates_and_fanout_multiplies():
    docs = [probe("a", "/a"), probe("b", "/b")]
    policy = contract(docs, hourly=120, daily=100000)
    with pytest.raises(quota.ValidationError, match="hourly.*calculated_volume=120"):
        check(docs, policy)
    policy = contract([docs[0]], hourly=120, daily=100000)
    policy["probes"][0]["scrape_fanout"] = 2
    with pytest.raises(quota.ValidationError, match="calculated_volume=120"):
        check([docs[0]], policy)
    policy["probes"][0]["scrape_fanout"] = 1
    policy["probes"][0]["request_multiplier"] = 2
    with pytest.raises(quota.ValidationError, match="calculated_volume=120"):
        check([docs[0]], policy)


def test_hourly_and_daily_limits_are_independent():
    docs = [probe(interval="60s")]
    with pytest.raises(quota.ValidationError, match="hourly"):
        check(docs, contract(docs, hourly=60, daily=2000))
    with pytest.raises(quota.ValidationError, match="daily"):
        check(docs, contract(docs, hourly=100, daily=1440))


def test_boundary_fails_and_below_margin_threshold_passes():
    docs = [probe(interval="60s")]
    with pytest.raises(quota.ValidationError, match="usable_budget=60"):
        check(docs, contract(docs, hourly=100, daily=100000, margin="0.40"))
    assert check(docs, contract(docs, hourly=102, daily=100000, margin="0.40")) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.pop("environment"),
        lambda c: c["probes"][0].pop("quota_bucket"),
        lambda c: c["probes"][0].pop("interval"),
        lambda c: c["probes"][0].pop("method"),
        lambda c: c["quota_policies"][0].pop("safety_margin"),
    ],
)
def test_missing_metadata_fails_closed(mutation):
    docs = [probe()]
    policy = contract(docs)
    mutation(policy)
    with pytest.raises((quota.ValidationError, KeyError)):
        check(docs, policy)


@pytest.mark.parametrize(
    "field,value",
    [
        ("interval", "0s"),
        ("interval", "minute"),
        ("method", "TRACE"),
        ("scrape_fanout", 0),
        ("request_multiplier", -1),
    ],
)
def test_malformed_probe_values_fail(field, value):
    docs = [probe()]
    policy = contract(docs)
    policy["probes"][0][field] = value
    with pytest.raises(quota.ValidationError):
        check(docs, policy)


@pytest.mark.parametrize("field,value", [("hourly", 0), ("daily", -1)])
def test_invalid_limits_fail(field, value):
    docs = [probe()]
    policy = contract(docs)
    policy["quota_policies"][0]["limits"][field] = value
    with pytest.raises(quota.ValidationError):
        check(docs, policy)


@pytest.mark.parametrize("margin", ["-0.1", "1", "bogus"])
def test_invalid_margins_fail(margin):
    docs = [probe()]
    with pytest.raises(quota.ValidationError):
        check(docs, contract(docs, margin=margin))


def test_duplicates_orphans_and_undeclared_active_probes_fail():
    docs = [probe()]
    policy = contract(docs)
    policy["probes"].append(copy.deepcopy(policy["probes"][0]))
    with pytest.raises(quota.ValidationError, match="duplicate probe contract"):
        check(docs, policy)
    policy = contract(docs)
    policy["probes"][0]["probe"] = "orphan"
    with pytest.raises(quota.ValidationError, match="orphaned"):
        check(docs, policy)
    with pytest.raises(quota.ValidationError, match="lacks a quota contract"):
        check(docs + [probe("extra", "/extra")], contract(docs))


def test_disabled_probe_is_zero_and_unlimited_endpoint_passes():
    docs = [probe()]
    policy = contract(docs, hourly=1, daily=1)
    policy["probes"][0]["enabled"] = False
    assert check(docs, policy) == 1
    assert (
        check(docs, contract(docs, hourly=1, daily=1, unlimited=[{"route": "/", "method": "GET"}]))
        == 1
    )


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_repository_active_graph_and_contract_validate(environment):
    assert (
        quota.validate(
            environment,
            quota.render_active_probes(environment),
            quota.load_contract(environment),
            quota.module_methods(environment),
        )
        > 0
    )


def test_tokenplace_root_and_metadata_require_corrected_exemptions():
    environment = "prod"
    docs = quota.render_active_probes(environment)
    policy = quota.load_contract(environment)
    assert quota.validate(environment, docs, policy, quota.module_methods(environment)) == 11
    for route in ("/", "/api/v1/meta"):
        changed = copy.deepcopy(policy)
        changed_policy = next(
            p for p in changed["quota_policies"] if p["application"] == "tokenplace"
        )
        changed_policy["exemptions"] = [
            e for e in changed_policy["exemptions"] if e["route"] != route
        ]
        with pytest.raises(quota.ValidationError, match="daily"):
            quota.validate(environment, docs, changed, quota.module_methods(environment))


def test_custom_config_directory_and_sanitized_cli_error(tmp_path):
    docs = [probe()]
    policy = contract(docs, exemptions=[{"route": "/", "method": "GET"}])
    config_dir = tmp_path / "contracts"
    config_dir.mkdir()
    (config_dir / "staging.json").write_text(json.dumps(policy))
    assert quota.load_contract("staging", config_dir) == policy
    rendered = tmp_path / "rendered.json"
    rendered.write_text(json.dumps({"items": docs}))
    policy["probes"][0]["interval"] = "bad"
    (config_dir / "staging.json").write_text(json.dumps(policy))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate_probe_quotas.py"),
            "--env",
            "staging",
            "--config-dir",
            str(config_dir),
            "--rendered-probes",
            str(rendered),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert "private.invalid" not in result.stderr
    assert "sec" + "ret-sentinel" not in result.stderr
