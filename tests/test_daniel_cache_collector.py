"""Focused contract tests for Daniel's passive GitHub-cache collector."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import daniel_cache_metrics as metrics
from scripts import validate_probe_quotas

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "config/observability/danielsmith-github-cache.json"


def document(state="fresh"):
    stale = state == "stale"
    available = state in {"fresh", "stale"}
    unavailable = state == "unavailable"
    return {
        "schemaVersion": 1,
        "generatedAt": "2026-09-17T00:00:00Z" if available else None,
        "expiresAt": "2026-09-17T00:05:00Z" if available else None,
        "source": metrics.SOURCE_VALUES[state],
        "repos": {"owner/repo": {}} if available else {},
        "errors": {},
        "cache": {
            "enabled": state != "disabled",
            "state": state,
            "lastSuccessfulRefreshAt": "2026-09-16T23:00:00Z" if available else None,
            "dataCompleteness": "partial" if stale else ("complete" if available else "none"),
            "refreshDurationMs": 1000 if state not in {"disabled", "warming"} else None,
            "failureCategories": (
                ["rate_limited" if stale else "network"] if stale or unavailable else []
            ),
            "configuredRepositoryCount": 1 if state not in {"disabled", "warming"} else 0,
            "successfulRepositoryCount": 0 if stale else (1 if available else 0),
            "failedRepositoryCount": 1 if stale or unavailable else 0,
            "retainedRepositoryCount": 1 if stale else 0,
            "oldestDataFetchedAt": "2026-09-17T00:00:00Z" if available else None,
            "retainedDataAgeSeconds": 3600 if available else None,
        },
    }


def encoded(value):
    return json.dumps(value).encode()


def test_descriptor_is_pinned_disabled_and_quota_validated():
    contract = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))
    assert contract["sourceRevision"] == "c4d45d96f593d0075096c55ea0a71215350b5ed3"
    assert all(item["enabled"] is False for item in contract["producers"])
    assert validate_probe_quotas.validate_daniel_cache_contract(contract) == 2


def test_disabled_descriptor_does_not_open_any_url():
    producer = metrics.load_producer(DESCRIPTOR, "staging")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled collection made a network request")

    output = metrics.collect_producer(producer, opener=forbidden)
    assert 'daniel_cache_monitoring_enabled{environment="staging"} 0' in output
    assert 'state="disabled"} 1' in output
    assert 'daniel_cache_collection_up{environment="staging"} 0' in output


@pytest.mark.parametrize("state", metrics.STATES)
def test_all_lifecycle_states_are_preserved(state):
    value = document(state)
    if state == "warming":
        value["cache"]["configuredRepositoryCount"] = 1
    output = metrics.render(encoded(value), "staging")
    assert f'state="{state}"}} 1' in output


def test_stale_fallback_preserves_last_success_freshness_and_failure():
    now = datetime(2026, 9, 17, 1, 0, tzinfo=timezone.utc)
    output = metrics.render(encoded(document("stale")), "prod", now=now)
    assert 'daniel_cache_freshness_age_seconds{environment="prod"} 7200' in output
    assert 'daniel_cache_retained_data_age_seconds{environment="prod"} 3600' in output
    assert 'category="rate_limited"} 1' in output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(requestId="unbounded"),
        lambda value: value["cache"].update(failureCategories=["private-error"]),
        lambda value: value["cache"].update(retainedRepositoryCount=2),
        lambda value: value.update(source="arbitrary"),
    ],
)
def test_malformed_contradictory_or_unbounded_data_fails_closed(mutation):
    value = copy.deepcopy(document("stale"))
    mutation(value)
    with pytest.raises(metrics.InvalidDocument):
        metrics.parse_document(encoded(value))
