"""Tests for the bounded passive Daniel cache collector."""

import io
import json
from pathlib import Path

import pytest

from scripts import daniel_cache_metrics as metrics


def document(state="fresh", completeness="complete", **changes):
    enabled = state != "disabled"
    cache = {
        "enabled": enabled,
        "state": state,
        "lastSuccessfulRefreshAt": "2026-09-16T10:00:00Z" if state == "fresh" else None,
        "dataCompleteness": completeness,
        "refreshDurationMs": 1250 if state not in {"disabled", "warming"} else None,
        "failureCategories": [],
        "configuredRepositoryCount": 3 if enabled else 0,
        "successfulRepositoryCount": 3 if state == "fresh" else 0,
        "failedRepositoryCount": 0,
        "retainedRepositoryCount": 3 if state in {"fresh", "stale"} else 0,
        "oldestDataFetchedAt": "2026-09-16T10:00:00Z" if state in {"fresh", "stale"} else None,
        "retainedDataAgeSeconds": 60 if state in {"fresh", "stale"} else None,
    }
    cache.update(changes)
    return {"schemaVersion": 1, "repos": {"untrusted/repository-name": {}}, "cache": cache}


@pytest.mark.parametrize(
    ("state", "completeness"),
    [
        ("disabled", "none"),
        ("warming", "none"),
        ("fresh", "complete"),
        ("stale", "partial"),
        ("unavailable", "none"),
    ],
)
def test_all_cache_states_remain_distinct(state, completeness):
    cache = metrics.validate_document(document(state, completeness))
    output = metrics.render_metrics(cache, "staging", 1_758_016_860, True)
    assert f'daniel_cache_state{{environment="staging",state="{state}"}} 1' in output
    assert output.count("daniel_cache_state{") == 5
    if state in {"stale", "unavailable"}:
        assert 'state="fresh"} 0' in output


@pytest.mark.parametrize(
    ("completeness", "successful", "failed", "retained"),
    [("complete", 3, 0, 3), ("partial", 1, 2, 2), ("none", 0, 3, 0)],
)
def test_complete_partial_and_empty_counts(completeness, successful, failed, retained):
    state = {"complete": "fresh", "partial": "stale", "none": "unavailable"}[completeness]
    cache = metrics.validate_document(
        document(
            state,
            completeness,
            successfulRepositoryCount=successful,
            failedRepositoryCount=failed,
            retainedRepositoryCount=retained,
        )
    )
    output = metrics.render_metrics(cache, "prod", 1_758_016_860, True)
    assert f'completeness="{completeness}"}} 1' in output
    assert f'result="successful"}} {successful}' in output
    assert f'result="failed"}} {failed}' in output
    assert f'result="retained"}} {retained}' in output


def test_labels_are_only_fixed_bounded_dimensions():
    cache = metrics.validate_document(document())
    output = metrics.render_metrics(cache, "staging", 1_758_016_860, True)
    assert "untrusted/repository-name" not in output
    labels = {
        part.split("=")[0]
        for line in output.splitlines()
        if "{" in line and not line.startswith("#")
        for part in line.split("{", 1)[1].split("}", 1)[0].split(",")
    }
    assert labels <= {"environment", "state", "completeness", "failure_category", "result"}


def test_failure_categories_are_fixed_and_one_hot():
    cache = metrics.validate_document(
        document("stale", "partial", failureCategories=["timeout", "rate_limited"])
    )
    output = metrics.render_metrics(cache, "staging", 1_758_016_860, True)
    assert output.count("daniel_cache_failure_category{") == len(metrics.FAILURE_CATEGORIES)
    assert 'failure_category="timeout"} 1' in output
    with pytest.raises(ValueError, match="failure categories"):
        metrics.validate_document(document(failureCategories=["arbitrary error text"]))


class Response:
    status = 200

    def __init__(self, body):
        self.body = io.BytesIO(body)

    def read(self, size):
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


