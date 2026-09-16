"""Contracts for passive Daniel cache runtime collection and dashboards."""

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from scripts import daniel_cache_metrics as collector
from scripts.generate_observability_dashboards import PROFILES, render

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 9, 16, 12, tzinfo=dt.timezone.utc)


def document(state="fresh", completeness="complete", categories=None):
    return {
        "schemaVersion": 1,
        "generatedAt": "2026-09-16T11:00:00Z",
        "expiresAt": "2026-09-16T13:00:00Z",
        "source": "github-api",
        "repos": {},
        "errors": {},
        "cache": {
            "enabled": state != "disabled",
            "state": state,
            "lastSuccessfulRefreshAt": (
                "2026-09-16T11:00:00Z" if state in {"fresh", "stale"} else None
            ),
            "dataCompleteness": completeness,
            "refreshDurationMs": 1250 if state not in {"disabled", "warming"} else None,
            "failureCategories": categories or [],
            "configuredRepositoryCount": 3,
            "successfulRepositoryCount": (
                3 if completeness == "complete" else (1 if completeness == "partial" else 0)
            ),
            "failedRepositoryCount": (
                0 if completeness == "complete" else (2 if completeness == "partial" else 3)
            ),
            "retainedRepositoryCount": 1 if state == "stale" else 0,
            "oldestDataFetchedAt": "2026-09-16T10:00:00Z" if state in {"fresh", "stale"} else None,
            "retainedDataAgeSeconds": 7200 if state == "stale" else None,
        },
    }


def payload(**kwargs):
    return json.dumps(document(**kwargs)).encode()


@pytest.mark.parametrize("state", collector.STATES)
def test_all_cache_states_are_exposed_without_becoming_fresh(state):
    completeness = "complete" if state == "fresh" else ("partial" if state == "stale" else "none")
    parsed = collector.parse_document(payload(state=state, completeness=completeness))
    metrics = collector.render_metrics(parsed, "staging", NOW)
    assert f'daniel_cache_state_info{{environment="staging",state="{state}"}} 1' in metrics
    assert (
        sum(
            line.endswith(" 1")
            for line in metrics.splitlines()
            if line.startswith("daniel_cache_state_info")
        )
        == 1
    )


@pytest.mark.parametrize("completeness", collector.COMPLETENESS)
def test_complete_partial_and_empty_documents(completeness):
    state = {"complete": "fresh", "partial": "stale", "none": "unavailable"}[completeness]
    metrics = collector.render_metrics(
        collector.parse_document(payload(state=state, completeness=completeness)), "prod", NOW
    )
    assert f'completeness="{completeness}"}} 1' in metrics


def test_labels_are_fixed_and_repository_identity_is_never_exported():
    raw = document(state="stale", completeness="partial", categories=["timeout"])
    raw["repos"] = {
        "private-owner/secret-repo": {"htmlUrl": "https://github.com/private-owner/secret-repo"}
    }
    metrics = collector.render_metrics(
        collector.parse_document(json.dumps(raw).encode()), "staging", NOW
    )
    labels = set(re.findall(r"([a-z_]+)=", metrics))
    assert labels == {"environment", "state", "completeness", "failure_category"}
    assert not any(value in metrics for value in ("private-owner", "secret-repo", "github.com"))


def test_fixed_failure_categories_are_one_hot_bounded():
    parsed = collector.parse_document(
        payload(
            state="stale", completeness="partial", categories=list(collector.FAILURE_CATEGORIES)
        )
    )
    metrics = collector.render_metrics(parsed, "staging", NOW)
    assert (
        sum(
            line.endswith(" 1")
            for line in metrics.splitlines()
            if line.startswith("daniel_cache_failure_category_info")
        )
        == 8
    )
    invalid = document()
    invalid["cache"]["failureCategories"] = ["arbitrary error"]
    with pytest.raises(collector.InvalidDocument):
        collector.parse_document(json.dumps(invalid).encode())


@pytest.mark.parametrize("bad", [b"{", b"x" * (collector.MAX_PAYLOAD_BYTES + 1), b"{}"])
def test_malformed_oversized_and_schema_missing_payloads_fail_closed(bad):
    with pytest.raises(collector.InvalidDocument):
        collector.parse_document(bad)


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, limit):
        return self.body[:limit]


def test_missing_endpoint_emits_unavailable_and_collection_down():
    def unavailable(request, timeout):
        raise OSError("unavailable")

    metrics, ok = collector.collect(
        "https://staging.danielsmith.io/runtime/github-metrics.json",
        "staging",
        opener=unavailable,
        now=NOW,
    )
    assert not ok
    assert 'daniel_cache_collection_up{environment="staging"} 0' in metrics
    assert 'state="unavailable"} 1' in metrics
    assert 'state="fresh"} 0' in metrics


def test_collection_only_reads_the_published_daniel_endpoint():
    seen = []

    def open_runtime(request, timeout):
        seen.append((request.full_url, request.get_method()))
        return Response(payload())

    _, ok = collector.collect(
        "https://danielsmith.io/runtime/github-metrics.json", "prod", opener=open_runtime, now=NOW
    )
    assert ok and seen == [("https://danielsmith.io/runtime/github-metrics.json", "GET")]
    assert all("api.github.com" not in url for url, _ in seen)


def test_dashboard_queries_are_aggregate_and_cardinality_safe():
    template = json.loads(
        (
            ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"
        ).read_text()
    )
    panels = {panel["title"]: panel for panel in template["panels"]}
    expected = {
        "Daniel cache state",
        "Daniel cache completeness",
        "Daniel cache freshness age",
        "Daniel cache refresh duration",
        "Daniel cache repository counts",
        "Daniel cache retained-data age",
    }
    assert expected <= panels.keys()
    expressions = "\n".join(
        target["expr"] for title in expected for target in panels[title]["targets"]
    )
    assert 'environment=~"$environment"' in expressions
    assert not re.search(r"\b(repo|repository|url|error|request_id)\s*=", expressions)
    assert not re.search(r"\bby\s*\([^)]*(repo|url|error)", expressions)
    for profile in PROFILES.values():
        assert profile["path"].read_text() == render(profile)
