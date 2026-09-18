import copy, json, subprocess
from pathlib import Path
import pytest, yaml
from scripts import danielsmith_github_cache_metrics as metrics
from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/observability/danielsmith-github-cache.json"
RULES = ROOT / "platform/observability/rules/danielsmith-github-cache.yaml"


def inventory():
    return json.loads(CONFIG.read_text())


def producer(enabled=True):
    p = copy.deepcopy(inventory()["producers"][0])
    p["enabled"] = enabled
    p["requestMultiplicity"] = 1 if enabled else None
    return p


def snapshot(**updates):
    value = {
        "enabled": True,
        "state": "fresh",
        "lastSuccessfulRefreshAt": "2026-01-01T00:00:00.000Z",
        "oldestDataFetchedAt": "2026-01-01T00:00:00.000Z",
        "retainedDataAgeSeconds": 0,
        "dataCompleteness": "complete",
        "refreshDurationMs": 100,
        "failureCategories": [],
        "configuredRepositoryCount": 2,
        "successfulRepositoryCount": 2,
        "failedRepositoryCount": 0,
        "retainedRepositoryCount": 0,
    }
    value.update(updates)
    return value


def test_descriptor_is_pinned_disabled_and_quota_validated():
    data = inventory()
    assert data["sourceRevision"] == quotas.APPROVED_DANIELSMITH_GITHUB_CACHE_SOURCE_REVISION
    assert {(p["environment"], p["enabled"]) for p in data["producers"]} == {
        ("staging", False),
        ("prod", False),
    }
    assert quotas.validate_github_cache_contract(data) == 2


def test_disabled_and_missing_never_report_success():
    assert "daniel_github_cache_enabled" not in metrics.render_metrics(producer(False))
    assert "daniel_github_cache_enabled" not in metrics.render_metrics(producer(), None)
    with pytest.raises(ValueError, match="disabled producer"):
        metrics.render_metrics(producer(False), snapshot())


@pytest.mark.parametrize("state", metrics.STATES)
def test_valid_lifecycle_states(state):
    variants = {
        "disabled": (
            {
                "enabled": False,
                "state": "disabled",
                "lastSuccessfulRefreshAt": None,
                "oldestDataFetchedAt": None,
                "retainedDataAgeSeconds": None,
                "dataCompleteness": "none",
                "refreshDurationMs": None,
                "failureCategories": [],
                "configuredRepositoryCount": 0,
                "successfulRepositoryCount": 0,
                "failedRepositoryCount": 0,
                "retainedRepositoryCount": 0,
            },
            producer(),
        ),
        "warming": (
            snapshot(
                state="warming",
                lastSuccessfulRefreshAt=None,
                oldestDataFetchedAt=None,
                retainedDataAgeSeconds=None,
                dataCompleteness="none",
                refreshDurationMs=None,
                successfulRepositoryCount=0,
                failedRepositoryCount=0,
                retainedRepositoryCount=0,
            ),
            producer(),
        ),
        "fresh": (snapshot(), producer()),
        "stale": (
            snapshot(
                state="stale",
                dataCompleteness="partial",
                successfulRepositoryCount=1,
                failedRepositoryCount=1,
                retainedRepositoryCount=1,
                failureCategories=["rate_limited"],
                retainedDataAgeSeconds=900,
            ),
            producer(),
        ),
        "unavailable": (
            snapshot(
                state="unavailable",
                lastSuccessfulRefreshAt=None,
                oldestDataFetchedAt=None,
                retainedDataAgeSeconds=None,
                dataCompleteness="none",
                successfulRepositoryCount=0,
                failedRepositoryCount=2,
                retainedRepositoryCount=0,
                failureCategories=["network"],
            ),
            producer(),
        ),
    }
    value, p = variants[state]
    out = metrics.render_metrics(p, value)
    assert f'state="{state}"}} 1' in out


def test_stale_fallback_preserves_last_success_and_true_age():
    value = snapshot(
        state="stale",
        dataCompleteness="partial",
        successfulRepositoryCount=1,
        failedRepositoryCount=1,
        retainedRepositoryCount=1,
        failureCategories=["rate_limited"],
        retainedDataAgeSeconds=86400,
    )
    out = metrics.render_metrics(producer(), value)
    assert (
        "last_success_unixtime_seconds" in out
        and "retained_data_age_seconds" in out
        and " 86400" in out
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(url="https://github.com/private"),
        lambda v: v.update(state="other"),
        lambda v: v.update(configuredRepositoryCount=51),
        lambda v: v.update(failureCategories=["arbitrary error"]),
        lambda v: v.update(lastSuccessfulRefreshAt="2026-01-02T00:00:00Z"),
    ],
)
def test_malformed_or_unbounded_input_fails_closed(mutation):
    value = snapshot()
    mutation(value)
    with pytest.raises(ValueError):
        metrics.validate_snapshot(value)


def test_collection_is_offline_and_atomic(tmp_path, monkeypatch):
    descriptor = tmp_path / "descriptor.json"
    data = inventory()
    data["producers"][0].update(enabled=True, requestMultiplicity=1)
    descriptor.write_text(json.dumps(data))
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(snapshot()))
    output = tmp_path / "cache.prom"

    def forbidden(*args, **kwargs):
        raise AssertionError("upstream call attempted")

    monkeypatch.setattr(subprocess, "run", forbidden)
    assert (
        metrics.main(
            [
                "--descriptor",
                str(descriptor),
                "--environment",
                "staging",
                "--snapshot",
                str(snap),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert 'state="fresh"} 1' in output.read_text()


def test_rules_are_disabled_for_both_environments():
    rules = yaml.safe_load(RULES.read_text())["groups"][0]["rules"]
    expected = [r for r in rules if r.get("record") == "daniel_github_cache_monitoring_expected"]
    assert {(r["labels"]["environment"], r["expr"]) for r in expected} == {
        ("staging", "vector(0)"),
        ("prod", "vector(0)"),
    }
    text = RULES.read_text()
    assert (
        "TelemetryMissing" in text
        and "CacheStale" in text
        and "CacheUnavailable" in text
        and "RefreshFailure" in text
    )