@pytest.mark.parametrize("body", [b"{", b"\xff", b" " * (metrics.MAX_PAYLOAD_BYTES + 1)])
def test_malformed_and_oversized_payloads_fail_closed(monkeypatch, tmp_path, body):
    requested = []

    class Opener:
        def open(self, request, timeout):
            requested.append((request.full_url, timeout))
            return Response(body)

    monkeypatch.setattr(metrics.urllib.request, "build_opener", lambda *_: Opener())
    output = tmp_path / "cache.prom"
    assert not metrics.collect(
        "https://staging.danielsmith.io/runtime/github-metrics.json", "staging", output
    )
    rendered = output.read_text()
    assert 'daniel_cache_collection_success{environment="staging"} 0' in rendered
    assert 'state="unavailable"} 1' in rendered
    assert len(requested) == 1


def test_missing_endpoint_response_is_unavailable_and_atomic(monkeypatch, tmp_path):
    class Opener:
        def open(self, *_args, **_kwargs):
            raise metrics.urllib.error.URLError("unavailable endpoint")

    monkeypatch.setattr(metrics.urllib.request, "build_opener", lambda *_: Opener())
    output = tmp_path / "cache.prom"
    assert not metrics.collect("https://danielsmith.io/runtime/github-metrics.json", "prod", output)
    assert 'state="unavailable"} 1' in output.read_text()
    assert list(tmp_path.iterdir()) == [output]


def test_collection_only_gets_published_runtime_document(monkeypatch, tmp_path):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.method, timeout))
            return Response(json.dumps(document()).encode())

    monkeypatch.setattr(metrics.urllib.request, "build_opener", lambda *_: Opener())
    output = tmp_path / "cache.prom"
    assert metrics.collect(
        "https://staging.danielsmith.io/runtime/github-metrics.json", "staging", output
    )
    assert calls == [("https://staging.danielsmith.io/runtime/github-metrics.json", "GET", 10)]
    assert "api.github.com" not in output.read_text()


def test_systemd_contract_uses_existing_node_exporter_textfile_collection():
    root = Path(__file__).resolve().parents[1]
    service = (root / "scripts/systemd/daniel-cache-metrics.service").read_text()
    timer = (root / "scripts/systemd/daniel-cache-metrics.timer").read_text()
    assert "ReadWritePaths=/var/lib/node_exporter/textfile_collector" in service
    assert "--environment ${DANIEL_CACHE_ENVIRONMENT} --url ${DANIEL_CACHE_URL}" in service
    assert "OnUnitActiveSec=1min" in timer


def test_installer_stages_environment_specific_passive_collection(tmp_path, monkeypatch):
    import os
    import subprocess

    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, SUGARKUBE_DANIEL_CACHE_ROOT=str(tmp_path))
    subprocess.run(
        [str(root / "scripts/install_daniel_cache_metrics.sh"), "staging"],
        check=True,
        env=environment,
    )
    config = (tmp_path / "etc/sugarkube/daniel-cache-metrics.env").read_text()
    assert config == (
        "DANIEL_CACHE_ENVIRONMENT=staging\n"
        "DANIEL_CACHE_URL=https://staging.danielsmith.io/runtime/github-metrics.json\n"
    )


def test_dashboard_queries_are_aggregate_cardinality_safe_and_generated():
    root = Path(__file__).resolve().parents[1]
    template = json.loads(
        (
            root / "platform/observability/dashboards/sugarkube-observability.template.json"
        ).read_text()
    )
    titles = {
        "Daniel cache state",
        "Daniel cache completeness",
        "Daniel cache freshness age",
        "Daniel cache refresh duration",
        "Daniel cache retained-data age",
        "Daniel cache repository counts",
    }
    panels = {panel["title"]: panel for panel in template["panels"] if panel["title"] in titles}
    assert set(panels) == titles
    expressions = "\n".join(
        target["expr"] for panel in panels.values() for target in panel["targets"]
    )
    assert all(
        'environment=~"$environment"' in target["expr"]
        for panel in panels.values()
        for target in panel["targets"]
    )
    assert "vector(0)" not in expressions
    assert not any(label in expressions for label in ("repo=", "repository=", "url="))
    for environment in ("staging", "prod"):
        generated = (
            root / f"clusters/{environment}/observability/dashboards/"
            f"sugarkube-{environment}-observability.json"
        )
        assert json.loads(generated.read_text())["panels"][-6:] == template["panels"][-6:]
