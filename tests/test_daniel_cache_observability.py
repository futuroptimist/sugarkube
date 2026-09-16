import json
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest

from scripts import daniel_cache_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"


def document(state="fresh", completeness="complete", failures=None, **overrides):
    cache = {
        "enabled": state != "disabled",
        "state": state,
        "lastSuccessfulRefreshAt": "2026-09-16T00:00:00Z" if state == "fresh" else None,
        "dataCompleteness": completeness,
        "refreshDurationMs": 1250 if state not in {"disabled", "warming"} else None,
        "failureCategories": failures or [],
        "configuredRepositoryCount": 13 if state != "disabled" else 0,
        "successfulRepositoryCount": 13 if state == "fresh" else 0,
        "failedRepositoryCount": 0 if state == "fresh" else (13 if state == "unavailable" else 1),
        "retainedRepositoryCount": 0,
        "oldestDataFetchedAt": None,
        "retainedDataAgeSeconds": None,
    }
    cache.update(overrides)
    return json.dumps({"schemaVersion": 1, "cache": cache, "repos": {}, "errors": {}}).encode()


@pytest.mark.parametrize("state", metrics.STATES)
def test_all_cache_states_are_preserved(state):
    completeness = "complete" if state == "fresh" else "none"
    output = metrics.render(document(state, completeness), "staging")
    assert f'daniel_cache_state{{environment="staging",state="{state}"}} 1' in output
    assert output.count("daniel_cache_state{") == 5


@pytest.mark.parametrize("completeness", metrics.COMPLETENESS)
def test_complete_partial_and_empty_data(completeness):
    output = metrics.render(document("stale", completeness), "prod")
    assert f'completeness="{completeness}"}} 1' in output


def test_counts_durations_freshness_and_retained_age_are_aggregate():
    payload = document(
        retainedRepositoryCount=4,
        retainedDataAgeSeconds=90,
        refreshDurationMs=2500,
    )
    output = metrics.render(
        payload, "staging", now=datetime(2026, 9, 16, 0, 1, tzinfo=timezone.utc)
    )
    assert 'daniel_cache_freshness_age_seconds{environment="staging"} 60' in output
    assert 'daniel_cache_refresh_duration_seconds{environment="staging"} 2.5' in output
    assert 'daniel_cache_retained_data_age_seconds{environment="staging"} 90' in output
    assert 'result="retained"} 4' in output


def test_labels_are_only_bounded_domains_and_never_repository_data():
    payload = document()
    source = json.loads(payload)
    source["repos"] = {"owner/private-repository": {"htmlUrl": "https://example.test/secret"}}
    output = metrics.render(json.dumps(source).encode(), "prod")
    labels = set(re.findall(r'(\w+)="([^"]*)"', output))
    allowed = (
        {("environment", "prod")}
        | {("state", value) for value in metrics.STATES}
        | {("completeness", value) for value in metrics.COMPLETENESS}
        | {("category", value) for value in metrics.FAILURES}
        | {("status", value) for value in metrics.DOCUMENT_STATUSES}
        | {("result", value) for value in ("configured", "successful", "failed", "retained")}
    )
    assert labels <= allowed
    assert "private-repository" not in output and "example.test" not in output


def test_fixed_failure_categories_and_unknown_category_rejected():
    output = metrics.render(document("stale", "partial", ["timeout", "rate_limited"]), "prod")
    assert output.count("daniel_cache_failure_category{") == len(metrics.FAILURES)
    assert 'category="timeout"} 1' in output
    with pytest.raises(metrics.InvalidDocument):
        metrics.render(document("stale", "partial", ["raw error text"]), "prod")


@pytest.mark.parametrize(
    ("payload", "status"),
    [(b"not json", "malformed"), (b"{" + b" " * metrics.MAX_BYTES, "oversized")],
)
def test_malformed_and_oversized_payloads_fail_closed(payload, status):
    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    output = metrics.collect(
        "https://danielsmith.io/runtime/github-metrics.json",
        "prod",
        opener=lambda *_args, **_kwargs: Response(payload),
    )
    assert 'daniel_cache_collection_up{environment="prod"} 0' in output
    assert f'status="{status}"}} 1' in output
    assert 'state="unavailable"} 1' in output


def test_missing_endpoint_is_unavailable_and_collection_is_passive():
    seen = []

    def unavailable(request, **kwargs):
        seen.append((request.full_url, request.headers, kwargs))
        raise OSError("missing")

    output = metrics.collect(
        "https://staging.danielsmith.io/runtime/github-metrics.json", "staging", opener=unavailable
    )
    assert len(seen) == 1
    assert seen[0][0].endswith("/runtime/github-metrics.json")
    assert "api.github.com" not in seen[0][0]
    assert 'status="unavailable"} 1' in output


def test_dashboard_queries_cover_cache_contract_without_unbounded_labels():
    dashboard = json.loads(TEMPLATE.read_text())
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    expected = {
        "Daniel cache state",
        "Daniel cache freshness",
        "Daniel cache completeness",
        "Daniel cache refresh duration",
        "Daniel cache retained-data age",
    }
    assert expected <= panels.keys()
    expressions = "\n".join(
        target["expr"] for title in expected for target in panels[title]["targets"]
    )
    assert {"state", "completeness"} <= set(re.findall(r"by \((\w+)\)", expressions))
    assert not re.search(r"repo|repository|url|error|request|token", expressions, re.I)
    assert "or vector(0)" not in expressions
