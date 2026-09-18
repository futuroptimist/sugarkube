"""Focused contract tests for passive Daniel GitHub-cache collection."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import daniel_cache_metrics as metrics
from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "config/observability/danielsmith-github-cache.json"
REVISION = "c4d45d96f593d0075096c55ea0a71215350b5ed3"
NOW = datetime(2026, 9, 17, 16, tzinfo=timezone.utc)


def snapshot(**overrides):
    cache = {
        "enabled": True,
        "state": "fresh",
        "lastSuccessfulRefreshAt": "2026-09-17T12:00:00.000Z",
        "oldestDataFetchedAt": "2026-09-17T12:00:00.000Z",
        "retainedDataAgeSeconds": 14400,
        "dataCompleteness": "complete",
        "refreshDurationMs": 125,
        "failureCategories": [],
        "configuredRepositoryCount": 1,
        "successfulRepositoryCount": 1,
        "failedRepositoryCount": 0,
        "retainedRepositoryCount": 0,
    }
    cache.update(overrides)
    repositories = cache["successfulRepositoryCount"] + cache["retainedRepositoryCount"]
    return {
        "schemaVersion": 1,
        "generatedAt": "2026-09-17T12:00:00.000Z" if repositories else None,
        "expiresAt": "2026-09-17T14:00:00.000Z" if repositories else None,
        "source": "runtime-cache",
        "repos": {f"repo-{index}": {} for index in range(repositories)},
        "errors": {},
        "cache": cache,
    }


def encoded(document):
    return json.dumps(document, separators=(",", ":")).encode()


def test_descriptor_is_pinned_deterministic_and_disabled_by_default():
    descriptor = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))
    assert descriptor["sourceRevision"] == REVISION
    assert [item["environment"] for item in descriptor["producers"]] == ["staging", "prod"]
    assert all(item["enabled"] is False for item in descriptor["producers"])
    assert quotas.validate_daniel_cache_contract(descriptor) == 2


def test_disabled_collection_does_not_open_transport():
    producer = json.loads(DESCRIPTOR.read_text())["producers"][0]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled collection performed I/O")

    output = metrics.collect(producer, opener=forbidden)
    assert "daniel_github_cache_monitoring_enabled 0" in output
    assert "daniel_github_cache_collection_up 0" in output
    assert "daniel_github_cache_enabled 0" in output
    assert 'daniel_github_cache_state{state="disabled"} 1' in output
    assert 'daniel_github_cache_state{state="fresh"} 0' in output


@pytest.mark.parametrize("state", metrics.STATES)
def test_all_lifecycle_states_validate(state):
    cases = {
        "disabled": snapshot(
            enabled=False,
            state="disabled",
            lastSuccessfulRefreshAt=None,
            oldestDataFetchedAt=None,
            retainedDataAgeSeconds=None,
            dataCompleteness="none",
            refreshDurationMs=None,
            configuredRepositoryCount=0,
            successfulRepositoryCount=0,
        ),
        "warming": snapshot(
            state="warming",
            lastSuccessfulRefreshAt=None,
            oldestDataFetchedAt=None,
            retainedDataAgeSeconds=None,
            dataCompleteness="none",
            refreshDurationMs=None,
            successfulRepositoryCount=0,
        ),
        "fresh": snapshot(),
        "stale": snapshot(
            state="stale",
            dataCompleteness="partial",
            failureCategories=["rate_limited"],
            successfulRepositoryCount=0,
            failedRepositoryCount=1,
            retainedRepositoryCount=1,
        ),
        "unavailable": snapshot(
            state="unavailable",
            lastSuccessfulRefreshAt=None,
            oldestDataFetchedAt=None,
            retainedDataAgeSeconds=None,
            dataCompleteness="none",
            failureCategories=["network"],
            successfulRepositoryCount=0,
            failedRepositoryCount=1,
        ),
    }
    assert metrics.parse_document(encoded(cases[state]), NOW)["state"] == state


def test_stale_fallback_preserves_last_success_and_true_retained_age():
    document = snapshot(
        state="stale",
        dataCompleteness="partial",
        failureCategories=["rate_limited"],
        successfulRepositoryCount=0,
        failedRepositoryCount=1,
        retainedRepositoryCount=1,
        retainedDataAgeSeconds=14400,
    )
    output = metrics.render(
        metrics.parse_document(encoded(document), NOW), monitoring_enabled=True, status="valid"
    )
    assert "daniel_github_cache_last_success_unixtime_seconds 1789646400" in output
    assert "daniel_github_cache_retained_data_age_seconds 14400" in output
    assert 'daniel_github_cache_refresh_failure{category="rate_limited"} 1' in output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["cache"].update({"state": "healthy"}),
        lambda value: value["cache"].update({"configuredRepositoryCount": 51}),
        lambda value: value["cache"].update({"repository": "private/name"}),
        lambda value: value["cache"].update({"failureCategories": ["arbitrary upstream text"]}),
        lambda value: value["cache"].update(
            {"lastSuccessfulRefreshAt": "2026-09-17T16:01:00.000Z"}
        ),
    ],
)
def test_malformed_contradictory_or_unbounded_documents_fail_closed(mutation):
    document = snapshot()
    mutation(document)
    with pytest.raises(metrics.InvalidDocument):
        metrics.parse_document(encoded(document), NOW)


def test_failed_refresh_cannot_advance_last_success_timestamp():
    document = snapshot(
        state="stale",
        dataCompleteness="partial",
        failureCategories=["timeout"],
        successfulRepositoryCount=0,
        failedRepositoryCount=1,
        retainedRepositoryCount=1,
        lastSuccessfulRefreshAt="2026-09-17T16:01:00.000Z",
    )
    with pytest.raises(metrics.InvalidDocument, match="future timestamp"):
        metrics.parse_document(encoded(document), NOW)


def test_enabled_collection_reads_only_the_passive_snapshot():
    producer = copy.deepcopy(json.loads(DESCRIPTOR.read_text())["producers"][0])
    producer["enabled"] = True
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return producer["url"]

        def read(self, _size):
            return encoded(snapshot())

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        return Response()

    output = metrics.collect(producer, opener=opener, now=NOW)
    assert calls == [(producer["url"], 10)]
    assert "daniel_github_cache_collection_up 1" in output
    assert "github.com" not in output


def test_quota_validator_rejects_unsafe_enabled_cadence():
    descriptor = json.loads(DESCRIPTOR.read_text())
    descriptor["producers"][0].update(enabled=True, cadence="1m")
    with pytest.raises(quotas.ContractError, match="pinned cadence"):
        quotas.validate_daniel_cache_contract(descriptor)
