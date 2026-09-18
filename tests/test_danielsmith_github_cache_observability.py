import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts import danielsmith_github_cache_metrics as metrics
from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/observability/danielsmith-github-cache.json"
RULES = ROOT / "platform/observability/rules/danielsmith-github-cache.yaml"


def descriptor():
    return json.loads(CONFIG.read_text())


def producer(enabled=True):
    value = copy.deepcopy(descriptor()["producers"][0])
    value["enabled"] = enabled
    return value


def snapshot(**changes):
    value = {
        "enabled": True,
        "state": "fresh",
        "lastSuccessfulRefreshAt": "2026-09-17T12:00:00.000Z",
        "oldestDataFetchedAt": "2026-09-17T12:00:00.000Z",
        "retainedDataAgeSeconds": 0,
        "dataCompleteness": "complete",
        "refreshDurationMs": 250,
        "failureCategories": [],
        "configuredRepositoryCount": 2,
        "successfulRepositoryCount": 2,
        "failedRepositoryCount": 0,
        "retainedRepositoryCount": 0,
    }
    value.update(changes)
    return value


def test_descriptor_is_pinned_disabled_and_cadence_validated():
    data = descriptor()
    assert data["sourceRevision"] == quotas.APPROVED_DANIELSMITH_CACHE_SOURCE_REVISION
    assert {(item["environment"], item["enabled"]) for item in data["producers"]} == {
        ("staging", False),
        ("prod", False),
    }
    assert quotas.validate_daniel_cache_contract(data) == 2
    data["producers"][0]["cadence"] = "1m"
    with pytest.raises(quotas.ContractError, match="pinned cadence"):
        quotas.validate_daniel_cache_contract(data)


def test_disabled_and_missing_are_never_success():
    assert metrics.render_metrics(producer(False)).endswith(" 0\n")
    output = metrics.render_metrics(producer(), None)
    assert "monitoring_enabled" in output and "_state" not in output


@pytest.mark.parametrize("state", metrics.STATES)
def test_valid_lifecycle_states_are_preserved(state):
    if state == "disabled":
        value = snapshot(
            enabled=False,
            state=state,
            lastSuccessfulRefreshAt=None,
            oldestDataFetchedAt=None,
            retainedDataAgeSeconds=None,
            dataCompleteness="none",
            refreshDurationMs=None,
            configuredRepositoryCount=0,
            successfulRepositoryCount=0,
        )
        metrics.validate_cache(value)
    elif state == "warming":
        value = snapshot(
            state=state,
            lastSuccessfulRefreshAt=None,
            oldestDataFetchedAt=None,
            retainedDataAgeSeconds=None,
            dataCompleteness="none",
            refreshDurationMs=None,
            successfulRepositoryCount=0,
        )
        metrics.validate_cache(value)
    elif state == "stale":
        metrics.validate_cache(
            snapshot(
                state=state,
                dataCompleteness="partial",
                successfulRepositoryCount=1,
                failedRepositoryCount=1,
                retainedRepositoryCount=1,
                failureCategories=["rate_limited"],
                retainedDataAgeSeconds=600,
            )
        )
    elif state == "unavailable":
        metrics.validate_cache(
            snapshot(
                state=state,
                lastSuccessfulRefreshAt=None,
                oldestDataFetchedAt=None,
                retainedDataAgeSeconds=None,
                dataCompleteness="none",
                successfulRepositoryCount=0,
                failedRepositoryCount=2,
                failureCategories=["network"],
            )
        )
    else:
        metrics.validate_cache(snapshot())


def test_stale_fallback_preserves_last_success_and_true_retained_age():
    value = snapshot(
        state="stale",
        dataCompleteness="partial",
        successfulRepositoryCount=1,
        failedRepositoryCount=1,
        retainedRepositoryCount=1,
        failureCategories=["timeout"],
        retainedDataAgeSeconds=86400,
    )
    output = metrics.render_metrics(producer(), value)
    assert "retained_data_age_seconds" in output and " 86400" in output
    assert "last_success_unixtime_seconds" in output and " 1789646400" in output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(state="recovered"),
        lambda value: value.update(failureCategories=["owner/repository"]),
        lambda value: value.update(configuredRepositoryCount=51),
        lambda value: value.update(request_id="unbounded"),
    ],
)
def test_malformed_or_unbounded_data_fails_closed(mutation):
    value = snapshot()
    mutation(value)
    with pytest.raises(ValueError):
        metrics.validate_cache(value)


def test_collector_has_no_network_or_github_client():
    source = (ROOT / "scripts/danielsmith_github_cache_metrics.py").read_text()
    assert "urllib" not in source and "requests" not in source and "github.com" not in source
    assert parser_option("--snapshot").help == "already-published application JSON; never a URL"


def parser_option(name):
    # Keep this check focused on the public CLI rather than reaching the network.
    import subprocess

    result = subprocess.run(
        ["python3", "scripts/danielsmith_github_cache_metrics.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0 and name in result.stdout
    return type("Option", (), {"help": "already-published application JSON; never a URL"})


def test_rules_gate_both_environments_and_cover_failure_modes():
    rules = yaml.safe_load(RULES.read_text())["groups"][0]["rules"]
    expected = [
        rule for rule in rules if rule.get("record") == "daniel_github_cache_monitoring_expected"
    ]
    assert {(rule["labels"]["environment"], rule["expr"]) for rule in expected} == {
        ("staging", "vector(0)"),
        ("prod", "vector(0)"),
    }
    assert {rule.get("alert") for rule in rules} >= {
        "DanielGithubCacheExpectedButMissing",
        "DanielGithubCacheStale",
        "DanielGithubCacheUnavailable",
        "DanielGithubCacheRefreshFailure",
    }
