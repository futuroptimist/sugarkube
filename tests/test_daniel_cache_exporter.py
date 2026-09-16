from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "daniel_cache_exporter",
    ROOT / "monitoring/daniel-cache-exporter/daniel_cache_exporter.py",
)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def payload(state="fresh", completeness="complete", **overrides) -> bytes:
    cache = {
        "enabled": state != "disabled",
        "state": state,
        "lastSuccessfulRefreshAt": "2026-09-16T00:00:00Z" if state == "fresh" else None,
        "dataCompleteness": completeness,
        "refreshDurationMs": 1250,
        "failureCategories": [],
        "configuredRepositoryCount": 3,
        "successfulRepositoryCount": 3,
        "failedRepositoryCount": 0,
        "retainedRepositoryCount": 3,
        "oldestDataFetchedAt": None,
        "retainedDataAgeSeconds": 45,
    }
    cache.update(overrides)
    return json.dumps({"schemaVersion": 1, "cache": cache, "repos": {}}).encode()


@pytest.mark.parametrize("state", exporter.STATES)
def test_all_cache_states_remain_distinct(state):
    text = exporter.render(payload(state=state), "staging")
    assert f'state="{state}"}} 1' in text
    assert sum(line.endswith(" 1") for line in text.splitlines() if "cache_state{" in line) == 1


@pytest.mark.parametrize("value", exporter.COMPLETENESS)
def test_complete_partial_and_empty_data(value):
    text = exporter.render(payload(completeness=value), "prod")
    assert f'completeness="{value}"}} 1' in text


def test_metrics_use_only_bounded_labels_and_aggregate_counts():
    source = payload()
    document = json.loads(source)
    document["repos"] = {"private-owner/arbitrary-repo": {"url": "https://example.invalid/x"}}
    text = exporter.render(json.dumps(document).encode(), "staging")
    assert "private-owner" not in text
    assert "example.invalid" not in text
    label_names = set()
    for line in text.splitlines():
        if "{" not in line or line.startswith("#"):
            continue
        label_names.update(
            item.split("=", 1)[0] for item in line.split("{", 1)[1].split("}", 1)[0].split(",")
        )
    assert label_names == {"environment", "state", "completeness", "failure_category"}


def test_fixed_failure_categories_are_one_hot_without_arbitrary_errors():
    text = exporter.render(payload(failureCategories=["timeout", "rate_limited"]), "staging")
    assert 'failure_category="timeout"} 1' in text
    assert 'failure_category="rate_limited"} 1' in text
    assert len([line for line in text.splitlines() if "failure_category{" in line]) == 8
    with pytest.raises(exporter.ContractError):
        exporter.validate(payload(failureCategories=["HTTP 500 from arbitrary URL"]))


@pytest.mark.parametrize("body", [b"{", b"x" * (exporter.MAX_PAYLOAD_BYTES + 1)])
def test_malformed_and_oversized_payloads_fail_closed(body):
    text = exporter.render(body, "prod")
    assert 'daniel_cache_document_up{environment="prod"} 0' in text
    assert 'state="unavailable"} 1' in text
    assert 'state="fresh"} 0' in text


def test_missing_or_unavailable_endpoint_is_not_healthy(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(exporter.urllib.request, "urlopen", unavailable)
    text = exporter.collect("https://danielsmith.io/runtime/github-metrics.json", "prod")
    assert 'daniel_cache_document_up{environment="prod"} 0' in text
    assert 'state="unavailable"} 1' in text


def test_collection_only_gets_published_document_and_never_github(monkeypatch):
    calls = []

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return payload()

    def open_once(request, timeout):
        calls.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr(exporter.urllib.request, "urlopen", open_once)
    exporter.collect("https://danielsmith.io/runtime/github-metrics.json", "prod")
    assert calls == [("https://danielsmith.io/runtime/github-metrics.json", 10)]
    assert all("api.github.com" not in url for url, _ in calls)


def test_freshness_duration_counts_and_retained_age():
    text = exporter.render(payload(), "prod", datetime(2026, 9, 16, 0, 2, tzinfo=timezone.utc))
    assert 'daniel_cache_freshness_age_seconds{environment="prod"} 120' in text
    assert 'daniel_cache_refresh_duration_seconds{environment="prod"} 1.25' in text
    assert 'daniel_cache_retained_data_age_seconds{environment="prod"} 45' in text
    for suffix in ("configured", "successful", "failed", "retained"):
        assert f"daniel_cache_repositories_{suffix}" in text


def test_dashboard_queries_are_aggregate_and_cardinality_safe():
    dashboard = json.loads(
        (
            ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"
        ).read_text()
    )
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    expected = {
        "Daniel cache state and completeness",
        "Daniel cache freshness and retained-data age",
        "Daniel cache refresh duration",
        "Daniel cache repository outcomes",
    }
    assert expected <= panels.keys()
    expressions = [target["expr"] for title in expected for target in panels[title]["targets"]]
    assert all('environment=~"$environment"' in expression for expression in expressions)
    assert all(label not in " ".join(expressions) for label in ("repo=", "url=", "error="))
