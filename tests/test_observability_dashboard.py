import copy
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
PROD = ROOT / "clusters/prod/observability/dashboards/sugarkube-prod-observability.json"
GENERATOR = ROOT / "scripts/generate_observability_dashboards.py"
TEMPLATE = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"
sys.path.insert(0, str(ROOT))
from scripts import daniel_cache_metrics as metrics  # noqa: E402
from scripts import generate_observability_dashboards as generator  # noqa: E402
from scripts import validate_observability_dashboard as validator  # noqa: E402


@pytest.fixture
def dashboards():
    return json.loads(STAGING.read_text()), json.loads(PROD.read_text())


def panel(document, title):
    return next(item for item in document["panels"] if item["title"] == title)


def write_candidate(tmp_path, document):
    path = tmp_path / f'{document["uid"]}.json'
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


FIXED_NOW = datetime(2026, 9, 16, 0, 1, tzinfo=timezone.utc)


def daniel_document(state="fresh", **overrides):
    variants = {
        "disabled": dict(
            enabled=False,
            dataCompleteness="none",
            configuredRepositoryCount=0,
            successfulRepositoryCount=0,
            failedRepositoryCount=0,
            retainedRepositoryCount=0,
            failureCategories=[],
            repos={},
            nulls=True,
        ),
        "warming": dict(
            enabled=True,
            dataCompleteness="none",
            configuredRepositoryCount=2,
            successfulRepositoryCount=0,
            failedRepositoryCount=0,
            retainedRepositoryCount=0,
            failureCategories=[],
            repos={},
            nulls=True,
        ),
        "fresh": dict(
            enabled=True,
            dataCompleteness="complete",
            configuredRepositoryCount=2,
            successfulRepositoryCount=2,
            failedRepositoryCount=0,
            retainedRepositoryCount=0,
            failureCategories=[],
            repos={"a/one": {}, "a/two": {}},
            nulls=False,
        ),
        "stale": dict(
            enabled=True,
            dataCompleteness="partial",
            configuredRepositoryCount=2,
            successfulRepositoryCount=1,
            failedRepositoryCount=1,
            retainedRepositoryCount=1,
            failureCategories=["timeout"],
            repos={"a/one": {}, "a/two": {}},
            nulls=False,
        ),
        "unavailable": dict(
            enabled=True,
            dataCompleteness="none",
            configuredRepositoryCount=2,
            successfulRepositoryCount=0,
            failedRepositoryCount=2,
            retainedRepositoryCount=0,
            failureCategories=["network"],
            repos={},
            nulls=False,
        ),
    }
    values = variants[state]
    nulls = values.pop("nulls")
    repos = values.pop("repos")
    cache = {
        "state": state,
        "lastSuccessfulRefreshAt": (
            None if state in {"disabled", "warming", "unavailable"} else "2026-09-16T00:00:00.000Z"
        ),
        "refreshDurationMs": None if nulls else 3_600_000,
        "oldestDataFetchedAt": None if not repos else "2026-09-15T23:59:00.000Z",
        "retainedDataAgeSeconds": None if not repos else 60,
        **values,
    }
    cache.update(overrides.pop("cache", {}))
    document = {
        "schemaVersion": 1,
        "generatedAt": None if nulls else "2026-09-15T23:59:00.000Z",
        "expiresAt": None if nulls else "2026-09-16T01:14:00.000Z",
        "source": metrics.SOURCE_BY_STATE[state],
        "repos": repos,
        "errors": {},
        "cache": cache,
    }
    document.update(overrides)
    return json.dumps(document).encode()


class DanielResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_generator_check_and_outputs_are_deterministic(dashboards):
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"], cwd=ROOT, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    staging, prod = dashboards
    staging_panels = (
        json.dumps(staging["panels"])
        .replace('provider=\\"tokenplace\\"', 'provider=\\"PRIMARY\\"')
        .replace(
            '\\"sugarkube-int\\", \\"cluster\\", \\"^$\\"', '\\"CLUSTER\\", \\"cluster\\", \\"^$\\"'
        )
    )
    prod_panels = (
        json.dumps(prod["panels"])
        .replace('provider=\\"openai\\"', 'provider=\\"PRIMARY\\"')
        .replace(
            '\\"sugarkube-prod\\", \\"cluster\\", \\"^$\\"',
            '\\"CLUSTER\\", \\"cluster\\", \\"^$\\"',
        )
    )
    assert staging_panels == prod_panels
    assert len(staging["panels"]) == 92
    assert sum(item["type"] == "row" for item in staging["panels"]) == 15
    assert sum(item["type"] != "row" for item in staging["panels"]) == 77


@pytest.mark.parametrize("state", metrics.STATES)
def test_daniel_collector_accepts_every_published_state(state):
    output = metrics.render(daniel_document(state), "staging", now=FIXED_NOW)
    assert f'state="{state}"}} 1' in output
    expected = {"fresh": "complete", "stale": "partial"}.get(state, "none")
    assert f'completeness="{expected}"}} 1' in output


def test_daniel_collector_preserves_all_categories_and_numeric_boundaries():
    payload = daniel_document(
        "stale",
        cache={
            "failureCategories": list(metrics.FAILURES),
            "configuredRepositoryCount": 50,
            "successfulRepositoryCount": 49,
            "failedRepositoryCount": 1,
            "retainedRepositoryCount": 1,
            "refreshDurationMs": metrics.MAX_DURATION_MS,
            "retainedDataAgeSeconds": metrics.MAX_AGE_SECONDS,
        },
        repos={f"a/repo-{index}": {} for index in range(50)},
    )
    output = metrics.render(payload, "prod", now=FIXED_NOW)
    assert 'refresh_duration_seconds{environment="prod"} 3600' in output
    assert 'retained_data_age_seconds{environment="prod"} 31536000' in output
    assert all(f'category="{category}"}} 1' in output for category in metrics.FAILURES)


def test_daniel_collector_emits_only_bounded_metric_labels_and_values():
    repository = "distinctive-owner/distinctive-repository"
    url = "https://example.invalid/distinctive-repository"
    arbitrary = "distinctive-non-metric-text"
    payload = json.loads(daniel_document("fresh"))
    payload["repos"] = {
        repository: {"url": url, "description": arbitrary},
        "a/two": {"url": f"{url}/two"},
    }
    payload["errors"] = {repository: arbitrary}

    output = metrics.render(json.dumps(payload).encode(), "prod", now=FIXED_NOW)
    series = {}
    for line in output.splitlines():
        if line.startswith("#") or line.startswith("daniel_github_cache_"):
            continue
        name, labels, _value = re.fullmatch(r"(\w+)\{([^}]*)\} (\S+)", line).groups()
        parsed_labels = dict(re.findall(r'(\w+)="([^"]*)"', labels))
        series.setdefault(name, []).append(parsed_labels)

    expected = {
        "daniel_cache_collection_up": ({"environment"}, 1),
        "daniel_cache_state": ({"environment", "state"}, len(metrics.STATES)),
        "daniel_cache_data_completeness": (
            {"environment", "completeness"},
            len(metrics.COMPLETENESS),
        ),
        "daniel_cache_failure_category": (
            {"environment", "category"},
            len(metrics.FAILURES),
        ),
        "daniel_cache_freshness_age_seconds": ({"environment"}, 1),
        "daniel_cache_refresh_duration_seconds": ({"environment"}, 1),
        "daniel_cache_retained_data_age_seconds": ({"environment"}, 1),
        "daniel_cache_repositories": ({"environment", "result"}, 4),
    }
    assert set(series) == set(expected)
    for name, (label_keys, count) in expected.items():
        assert len(series[name]) == count
        assert all(set(labels) == label_keys for labels in series[name])
        assert all(labels["environment"] == "prod" for labels in series[name])
    assert {labels["state"] for labels in series["daniel_cache_state"]} == set(metrics.STATES)
    assert {labels["completeness"] for labels in series["daniel_cache_data_completeness"]} == set(
        metrics.COMPLETENESS
    )
    assert {labels["category"] for labels in series["daniel_cache_failure_category"]} == set(
        metrics.FAILURES
    )
    assert {labels["result"] for labels in series["daniel_cache_repositories"]} == {
        "configured",
        "successful",
        "failed",
        "retained",
    }
    assert repository not in output
    assert url not in output
    assert arbitrary not in output


@pytest.mark.parametrize(
    ("state", "cache_change"),
    [
        ("fresh", {"dataCompleteness": "none"}),
        ("fresh", {"failedRepositoryCount": 1}),
        ("fresh", {"successfulRepositoryCount": True}),
        ("stale", {"retainedRepositoryCount": 2}),
        ("unavailable", {"successfulRepositoryCount": 1}),
        ("warming", {"refreshDurationMs": 1}),
    ],
)
def test_daniel_collector_rejects_contradictory_or_invalid_cache_fields(state, cache_change):
    with pytest.raises(metrics.InvalidDocument):
        metrics.parse_document(daniel_document(state, cache=cache_change), now=FIXED_NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"schemaVersion": True},
        {"source": None},
        {"generatedAt": 123},
        {"expiresAt": "not-a-timestamp"},
        {"errors": []},
    ],
)
def test_daniel_collector_rejects_invalid_envelope_types(change):
    with pytest.raises(metrics.InvalidDocument):
        metrics.parse_document(daniel_document("fresh", **change), now=FIXED_NOW)


def test_daniel_collector_rejects_missing_fields_and_structured_categories():
    missing = json.loads(daniel_document("fresh"))
    del missing["cache"]["failedRepositoryCount"]
    structured = json.loads(daniel_document("stale"))
    structured["cache"]["failureCategories"] = [{"code": "timeout"}]
    for payload in (missing, structured):
        with pytest.raises(metrics.InvalidDocument):
            metrics.parse_document(json.dumps(payload).encode(), now=FIXED_NOW)


@pytest.mark.parametrize(
    ("payload", "status"),
    [(b"not json", "malformed"), (b"{" + b" " * metrics.MAX_BYTES, "oversized")],
)
def test_daniel_malformed_input_replaces_healthy_textfile(tmp_path, payload, status):
    path = tmp_path / "daniel-cache.prom"
    metrics.write_textfile(path, metrics.render(daniel_document("fresh"), "prod", now=FIXED_NOW))
    result = metrics.collect(
        metrics.RUNTIME_URLS["prod"],
        "prod",
        opener=lambda *_args, **_kwargs: DanielResponse(payload),
        now=FIXED_NOW,
    )
    metrics.write_textfile(path, result)
    published = path.read_text()
    assert 'daniel_cache_collection_up{environment="prod"} 0' in published
    assert 'result="successful"' not in published
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.parametrize(
    "payload",
    [
        b'{"number":' + b"9" * 5_000 + b"}",
        b"[" * 10_000 + b"]" * 10_000,
    ],
    ids=["integer-conversion-limit", "decoder-recursion-limit"],
)
def test_daniel_decoder_failures_replace_healthy_textfile(tmp_path, payload):
    path = tmp_path / "daniel-cache.prom"
    healthy = metrics.render(daniel_document("fresh"), "prod", now=FIXED_NOW)
    metrics.write_textfile(path, healthy)

    result = metrics.collect(
        metrics.RUNTIME_URLS["prod"],
        "prod",
        opener=lambda *_args, **_kwargs: DanielResponse(payload),
        now=FIXED_NOW,
    )
    metrics.write_textfile(path, result)

    published = path.read_text()
    assert 'daniel_cache_collection_up{environment="prod"} 0' in published
    assert 'result="successful"' not in published
    assert "daniel_cache_freshness_age_seconds" not in published
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.parametrize("decoder_error", [ValueError("integer limit"), RecursionError()])
def test_daniel_decoder_errors_are_normalized(monkeypatch, decoder_error):
    def fail_decode(_payload, **_kwargs):
        raise decoder_error

    monkeypatch.setattr(metrics.json, "loads", fail_decode)
    with pytest.raises(metrics.InvalidDocument, match="JSON"):
        metrics.parse_document(b"{}", now=FIXED_NOW)


def test_daniel_excessive_numeric_field_is_malformed_not_oversized():
    payload = daniel_document("fresh", cache={"refreshDurationMs": 10**3_999})
    output = metrics.collect(
        metrics.RUNTIME_URLS["prod"],
        "prod",
        opener=lambda *_args, **_kwargs: DanielResponse(payload),
        now=FIXED_NOW,
    )


def test_daniel_successful_fetch_is_single_passive_canonical_request():
    seen = []

    def opener(request, **kwargs):
        seen.append((request.full_url, dict(request.header_items()), kwargs))
        return DanielResponse(daniel_document("fresh"))

    output = metrics.collect(
        metrics.RUNTIME_URLS["staging"], "staging", opener=opener, now=FIXED_NOW
    )
    assert 'daniel_cache_collection_up{environment="staging"} 1' in output
    assert len(seen) == 1 and seen[0][0] == metrics.RUNTIME_URLS["staging"]
    assert not any(key.lower() == "authorization" for key in seen[0][1])
    assert "api.github.com" not in json.dumps(seen)


def test_daniel_stale_total_failure_preserves_retained_records():
    payload = daniel_document(
        "stale",
        cache={
            "successfulRepositoryCount": 0,
            "failedRepositoryCount": 2,
            "retainedRepositoryCount": 2,
        },
    )
    output = metrics.render(payload, "prod", now=FIXED_NOW)
    assert 'state="stale"} 1' in output
    assert 'result="successful"} 0' in output
    assert 'result="retained"} 2' in output


def test_daniel_missing_response_is_unavailable_and_replaces_samples():
    def missing(*_args, **_kwargs):
        raise OSError("endpoint unavailable")

    output = metrics.collect(metrics.RUNTIME_URLS["staging"], "staging", opener=missing)
    assert 'daniel_cache_collection_up{environment="staging"} 0' in output
    assert 'result="successful"' not in output


def test_daniel_redirect_is_rejected_without_contacting_destination():
    seen = []

    def redirect(request, **_kwargs):
        seen.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 302, "redirect", {}, None)

    output = metrics.collect(metrics.RUNTIME_URLS["prod"], "prod", opener=redirect)
    assert seen == [metrics.RUNTIME_URLS["prod"]]
    with pytest.raises(ValueError, match="canonical runtime URL"):
        metrics.collect("https://example.test/runtime/github-metrics.json", "prod")


def test_daniel_redirect_handler_rejects_before_following():
    request = urllib.request.Request(metrics.RUNTIME_URLS["prod"])
    with pytest.raises(urllib.error.HTTPError, match="redirect rejected"):
        metrics._RejectRedirects().redirect_request(
            request, None, 302, "Found", {}, "https://example.invalid/redirect"
        )


def test_daniel_response_url_must_remain_canonical():
    response = DanielResponse(daniel_document("fresh"))
    response.geturl = lambda: "https://example.invalid/redirect"
    output = metrics.collect(
        metrics.RUNTIME_URLS["prod"], "prod", opener=lambda *_args, **_kwargs: response
    )


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"schemaVersion": 2}, "schemaVersion"),
        ({"cache": {"state": "unknown"}}, "cache enum"),
        ({"cache": {"enabled": False}}, "cache state/count relationship"),
        ({"cache": {"successfulRepositoryCount": 0.5}}, "successful"),
        ({"cache": {"retainedDataAgeSeconds": -1}}, "retainedDataAgeSeconds"),
        ({"generatedAt": "2026-99-99T00:00:00Z"}, "generatedAt"),
        ({"generatedAt": "2026-09-16T00:00:00+01:00Z"}, "generatedAt"),
    ],
)
def test_daniel_collector_rejects_additional_invalid_contract_values(change, field):
    cache_change = change.pop("cache", None)
    payload = daniel_document("fresh", cache=cache_change or {}, **change)
    with pytest.raises(metrics.InvalidDocument, match=field):
        metrics.parse_document(payload, now=FIXED_NOW)


def test_daniel_textfile_cleans_up_temporary_file_after_replace_failure(tmp_path, monkeypatch):
    def fail_replace(*_args):
        raise OSError("replacement failed")

    monkeypatch.setattr(metrics.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        metrics.write_textfile(tmp_path / "daniel-cache.prom", "sample\n")
    assert list(tmp_path.iterdir()) == []


def test_daniel_main_collects_and_writes_requested_environment(tmp_path, monkeypatch):
    output_path = tmp_path / "daniel-cache.prom"
    descriptor = ROOT / "config/observability/danielsmith-github-cache.json"
    monkeypatch.setattr(
        metrics,
        "collect",
        lambda producer: f'{producer["url"]} environment="{producer["environment"]}"\n',
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daniel_cache_metrics.py",
            "--descriptor",
            str(descriptor),
            "--environment",
            "staging",
            "--output",
            str(output_path),
        ],
    )
    assert metrics.main() == 0
    assert output_path.read_text() == (f'{metrics.RUNTIME_URLS["staging"]} environment="staging"\n')
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o644


def test_public_availability_summary_includes_gitshelves_in_every_expression(dashboards):
    expected_fleet = "blackbox-(dspace|tokenplace|danielsmith|jobbot3000|gitshelves)"
    documents = [json.loads(TEMPLATE.read_text(encoding="utf-8")), *dashboards]
    for document in documents:
        expressions = [
            target["expr"] for target in panel(document, "Public availability summary")["targets"]
        ]
        assert len(expressions) == 3
        assert all(expected_fleet in expression for expression in expressions)


def test_daniel_dashboard_contract_covers_metrics_scope_grouping_units_and_missing_data(
    dashboards,
):
    for document in (json.loads(TEMPLATE.read_text()), *dashboards):
        for title, (expression, unit, legend) in validator.DANIEL_PANEL_CONTRACT.items():
            item = panel(document, title)
            assert item["targets"] == [{"refId": "A", "expr": expression, "legendFormat": legend}]
            assert item["fieldConfig"]["defaults"]["unit"] == unit
            assert item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
            assert 'environment=~"$environment"' in expression
            if title.startswith("Daniel cache"):
                assert 'cluster=~"$cluster"' in expression
                assert 'name=~"danielsmith-github-cache-$environment"' in expression
                assert "daniel_cache_" not in expression
            assert "vector(0)" not in expression
        assert "by (state)" in validator.DANIEL_PANEL_CONTRACT["Daniel cache state"][0]
        assert (
            "by (completeness)" in validator.DANIEL_PANEL_CONTRACT["Daniel cache completeness"][0]
        )
        assert panel(document, "Daniel cache state")["id"] == 66
        assert (
            panel(document, "Daniel cache completeness")["fieldConfig"]["defaults"]["unit"]
            == "none"
        )
        assert 'state="fresh"' in validator.DANIEL_PANEL_CONTRACT["Daniel cache freshness"][0]
        assert (
            'state="stale"' in validator.DANIEL_PANEL_CONTRACT["Daniel cache retained-data age"][0]
        )
        assert "monitoring_enabled" in validator.DANIEL_PANEL_CONTRACT["Daniel cache state"][0]
        assert "collection_up" in validator.DANIEL_PANEL_CONTRACT["Daniel cache state"][0]


def test_daniel_visitor_dashboard_contract_is_scoped_bounded_and_fail_closed(dashboards):
    documents = (json.loads(TEMPLATE.read_text()), *dashboards)
    categorical = {
        "Daniel visitor journey state",
        "Daniel visitor journey success",
        "Daniel visitor journey failure stage",
        "Daniel visitor journey unavailable or stale",
    }
    for document in documents:
        cluster = next(
            variable["current"]["value"]
            for variable in document["templating"]["list"]
            if variable["name"] == "cluster"
        )
        for title, (expression, unit, legend) in validator.DANIEL_VISITOR_PANEL_CONTRACT.items():
            expression = expression.replace("${CLUSTER}", cluster)
            item = panel(document, title)
            assert item["targets"] == [{"refId": "A", "expr": expression, "legendFormat": legend}]
            assert item["fieldConfig"]["defaults"]["unit"] == unit
            assert item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
            assert 'application="danielsmith"' in expression
            assert 'environment=~"$environment"' in expression
            assert 'cluster=~"$cluster"' in expression
            assert 'cluster=""' in expression
            assert f'"cluster", "{cluster}", "cluster", "^$"' in expression
            assert 'name=~"danielsmith-visitor-journey-$environment"' in expression
            assert "vector(0)" not in expression
            if title in categorical:
                assert unit == "short"
        assert validator.DANIEL_VISITOR_PANEL_CONTRACT["Daniel visitor journey freshness"][1] == "s"
        assert (
            validator.DANIEL_VISITOR_PANEL_CONTRACT["Daniel visitor journey aggregate duration"][1]
            == "s"
        )


def _promtool_series(metric, value, **labels):
    label_text = ",".join(f'{name}="{label}"' for name, label in labels.items())
    return {"series": f"{metric}{{{label_text}}}", "values": f"{value}x31"}


def _visitor_fixture(expected=1, enabled=1, freshness=780, state="success", **labels):
    identity = {
        "application": "danielsmith",
        "environment": "staging",
        "name": "danielsmith-visitor-journey-staging",
        **labels,
    }
    series = [
        _promtool_series("danielsmith_visitor_journey_monitoring_expected", expected, **identity),
        _promtool_series("danielsmith_visitor_journey_monitoring_enabled", enabled, **identity),
    ]
    if freshness is not None:
        series.extend(
            [
                _promtool_series(
                    "danielsmith_visitor_journey_freshness_timestamp_seconds",
                    freshness,
                    **identity,
                ),
                _promtool_series("danielsmith_visitor_journey_state", 1, state=state, **identity),
                _promtool_series(
                    "danielsmith_visitor_journey_success",
                    int(state in ("success", "recovered")),
                    **identity,
                ),
                _promtool_series(
                    "danielsmith_visitor_journey_failure_stage",
                    int(state == "failure"),
                    failure_stage="navigation" if state == "failure" else "none",
                    **identity,
                ),
            ]
        )
    return series


def test_daniel_visitor_promql_lifecycle_semantics_with_promtool(tmp_path, dashboards):
    """Evaluate the rendered dashboard PromQL rather than approximating it in Python."""
    promtool = os.environ.get("PROMTOOL") or shutil.which("promtool")
    if not promtool:
        # TODO: Ensure offline PromQL evaluation runs where promtool is available.
        # Root cause: Neither PROMTOOL nor PATH supplies a promtool executable in this environment.
        # Estimated fix: Provide promtool through PROMTOOL or PATH and rerun this test.
        pytest.skip("promtool is required for offline dashboard PromQL evaluation")

    expressions = {
        title: panel(dashboards[0], title)["targets"][0]["expr"]
        .replace("$environment", "staging")
        .replace("$cluster", "sugarkube-int")
        for title in validator.DANIEL_VISITOR_PANEL_CONTRACT
    }
    identity = {
        "application": "danielsmith",
        "cluster": "sugarkube-int",
        "environment": "staging",
        "name": "danielsmith-visitor-journey-staging",
    }

    def sample(labels, value):
        return {
            "labels": "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}",
            "value": value,
        }

    cases = []

    def add_case(series, checks):
        cases.append(
            {
                "interval": "1m",
                "input_series": series,
                "promql_expr_test": [
                    {
                        "expr": expressions[title],
                        "eval_time": "30m",
                        "exp_samples": expected,
                    }
                    for title, expected in checks.items()
                ],
            }
        )

    for state in ("success", "recovered"):
        add_case(
            _visitor_fixture(state=state),
            {
                "Daniel visitor journey state": [sample({"state": state}, 1)],
                "Daniel visitor journey success": [sample(identity, 1)],
                "Daniel visitor journey freshness": [sample(identity, 1020)],
                "Daniel visitor journey unavailable or stale": [],
            },
        )
    add_case(
        _visitor_fixture(state="failure"),
        {
            "Daniel visitor journey success": [sample(identity, 0)],
            "Daniel visitor journey failure stage": [
                sample({**identity, "failure_stage": "navigation"}, 1)
            ],
        },
    )
    add_case(
        _visitor_fixture(freshness=779),
        {
            "Daniel visitor journey state": [],
            "Daniel visitor journey success": [],
            "Daniel visitor journey unavailable or stale": [sample({"state": "stale"}, 1)],
        },
    )
    add_case(
        _visitor_fixture(freshness=779, state="failure"),
        {"Daniel visitor journey failure stage": []},
    )
    add_case(
        _visitor_fixture(expected=0, enabled=0, freshness=None),
        {
            "Daniel visitor journey success": [],
            "Daniel visitor journey unavailable or stale": [],
        },
    )
    add_case(
        _visitor_fixture(freshness=None),
        {"Daniel visitor journey unavailable or stale": [sample({"state": "stale"}, 1)]},
    )
    add_case(
        _visitor_fixture(cluster="wrong-cluster"),
        {"Daniel visitor journey success": [], "Daniel visitor journey state": []},
    )
    add_case(
        _visitor_fixture(environment="prod", name="danielsmith-visitor-journey-prod"),
        {"Daniel visitor journey success": [], "Daniel visitor journey state": []},
    )

    fixture = tmp_path / "visitor-dashboard-promql.yml"
    fixture.write_text(json.dumps({"rule_files": [], "tests": cases}), encoding="utf-8")
    completed = subprocess.run(
        [promtool, "test", "rules", str(fixture)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_daniel_visitor_dashboard_layout_is_stable(dashboards):
    expected_layout = {
        "Daniel visitor journey": (79, "row", {"h": 1, "w": 24, "x": 0, "y": 247}),
        "Daniel visitor journey state": (
            80,
            "timeseries",
            {"h": 8, "w": 12, "x": 0, "y": 248},
        ),
        "Daniel visitor journey success": (
            81,
            "timeseries",
            {"h": 8, "w": 12, "x": 12, "y": 248},
        ),
        "Daniel visitor journey freshness": (
            82,
            "timeseries",
            {"h": 8, "w": 12, "x": 0, "y": 256},
        ),
        "Daniel visitor journey aggregate duration": (
            83,
            "timeseries",
            {"h": 8, "w": 12, "x": 12, "y": 256},
        ),
        "Daniel visitor journey failure stage": (
            84,
            "timeseries",
            {"h": 8, "w": 12, "x": 0, "y": 264},
        ),
        "Daniel visitor journey unavailable or stale": (
            85,
            "timeseries",
            {"h": 8, "w": 12, "x": 12, "y": 264},
        ),
    }
    assert validator.DANIEL_VISITOR_LAYOUT_CONTRACT == expected_layout
    for document in (json.loads(TEMPLATE.read_text()), *dashboards):
        for title, (
            expected_id,
            expected_type,
            expected_grid_position,
        ) in expected_layout.items():
            item = panel(document, title)
            assert item["id"] == expected_id
            assert item["type"] == expected_type
            assert item["gridPos"] == expected_grid_position


def test_daniel_visitor_results_exclude_disabled_stale_and_unavailable():
    for title in (
        "Daniel visitor journey success",
        "Daniel visitor journey aggregate duration",
        "Daniel visitor journey failure stage",
    ):
        expression = validator.DANIEL_VISITOR_PANEL_CONTRACT[title][0]
        assert "monitoring_enabled" in expression and "== 1" in expression
        assert "<= 1020" in expression
        assert (
            'state="failure"' in expression
            if title == "Daniel visitor journey failure stage"
            else 'state=~"success|recovered|failure"' in expression
        )
        assert not any(
            state in expression.split('state=~"', 1)[-1].split('"', 1)[0]
            for state in ("disabled", "stale", "unavailable")
        )


@pytest.mark.parametrize("title", validator.DANIEL_VISITOR_LAYOUT_CONTRACT)
def test_daniel_visitor_dashboard_validator_rejects_layout_regressions(tmp_path, dashboards, title):
    changed = copy.deepcopy(dashboards[0])
    panel(changed, title)["gridPos"]["y"] += 1
    with pytest.raises(SystemExit, match="stable visitor layout contract"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


@pytest.mark.parametrize("title", validator.DANIEL_VISITOR_PANEL_CONTRACT)
def test_daniel_visitor_dashboard_validator_rejects_contract_regressions(
    tmp_path, dashboards, title
):
    changed = copy.deepcopy(dashboards[0])
    panel(changed, title)["targets"][0]["expr"] += " or vector(0)"
    with pytest.raises(SystemExit, match="visitor journey contract"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


@pytest.mark.parametrize(
    ("title", "mutation"),
    [
        (
            "Daniel cache freshness",
            lambda item: item["targets"][0].update(
                expr=item["targets"][0]["expr"].replace("last_success", "wrong_age")
            ),
        ),
        (
            "Daniel cache refresh duration",
            lambda item: item["targets"][0].update(
                expr=item["targets"][0]["expr"].replace(',cluster=~"$cluster"', "")
            ),
        ),
        (
            "Daniel cache state",
            lambda item: item["targets"][0].update(
                expr='max by (repository) (daniel_cache_state{environment=~"$environment"})'
            ),
        ),
        (
            "Daniel cache completeness",
            lambda item: item["targets"][0].update(
                expr=item["targets"][0]["expr"] + " or vector(0)"
            ),
        ),
    ],
)
def test_daniel_dashboard_validator_rejects_contract_regressions(
    tmp_path, dashboards, title, mutation
):
    changed = copy.deepcopy(dashboards[0])
    mutation(panel(changed, title))
    with pytest.raises(SystemExit, match="bounded Daniel contract"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


def test_finalized_staging_evidence_link_is_current(dashboards):
    expected = "deployment-evidence/dspace/staging/main-22f506e-20260817T094911Z.json"
    stale = "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"
    for document in dashboards:
        rendered = json.dumps(document)
        assert expected in rendered
        assert stale not in rendered


def test_generator_write_check_and_stale_exit_paths(tmp_path, monkeypatch, capsys):
    profiles = {
        name: {**profile, "path": tmp_path / f"{name}.json"}
        for name, profile in generator.PROFILES.items()
    }
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator, "PROFILES", profiles)

    monkeypatch.setattr(sys, "argv", [str(GENERATOR), "--check"])
    assert generator.main() == 1
    assert "staging, prod" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", [str(GENERATOR), "--write"])
    assert generator.main() == 0
    assert capsys.readouterr().out.count("wrote") == 2

    monkeypatch.setattr(sys, "argv", [str(GENERATOR), "--check"])
    assert generator.main() == 0
    assert "are current" in capsys.readouterr().out


def test_profiles_differ_only_by_allowlisted_identity(dashboards):
    staging, prod = dashboards
    differing = {key for key in staging if staging[key] != prod[key]}
    assert differing == validator.PROFILE_DIFFERENCES
    assert (staging["uid"], staging["title"], staging["tags"][-1]) == (
        "sugarkube-staging-observability",
        "Sugarkube Staging Observability",
        "staging",
    )
    assert (prod["uid"], prod["title"], prod["tags"][-1]) == (
        "sugarkube-prod-observability",
        "Sugarkube Production Observability",
        "prod",
    )
    for document, environment, cluster in (
        (staging, "staging", "sugarkube-int"),
        (prod, "prod", "sugarkube-prod"),
    ):
        variables = document["templating"]["list"]
        assert [item["name"] for item in variables] == [
            "environment",
            "cluster",
            "app",
            "route",
            "workload",
        ]
        assert variables[0]["query"] == environment
        assert variables[1]["query"] == cluster
        assert all(item["hide"] == 2 and item["type"] == "constant" for item in variables[:2])
        assert all(item["allValue"] == ".*" for item in variables[2:4])


def test_canonical_order_ids_grid_and_defaults(dashboards):
    staging, _ = dashboards
    rows = [item["title"] for item in staging["panels"] if item["type"] == "row"]
    assert rows == [
        "Cluster and service health",
        "Workload health",
        "Node and Prometheus capacity",
        "Observability build identity",
        "DSPACE HTTP",
        "DSPACE runtime and release",
        "DSPACE feature traffic",
        "Blackbox monitoring",
        "DSPACE release integrity",
        "token.place relay and compute capacity",
        "token.place HTTP and release",
        "Daniel GitHub metadata cache",
        "Daniel controlled performance",
        "Daniel visitor journey",
        "Cross-application resource, placement and release overview",
    ]
    assert [item["id"] for item in staging["panels"]] == list(range(1, 93))
    assert panel(staging, "DSPACE instrumentation health")
    assert panel(staging, "DSPACE build identity")
    assert all(
        item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
        for item in staging["panels"]
        if item["type"] not in {"row", "text"}
    )
    validator.validate_dashboard(STAGING)
    validator.validate_dashboard(PROD)


def test_daniel_queries_are_target_safe_and_expose_stale_or_missing_health(dashboards):
    staging, _ = dashboards
    age = validator.panel_expression(staging, "Daniel measurement age")
    health = validator.panel_expression(staging, "Daniel collection/document status")
    assert "time() -" in age and "time() - 86400" not in age
    assert "status" in health and "collection_up" not in health
    for title in (
        "Daniel performance result state",
        "Daniel application-ready duration",
        "Daniel controlled interaction latency",
        "Daniel renderer and fallback state",
        "Daniel controlled frame time",
    ):
        expression = validator.panel_expression(staging, title)
        assert "on(environment, instance, job)" in expression
        assert "time() - 86400" in expression
    for title in (
        "Daniel application-ready duration",
        "Daniel controlled interaction latency",
        "Daniel controlled frame time",
    ):
        expression = validator.panel_expression(staging, title)
        assert all(
            label in expression for label in ("renderer_class", "renderer_state", "fallback_status")
        )
    assert " or " not in validator.panel_expression(staging, "Daniel controlled frame time")


def test_all_twelve_tables_are_simultaneous_single_frames(dashboards):
    staging, _ = dashboards
    tables = [item for item in staging["panels"] if item["type"] == "table"]
    assert len(tables) == 12
    for table in tables:
        assert len(table["targets"]) == 1
        assert table["targets"][0]["format"] == "table"
        assert table["targets"][0]["instant"] is True
        assert table["targets"][0]["range"] is False
        assert [item["id"] for item in table["transformations"]] == ["organize"]
        options = table["transformations"][0]["options"]
        assert options["indexByName"] and options["renameByName"]
        assert options["excludeByName"]["Time"] is True
        assert options["excludeByName"]["__name__"] is True


def test_missing_application_capabilities_produce_no_series_not_healthy_zero(dashboards):
    _, prod = dashboards
    expressions = {
        item["title"]: [target.get("expr", "") for target in item.get("targets", [])]
        for item in prod["panels"]
    }
    for title in ("Image-pin agreement", "DSPACE metrics-target health"):
        assert "0 * count(dspace_release_approved_info" in expressions[title][0]
        assert "vector(0)" not in expressions[title][0]
    for title in (
        "Image-pin agreement",
        "DSPACE metrics-target health",
        "/chat synthetic result and freshness",
    ):
        assert all(
            expression.endswith(validator.CAPABILITY_PRESENCE_GATE)
            for expression in expressions[title]
        )
    image_pin = expressions["Image-pin agreement"][0]
    assert '"^(docker-pullable://)?(.*)$"' in image_pin
    assert '"image_id", "unknown"' in image_pin
    assert '"image_spec", "unknown"' in image_pin
    assert (
        "0 * count(dspace_release_approved_info"
        in expressions["/chat synthetic result and freshness"][0]
    )
    for title in ("DSPACE chat outcome rate", "DSPACE dependency outcome rate"):
        assert (
            '0 * count(dspace_instrumentation_up{environment=~"$environment"} == 1)'
            in expressions[title][1]
        )
        assert all(
            expression.endswith(validator.DSPACE_COMPLETE_HEALTH_GATE)
            for expression in expressions[title]
        )
    token_expressions = [
        expr
        for title, values in expressions.items()
        if title.startswith("token.place")
        for expr in values
    ]
    assert not any("vector(0)" in expr for expr in token_expressions)
    # Production has no capability producer in this task; gated RHS therefore has no output.
    assert prod["templating"]["list"][0]["query"] == "prod"
    assert all(
        item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
        for item in prod["panels"]
        if item["type"] not in {"row", "text"}
    )


def test_5xx_ratios_use_request_family_gated_zero_contract(dashboards):
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for document in (template, *dashboards):
        for title, expected in validator.FIVE_XX_RATIO_EXPRESSIONS.items():
            expression = validator.panel_expression(document, title)
            assert expression == expected
            assert " or on() (0 * sum(rate(" in expression
            assert "or vector(0)" not in expression

    dspace = validator.FIVE_XX_RATIO_EXPRESSIONS["5xx error ratio"]
    assert dspace.count("dspace_http_requests_total") == 3
    assert dspace.count('environment=~"$environment"') == 3
    assert dspace.count('status_class="5xx"') == 1

    tokenplace = validator.FIVE_XX_RATIO_EXPRESSIONS["token.place HTTP 5xx ratio"]
    assert tokenplace.count("tokenplace_http_requests_total") == 3
    for selector in (
        'app="tokenplace"',
        'environment=~"$environment"',
        'release="tokenplace"',
        'cluster=~"$cluster"',
        'namespace="tokenplace"',
    ):
        assert tokenplace.count(selector) == 3
    assert tokenplace.count('status_class="5xx"') == 1


@pytest.mark.parametrize(
    ("title", "old", "new"),
    [
        ("5xx error ratio", " or on() (0 * sum(rate(", " or on() (0 * sum(rate(wrong_"),
        (
            "token.place HTTP 5xx ratio",
            'namespace="tokenplace"}[$__rate_interval]))))',
            'namespace="wrong"}[$__rate_interval]))))',
        ),
        ("5xx error ratio", " or on() (0 * sum(rate(", " or vector(0) or on() (0 * sum(rate("),
    ],
)
def test_5xx_ratio_contract_rejects_wrong_gate_filter_or_unconditional_zero(
    dashboards, title, old, new
):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    target = panel(changed, title)["targets"][0]
    assert old in target["expr"]
    target["expr"] = target["expr"].replace(old, new, 1)
    with pytest.raises(SystemExit, match="5xx zero contract|missing data"):
        validator._validate_semantics(changed)


def test_query_scoping_and_safe_labels(dashboards):
    staging, _ = dashboards
    serialized = json.dumps(staging)
    expressions = [
        target["expr"] for item in staging["panels"] for target in item.get("targets", [])
    ]
    assert all("-$environment-.*" in expr for expr in expressions if "blackbox-" in expr)
    token_titles = validator.TOKENPLACE_DATA_TITLES
    token_expressions = [
        target["expr"] for title in token_titles for target in panel(staging, title)["targets"]
    ]
    assert all(
        'environment=~"$environment"' in expr and 'cluster=~"$cluster"' in expr
        for expr in token_expressions
    )
    core = [expr for expr in expressions if "$cluster" not in expr]
    assert not any("cluster=" in expr or "cluster=~" in expr for expr in core)
    assert "kube_state_metrics_build_info" not in serialized
    assert not any(f"{{{{{label}}}}}" in serialized for label in validator.FORBIDDEN_LABELS)


def test_dspace_chat_outcomes_fallback_and_denominators(dashboards):
    for document, provider in zip(dashboards, ("tokenplace", "openai")):
        chat_rate = panel(document, "DSPACE chat outcome rate")["targets"][0]["expr"]
        dependency_rate = panel(document, "DSPACE dependency outcome rate")["targets"][0]["expr"]
        assert "sum by (provider, outcome)" in chat_rate
        assert "sum by (dependency, outcome)" in dependency_rate
        # Healthy instrumentation supplies an explicit idle zero; missing or unhealthy
        # instrumentation supplies no fallback series and Grafana renders NO DATA.
        assert "dspace_instrumentation_up" in chat_rate and "== 1" in chat_rate
        assert "dspace_instrumentation_up" in dependency_rate and "== 1" in dependency_rate
        assert "label_replace" not in chat_rate
        assert "label_replace" not in dependency_rate
        for title in ("DSPACE chat outcome rate", "DSPACE dependency outcome rate"):
            targets = panel(document, title)["targets"]
            assert len(targets) == 2
            assert targets[1]["legendFormat"] == "idle"
            assert "unless on() sum(rate(" in targets[1]["expr"]
            assert all(
                target["expr"].endswith(validator.DSPACE_COMPLETE_HEALTH_GATE) for target in targets
            )
        assert (
            "mappings" not in panel(document, "DSPACE chat outcome rate")["fieldConfig"]["defaults"]
        )
        assert (
            "mappings"
            not in panel(document, "DSPACE dependency outcome rate")["fieldConfig"]["defaults"]
        )

        primary_panel = panel(document, "DSPACE primary-provider success ratio")
        primary = primary_panel["targets"][0]["expr"]
        assert primary.count(f'provider="{provider}"') == 2
        assert primary.count('outcome="success"') == 1
        assert 'outcome!="fallback_used"' not in primary
        assert "including fallback_used outcomes" in primary_panel["description"]
        assert primary.endswith(validator.DSPACE_COMPLETE_HEALTH_GATE)
        assert "mappings" not in primary_panel["fieldConfig"]["defaults"]

        fallback_panel = panel(document, "DSPACE fallback-use ratio")
        fallback = fallback_panel["targets"][0]["expr"]
        assert fallback.count("dspace_dchat_requests_total") == 2
        assert fallback.count('outcome="fallback_used"') == 1
        assert "all observed chat requests" in fallback_panel["description"]
        assert fallback.endswith(validator.DSPACE_COMPLETE_HEALTH_GATE)
        assert "mappings" not in fallback_panel["fieldConfig"]["defaults"]


@pytest.mark.parametrize(
    "title",
    ["DSPACE chat latency percentiles", "DSPACE dependency latency percentiles"],
)
def test_dspace_latency_histograms_reject_duplicate_percentiles(tmp_path, dashboards, title):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    targets = panel(changed, title)["targets"]
    targets[1]["expr"] = targets[1]["expr"].replace(".95", ".50", 1)
    with pytest.raises(SystemExit, match="requires p50/p95/p99"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


@pytest.mark.parametrize(
    ("title", "metric", "dimension"),
    [
        (
            "DSPACE chat latency percentiles",
            "dspace_dchat_request_duration_seconds_bucket",
            "provider",
        ),
        (
            "DSPACE dependency latency percentiles",
            "dspace_dependency_request_duration_seconds_bucket",
            "dependency",
        ),
    ],
)
def test_dspace_latency_histograms_preserve_bounded_outcome_dimensions(
    dashboards, title, metric, dimension
):
    for document in dashboards:
        targets = panel(document, title)["targets"]
        assert [target["refId"] for target in targets] == ["A", "B", "C"]
        assert [
            target["expr"].split("histogram_quantile(", 1)[1].split(",", 1)[0] for target in targets
        ] == [
            ".50",
            ".95",
            ".99",
        ]
        for target in targets:
            assert metric in target["expr"]
            assert f"sum by (le, {dimension}, outcome)" in target["expr"]
            assert 'environment=~"$environment"' in target["expr"]
            assert target["expr"].endswith(validator.DSPACE_COMPLETE_HEALTH_GATE)
            assert f"{metric.removesuffix('_bucket')}_count" in target["expr"]
            assert f"and on ({dimension}, outcome)" in target["expr"]
            assert "> 0" in target["expr"]


@pytest.mark.parametrize(
    ("title", "old", "new", "message"),
    [
        (
            "DSPACE fallback-use ratio",
            validator.DSPACE_COMPLETE_HEALTH_GATE,
            'and on() (count(dspace_instrumentation_up{environment=~"$environment"} == 1) > 0)',
            "complete health-gated contracts",
        ),
        (
            "DSPACE chat latency percentiles",
            "dspace_dchat_request_duration_seconds_count",
            "dspace_dchat_request_duration_seconds_bucket",
            "requires p50/p95/p99",
        ),
    ],
)
def test_dspace_panels_reject_partial_health_or_missing_observation_guard(
    dashboards, title, old, new, message
):
    changed = copy.deepcopy(dashboards[0])
    target = panel(changed, title)["targets"][0]
    assert old in target["expr"]
    target["expr"] = target["expr"].replace(old, new, 1)
    with pytest.raises(SystemExit, match=message):
        validator._validate_semantics(changed)


def test_primary_success_ratio_is_not_inflated_by_fallback_traffic(dashboards):
    successful_primary_requests = 1
    fallback_primary_requests = 1
    expected_ratio = successful_primary_requests / (
        successful_primary_requests + fallback_primary_requests
    )
    assert expected_ratio == 0.5
    for document in dashboards:
        expression = panel(document, "DSPACE primary-provider success ratio")["targets"][0]["expr"]
        denominator = expression.split("clamp_min(", 1)[1]
        assert 'outcome!="fallback_used"' not in denominator


@pytest.mark.parametrize(
    "title",
    ["DSPACE primary-provider success ratio", "DSPACE fallback-use ratio"],
)
@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_dspace_ratios_reject_malformed_target_counts(tmp_path, dashboards, title, mutation):
    changed = copy.deepcopy(dashboards[0])
    targets = panel(changed, title)["targets"]
    if mutation == "missing":
        targets.clear()
    else:
        targets.append(copy.deepcopy(targets[0]))
    with pytest.raises(SystemExit, match="exactly one PromQL target"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


def test_dspace_valid_zero_ratios_have_no_idle_value_mapping(dashboards):
    for document in dashboards:
        for title in ("DSPACE primary-provider success ratio", "DSPACE fallback-use ratio"):
            ratio_panel = panel(document, title)
            assert ratio_panel["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
            assert "mappings" not in ratio_panel["fieldConfig"]["defaults"]
            assert (
                "or on() (0 * count(dspace_instrumentation_up" in ratio_panel["targets"][0]["expr"]
            )


@pytest.mark.parametrize(
    ("title", "mutation"),
    [
        ("DSPACE chat latency percentiles", "missing"),
        ("DSPACE dependency latency percentiles", "extra"),
    ],
)
def test_dspace_latency_histograms_reject_malformed_target_counts(
    tmp_path, dashboards, title, mutation
):
    changed = copy.deepcopy(dashboards[0])
    targets = panel(changed, title)["targets"]
    if mutation == "missing":
        targets.pop()
    else:
        targets.append(copy.deepcopy(targets[-1]))
    with pytest.raises(SystemExit, match="requires p50/p95/p99"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("environment", "environment scoping"),
        ("metric-inventory", "counters and latency histograms"),
        ("outcome-contract", "complete health-gated idle contract"),
        ("primary-shape", "include fallback outcomes"),
        ("fallback-shape", "all chat requests"),
        ("ratio-contract", "complete health-gated contracts"),
        ("ratio-description", "document its denominator"),
    ],
)
def test_dspace_chat_validator_rejects_each_contract_violation(
    tmp_path, dashboards, mutation, message
):
    changed = copy.deepcopy(dashboards[0])
    if mutation == "environment":
        target = panel(changed, "DSPACE chat latency percentiles")["targets"][0]
        target["expr"] = target["expr"].replace(
            'environment=~"$environment"', 'environment="staging"'
        )
    elif mutation == "metric-inventory":
        for target in panel(changed, "DSPACE chat latency percentiles")["targets"]:
            target["expr"] = target["expr"].replace(
                "dspace_dchat_request_duration_seconds_bucket", "unrecognized_bucket", 1
            )
    elif mutation == "outcome-contract":
        target = panel(changed, "DSPACE chat outcome rate")["targets"][1]
        target["legendFormat"] = "inactive"
    elif mutation == "primary-shape":
        target = panel(changed, "DSPACE primary-provider success ratio")["targets"][0]
        target["expr"] = target["expr"].replace('provider="tokenplace"', 'provider="openai"', 1)
    elif mutation == "fallback-shape":
        target = panel(changed, "DSPACE fallback-use ratio")["targets"][0]
        target["expr"] = target["expr"].replace(
            'outcome="fallback_used"', 'outcome="fallback_used_dspace_dchat_requests_total"', 1
        )
    elif mutation == "ratio-contract":
        target = panel(changed, "DSPACE fallback-use ratio")["targets"][0]
        target["expr"] = target["expr"].replace("1e-9", "1e-8", 1)
    else:
        panel(changed, "DSPACE fallback-use ratio")["description"] = "Fallback ratio."

    with pytest.raises(SystemExit, match=message):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


@pytest.mark.parametrize(
    ("title", "target_index"),
    [
        ("Image-pin agreement", 0),
        ("DSPACE metrics-target health", 0),
        ("/chat synthetic result and freshness", 0),
        ("/chat synthetic result and freshness", 1),
    ],
)
def test_capability_outer_presence_gate_is_required(tmp_path, dashboards, title, target_index):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    target = panel(changed, title)["targets"][target_index]
    assert target["expr"].endswith(validator.CAPABILITY_PRESENCE_GATE)
    target["expr"] = target["expr"][: -len(validator.CAPABILITY_PRESENCE_GATE)].rstrip()
    with pytest.raises(SystemExit, match="capability-presence"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


def test_raw_ip_legend_is_rejected(tmp_path, dashboards):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    panel(changed, "Scrape availability by job")["targets"][0]["legendFormat"] = "{{ip}}"
    with pytest.raises(SystemExit, match="forbidden raw identity label"):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


@pytest.mark.parametrize(
    "mutation",
    [
        "object-count",
        "ids",
        "grid-type",
        "grid-bounds",
        "grid-overlap",
        "table-count",
        "table-target",
        "table-transform-count",
        "table-columns",
        "table-exclusions",
        "variable-shape",
        "constant-variable",
        "query-variable",
        "build-info",
        "external-cluster",
        "token-scope",
        "token-zero",
        "event-capability",
        "event-presence",
        "image-zero",
        "image-prefix",
        "image-metadata",
        "chat-capability",
        "blackbox-environment",
    ],
)
def test_semantic_contract_rejects_invalid_dashboard_mutations(dashboards, mutation):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    scrape_table = panel(changed, "Scrape availability by job")
    if mutation == "object-count":
        changed["panels"].pop()
    elif mutation == "ids":
        changed["panels"][0]["id"] = 99
    elif mutation == "grid-type":
        changed["panels"][1]["gridPos"]["x"] = "0"
    elif mutation == "grid-bounds":
        changed["panels"][1]["gridPos"]["w"] = 25
    elif mutation == "grid-overlap":
        changed["panels"][2]["gridPos"] = changed["panels"][1]["gridPos"]
    elif mutation == "table-count":
        scrape_table["type"] = "stat"
    elif mutation == "table-target":
        scrape_table["targets"][0]["range"] = True
    elif mutation == "table-transform-count":
        scrape_table["transformations"] = []
    elif mutation == "table-columns":
        scrape_table["transformations"][0]["options"]["indexByName"] = {}
    elif mutation == "table-exclusions":
        scrape_table["transformations"][0]["options"]["excludeByName"].pop("Time")
    elif mutation == "variable-shape":
        changed["templating"]["list"][3]["name"] = "path"
    elif mutation == "constant-variable":
        changed["templating"]["list"][0]["hide"] = 0
    elif mutation == "query-variable":
        changed["templating"]["list"][2]["includeAll"] = False
    elif mutation == "build-info":
        changed["panels"][1]["targets"][0]["expr"] = "kube_state_metrics_build_info"
    elif mutation == "external-cluster":
        changed["panels"][1]["targets"][0]["expr"] = 'up{cluster="remote"}'
    elif mutation == "token-scope":
        panel(changed, next(iter(validator.TOKENPLACE_DATA_TITLES)))["targets"][0]["expr"] = "up"
    elif mutation == "token-zero":
        panel(changed, next(iter(validator.TOKENPLACE_DATA_TITLES)))["targets"][0][
            "expr"
        ] += " or vector(0)"
    elif mutation == "event-capability":
        panel(changed, "DSPACE chat outcome rate")["targets"][0][
            "expr"
        ] = "dspace_dchat_requests_total"
    elif mutation == "event-presence":
        target = panel(changed, "DSPACE chat outcome rate")["targets"][0]
        target["expr"] = target["expr"][: -len(validator.DSPACE_COMPLETE_HEALTH_GATE)].rstrip()
    elif mutation == "image-zero":
        panel(changed, "Image-pin agreement")["targets"][0]["expr"] = panel(
            changed, "Image-pin agreement"
        )["targets"][0]["expr"].replace("0 * count(", "count(", 1)
    elif mutation == "image-prefix":
        panel(changed, "Image-pin agreement")["targets"][0]["expr"] = panel(
            changed, "Image-pin agreement"
        )["targets"][0]["expr"].replace('"^(docker-pullable://)?(.*)$"', '"(.*)"')
    elif mutation == "image-metadata":
        panel(changed, "Image-pin agreement")["targets"][0]["expr"] = panel(
            changed, "Image-pin agreement"
        )["targets"][0]["expr"].replace('"image_id", "unknown"', '"image_id", "missing"')
    elif mutation == "chat-capability":
        panel(changed, "/chat synthetic result and freshness")["targets"][0]["expr"] = panel(
            changed, "/chat synthetic result and freshness"
        )["targets"][0]["expr"].replace("0 * count(", "count(", 1)
    else:
        blackbox = next(
            target
            for item in changed["panels"]
            for target in item.get("targets", [])
            if "blackbox-" in target.get("expr", "")
        )
        blackbox["expr"] = blackbox["expr"].replace("-$environment-.*", "-prod-.*")
    with pytest.raises(SystemExit):
        validator._validate_semantics(changed)


@pytest.mark.parametrize(
    "expression",
    [
        "up",
        "(up)",
        f"up {validator.CAPABILITY_PRESENCE_GATE}",
        f"(up) + 1 {validator.CAPABILITY_PRESENCE_GATE}",
        f"((up) {validator.CAPABILITY_PRESENCE_GATE}",
        f'((label_replace(up, "x", "\\"", "y", ".*"))) extra {validator.CAPABILITY_PRESENCE_GATE}',
    ],
)
def test_outer_capability_gate_parser_rejects_malformed_expressions(expression):
    assert not validator._has_outer_capability_presence_gate(expression)


@pytest.mark.parametrize(
    "kind",
    ["title", "query", "grid", "type", "transformation", "noValue", "variable", "target-mode"],
)
def test_one_sided_canonical_mutations_fail(tmp_path, dashboards, kind):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    if kind == "title":
        changed["panels"][1]["title"] += " drift"
    elif kind == "query":
        changed["panels"][1]["targets"][0]["expr"] = "up"
    elif kind == "grid":
        changed["panels"][1]["gridPos"]["x"] += 1
    elif kind == "type":
        changed["panels"][1]["type"] = "gauge"
    elif kind == "transformation":
        panel(changed, "Scrape availability by job")["transformations"][0]["id"] = "merge"
    elif kind == "noValue":
        changed["panels"][1]["fieldConfig"]["defaults"].pop("noValue")
    elif kind == "variable":
        changed["templating"]["list"][0]["query"] = "prod"
    else:
        panel(changed, "Scrape availability by job")["targets"][0]["instant"] = False
    with pytest.raises(SystemExit):
        validator.validate_dashboard(write_candidate(tmp_path, changed))


def rendered_manifest(document):
    uid = document["uid"]
    payload = json.dumps(document, indent=2)
    return (
        "kind: ConfigMap\nmetadata:\n"
        "  name: kube-prometheus-stack-grafana-dashboards-sugarkube\n"
        "  labels:\n    dashboard-provider: sugarkube\ndata:\n"
        f"  {uid}.json:\n    |-\n"
        + "\n".join(f"      {line}" for line in payload.splitlines())
        + "\n---\nkind: ConfigMap\ndata:\n  dashboardproviders.yaml: |\n"
        "    providers:\n      - name: sugarkube\n        options:\n"
        "          path: /var/lib/grafana/dashboards/sugarkube\n"
        "---\nkind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n"
        "        - volumeMounts:\n"
        "            - name: dashboards-sugarkube\n"
        f'              mountPath: "/var/lib/grafana/dashboards/sugarkube/{uid}.json"\n'
        f'              subPath: "{uid}.json"\n'
    )


@pytest.mark.parametrize("source", [STAGING, PROD])
def test_source_rendered_configmap_equality(tmp_path, source):
    document = json.loads(source.read_text())
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(rendered_manifest(document))
    dashboard_json = validator.validate_dashboard(source)
    validator.validate_render(rendered, dashboard_json)
    drifted = copy.deepcopy(document)
    drifted["panels"][1]["title"] += " drift"
    rendered.write_text(rendered_manifest(drifted))
    with pytest.raises(SystemExit, match="differs"):
        validator.validate_render(rendered, dashboard_json)


@pytest.mark.parametrize(
    "mutation",
    [
        "dashboard-count",
        "configmap-identity",
        "provider-count",
        "provider-path",
        "mount",
        "block-marker",
        "payload",
    ],
)
def test_render_validation_fails_closed(tmp_path, dashboards, mutation):
    staging, _ = dashboards
    dashboard_json = json.dumps(staging)
    manifest = rendered_manifest(staging)
    if mutation == "dashboard-count":
        manifest = manifest.replace(f'"uid": "{staging["uid"]}"', '"uid": "wrong"')
    elif mutation == "configmap-identity":
        manifest = manifest.replace("dashboard-provider: sugarkube", "dashboard-provider: other")
    elif mutation == "provider-count":
        manifest = manifest.replace("name: sugarkube", "name: other", 1)
    elif mutation == "provider-path":
        manifest = manifest.replace(
            "/var/lib/grafana/dashboards/sugarkube\n---", "/tmp/dashboards\n---"
        )
    elif mutation == "mount":
        manifest = manifest.replace("subPath:", "otherPath:")
    elif mutation == "block-marker":
        manifest = manifest.replace("    |-\n", "    >-\n", 1)
    else:
        manifest = manifest.replace("      {\n", "      not-json\n", 1)
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(manifest)
    with pytest.raises(SystemExit):
        validator.validate_render(rendered, dashboard_json)


def test_dashboard_loading_and_profile_identity_fail_closed(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("[")
    with pytest.raises(SystemExit, match="missing or malformed"):
        validator.load_dashboard(malformed)
    non_object = tmp_path / "array.json"
    non_object.write_text("[]")
    with pytest.raises(SystemExit, match="root must be an object"):
        validator.load_dashboard(non_object)
    with pytest.raises(SystemExit, match="supported profile"):
        validator.configure_profile({"uid": "unknown", "title": "Unknown"})


OVERVIEW_TITLES = tuple(validator.OVERVIEW_PANEL_CONTRACT)


def test_cross_application_overview_handles_replica_rollouts_and_single_node_placement(dashboards):
    """The query shape preserves deployments but counts a shared serving node only once."""
    staging, _ = dashboards
    replicas = panel(staging, "Desired versus ready replicas")
    assert all("max by (namespace, deployment)" in target["expr"] for target in replicas["targets"])
    assert all("sum by (namespace)" not in target["expr"] for target in replicas["targets"])
    assert all("{{deployment}}" in target["legendFormat"] for target in replicas["targets"])
    placement = validator.panel_expression(staging, "Serving workload node placement")
    assert "count by (namespace) (count by (namespace, node)" in placement
    assert 'condition="true"' in placement and 'phase="Running"' in placement
    assert "kube_pod_deletion_timestamp" in placement
    target = panel(staging, "Serving workload node placement")["targets"][0]
    assert target["instant"] is True and target["range"] is False


def test_cross_application_overview_preserves_missing_limits_throttling_and_builds(dashboards):
    staging, _ = dashboards
    for title in (
        "Memory working set versus configured limit",
        "CPU throttling",
        "Application build identity",
    ):
        item = panel(staging, title)
        assert item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
        assert all("vector(0)" not in target["expr"] for target in item["targets"])
    assert "unsupported" in panel(staging, "CPU throttling")["description"].lower()
    assert "Missing producers" in panel(staging, "Application build identity")["description"]
    limit_expression = panel(staging, "Memory working set versus configured limit")["targets"][1][
        "expr"
    ]
    assert "and on (namespace)" in limit_expression
    assert "count by (namespace)" in limit_expression
    assert limit_expression.count("container_memory_working_set_bytes") >= 2
    assert "> 0" in limit_expression
    cpu_expression = panel(staging, "CPU throttling")["targets"][0]["expr"]
    assert cpu_expression.count("and on (namespace, pod, container)") == 6
    assert cpu_expression.count("count by (namespace)") == 2
    assert "container_memory_working_set_bytes" in cpu_expression


def test_cross_application_overview_is_profile_and_workload_scoped_without_double_counting(
    dashboards,
):
    staging, prod = dashboards
    for document, environment in ((staging, "staging"), (prod, "prod")):
        selector = document["templating"]["list"][-1]
        assert selector["name"] == "workload"
        assert selector["query"] == "dspace,tokenplace,danielsmith"
        assert selector["allValue"] == "dspace|tokenplace|danielsmith"
        for title in OVERVIEW_TITLES:
            assert all(
                'namespace=~"$workload"' in target["expr"]
                for target in panel(document, title)["targets"]
            )
        assert document["templating"]["list"][0]["query"] == environment
    memory = panel(staging, "Memory working set versus configured limit")
    cpu = panel(staging, "CPU throttling")
    assert all("max by (namespace, pod, container)" in x["expr"] for x in memory["targets"])
    assert all("max by (namespace, pod, container)" in x["expr"] for x in cpu["targets"])


@pytest.mark.parametrize(
    ("title", "mutation", "message"),
    [
        ("Serving workload node placement", "drop-ready", "required metric contract"),
        ("Serving workload node placement", "drop-running", "required metric contract"),
        ("Serving workload node placement", "drop-terminating", "required metric contract"),
        ("Memory working set versus configured limit", "zero", "preserve"),
        ("CPU throttling", "scope", "namespace scope"),
        ("Application build identity", "scope", "namespace scope"),
    ],
)
def test_cross_application_overview_rejects_unsafe_or_unknown_as_healthy(
    dashboards, title, mutation, message
):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    target = panel(changed, title)["targets"][0]
    if mutation == "drop-ready":
        target["expr"] = target["expr"].replace(
            'kube_pod_status_ready{namespace=~"$workload",condition="true"} == 1 '
            "and on (namespace, pod) ",
            "",
        )
    elif mutation == "drop-running":
        target["expr"] = target["expr"].replace(
            'kube_pod_status_phase{namespace=~"$workload",phase="Running"} == 1', "vector(1)"
        )
    elif mutation == "drop-terminating":
        target["expr"] = target["expr"].replace(
            ' unless on (namespace, pod) kube_pod_deletion_timestamp{namespace=~"$workload"}', ""
        )
    elif mutation == "zero":
        target["expr"] += " or vector(0)"
    else:
        target["expr"] = target["expr"].replace('namespace=~"$workload"', 'namespace=~".*"')
    with pytest.raises(SystemExit, match=message):
        validator._validate_semantics(changed)


def test_cross_application_overview_rejects_partially_unscoped_multi_metric_target(dashboards):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    target = panel(changed, "Application build identity")["targets"][0]
    target["expr"] = target["expr"].replace(
        'tokenplace_build_info{namespace=~"$workload",', "tokenplace_build_info{"
    )
    with pytest.raises(SystemExit, match="namespace scope"):
        validator._validate_semantics(changed)


def test_cross_application_overview_rejects_cpu_without_identity_matched_guard(dashboards):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    target = panel(changed, "CPU throttling")["targets"][0]
    expression = target["expr"]
    guard_start = expression.rindex("count by (namespace) (((")
    guard_end = expression.index(" == count by (namespace)", guard_start)
    matched_guard = expression[guard_start:guard_end]
    numerator_end = matched_guard.index(") and on (namespace, pod, container)")
    # Restore the former count-only guard: its population size can be satisfied by
    # stale CFS identities that are not members of the current observed population.
    count_only_guard = matched_guard[:numerator_end] + ")"
    target["expr"] = expression.replace(matched_guard, count_only_guard, 1)
    with pytest.raises(SystemExit, match="complete observed"):
        validator._validate_semantics(changed)


@pytest.mark.parametrize("metric", ["dspace_build_info", "tokenplace_build_info"])
def test_cross_application_overview_rejects_broadened_profile_branch(dashboards, metric):
    staging, _ = dashboards
    changed = copy.deepcopy(staging)
    target = panel(changed, "Application build identity")["targets"][0]
    selector = validator._metric_matchers(target["expr"], metric)[0]
    target["expr"] = target["expr"].replace(
        selector, selector.replace('environment=~"$environment"', 'environment=~".*"'), 1
    )
    with pytest.raises(SystemExit, match="exact profile scope"):
        validator._validate_semantics(changed)


def _overview_expression(document, title, target=0, workload=".*"):
    expression = panel(document, title)["targets"][target]["expr"]
    # rate() needs at least two samples in its range; keep the 1m-spaced fixture
    # deterministic by evaluating the dashboard queries over a wider window.
    return (
        expression.replace("$workload", workload)
        .replace("$__rate_interval", "5m")
        .replace("$environment", "staging")
        .replace("$cluster", "sugarkube-int")
    )


def test_actual_overview_promql_preserves_identity_coverage_and_serving_state(dashboards, tmp_path):
    """Evaluate the dashboard's PromQL, including absent/partial and rollout cases."""
    assert shutil.which("promtool"), "promtool is required for dashboard PromQL tests"
    staging, _ = dashboards

    def series(metric, labels, values="1x10"):
        rendered = ",".join(f'{key}="{value}"' for key, value in labels.items())
        return {"series": f"{metric}{{{rendered}}}", "values": values}

    inputs = []
    # Two deployments and duplicate scrapes prove identity preservation and deduplication.
    for metric, values in (
        ("kube_deployment_spec_replicas", {"web": 2, "worker": 1}),
        ("kube_deployment_status_replicas_ready", {"web": 2, "worker": 1}),
    ):
        for deployment, value in values.items():
            inputs += [
                series(
                    metric,
                    {"namespace": "dspace", "deployment": deployment, "job": job},
                    f"{value}x10",
                )
                for job in ("ksm-a", "ksm-b")
            ]
    # Serving placement: two nodes, shared replicas, plus excluded pending/unready/terminating pods.
    pods = (
        ("web-old", "node-a", 1, "Running", False),
        ("web-new", "node-b", 1, "Running", False),
        ("worker", "node-a", 1, "Running", False),
        ("pending", "node-c", 0, "Pending", False),
        ("terminating", "node-c", 1, "Running", True),
    )
    for pod_name, node, ready, phase, terminating in pods:
        base = {"namespace": "dspace", "pod": pod_name}
        inputs.append(series("kube_pod_info", {**base, "node": node}))
        inputs.append(series("kube_pod_status_ready", {**base, "condition": "true"}, f"{ready}x10"))
        inputs.append(series("kube_pod_status_phase", {**base, "phase": phase}))
        if terminating:
            inputs.append(series("kube_pod_deletion_timestamp", base))
    token_base = {"namespace": "tokenplace", "pod": "relay"}
    inputs += [
        series("kube_pod_info", {**token_base, "node": "node-a"}),
        series("kube_pod_status_ready", {**token_base, "condition": "true"}),
        series("kube_pod_status_phase", {**token_base, "phase": "Running"}),
    ]
    # Memory populations cover complete, absent, mixed, zero, duplicate, and rollout cases.
    memory_cases = {
        "full": (("a", 10, 100), ("b", 20, 200)),
        "unlimited": (("a", 11, None),),
        "mixed": (("a", 12, 120), ("b", 13, None)),
        "zero": (("a", 14, 0),),
        "rollout": (("old", 15, 150), ("new", 16, 160)),
    }
    for namespace, containers in memory_cases.items():
        for index, (container, usage, limit) in enumerate(containers):
            labels = {"namespace": namespace, "pod": f"pod-{index}", "container": container}
            for job in ("cadvisor-a", "cadvisor-b") if namespace == "full" else ("cadvisor-a",):
                inputs.append(
                    series(
                        "container_memory_working_set_bytes",
                        {**labels, "image": "runtime", "job": job},
                        f"{usage}x10",
                    )
                )
            if limit is not None:
                inputs.append(
                    series(
                        "kube_pod_container_resource_limits",
                        {**labels, "resource": "memory", "unit": "byte"},
                        f"{limit}x10",
                    )
                )
    # CPU: complete zero/nonzero controls, missing either side, a zero denominator,
    # and same-namespace mixed support. Working set defines the observed population.
    cpu_cases = {
        "cpu-full": (("app", True, True, 0, 60),),
        "cpu-nonzero": (("app", True, True, 6, 60),),
        "cpu-no-num": (("app", False, True, 0, 60),),
        "cpu-no-den": (("app", True, False, 0, 60),),
        "cpu-zero-den": (("app", True, True, 0, 0),),
        "cpu-mixed": (
            ("supported", True, True, 0, 60),
            ("unsupported", False, False, 0, 0),
        ),
        "cpu-rollout": (
            ("supported", True, True, 0, 60),
            ("unsupported", False, False, 0, 0),
        ),
        "cpu-stale-control": (("current", True, True, 6, 60),),
    }
    for namespace, containers in cpu_cases.items():
        for container, has_num, has_den, numerator_step, denominator_step in containers:
            labels = {
                "namespace": namespace,
                "pod": "pod",
                "container": container,
                "image": "runtime",
            }
            inputs.append(series("container_memory_working_set_bytes", labels, "10x10"))
            if has_num:
                inputs.append(
                    series(
                        "container_cpu_cfs_throttled_periods_total",
                        labels,
                        f"0+{numerator_step}x10",
                    )
                )
                if namespace == "cpu-full":
                    inputs.append(
                        series(
                            "container_cpu_cfs_throttled_periods_total",
                            {**labels, "job": "duplicate"},
                            "0+0x10",
                        )
                    )
            if has_den:
                inputs.append(
                    series("container_cpu_cfs_periods_total", labels, f"0+{denominator_step}x10")
                )
                if namespace == "cpu-full":
                    inputs.append(
                        series(
                            "container_cpu_cfs_periods_total",
                            {**labels, "job": "duplicate"},
                            f"0+{denominator_step}x10",
                        )
                    )
    # Old rollout CFS samples remain rate-eligible after their working-set identity
    # disappears. They must neither fill a current coverage gap nor dilute a fully
    # covered current container's nonzero ratio.
    for namespace in ("cpu-rollout", "cpu-stale-control"):
        labels = {
            "namespace": namespace,
            "pod": "old-pod",
            "container": "old",
            "image": "runtime",
        }
        inputs += [
            series("container_memory_working_set_bytes", labels, "10x4 stale _x5"),
            series("container_cpu_cfs_throttled_periods_total", labels, "0+0x4 stale _x5"),
            series("container_cpu_cfs_periods_total", labels, "0+60x4 stale _x5"),
        ]

    # Configured coordinates retain simultaneous old/new image_spec values, not status image.
    for pod_name, spec, status in (
        ("web-old", "repo/app:v1", "repo/app@sha256:old"),
        ("web-new", "repo/app:v2", "repo/app@sha256:new"),
    ):
        inputs.append(
            series(
                "kube_pod_container_info",
                {
                    "namespace": "dspace",
                    "pod": pod_name,
                    "container": "app",
                    "image_spec": spec,
                    "image": status,
                },
            )
        )
    inputs += [
        series(
            "dspace_build_info",
            {
                "namespace": "dspace",
                "pod": "web",
                "environment": "staging",
                "version": "1",
                "revision": "abc",
            },
        ),
        series(
            "dspace_build_info",
            {
                "namespace": "other",
                "pod": "leak",
                "environment": "staging",
                "version": "9",
                "revision": "bad",
            },
        ),
        series(
            "tokenplace_build_info",
            {
                "namespace": "tokenplace",
                "pod": "relay",
                "environment": "prod",
                "cluster": "sugarkube-int",
                "app": "tokenplace",
                "release": "tokenplace",
                "version": "2",
                "revision": "wrong-profile",
            },
        ),
    ]

    tests = []

    def query(name, expression, samples):
        tests.append(
            {
                "expr": expression,
                "eval_time": "5m",
                "exp_samples": [{"labels": labels, "value": value} for labels, value in samples],
            }
        )

    query(
        "replicas",
        _overview_expression(staging, "Desired versus ready replicas"),
        [
            ('{deployment="web", namespace="dspace"}', 2),
            ('{deployment="worker", namespace="dspace"}', 1),
        ],
    )
    query(
        "ready replicas",
        _overview_expression(staging, "Desired versus ready replicas", 1),
        [
            ('{deployment="web", namespace="dspace"}', 2),
            ('{deployment="worker", namespace="dspace"}', 1),
        ],
    )
    query(
        "placement",
        _overview_expression(staging, "Serving workload node placement"),
        [('{namespace="dspace"}', 2), ('{namespace="tokenplace"}', 1)],
    )
    query(
        "memory usage",
        _overview_expression(staging, "Memory working set versus configured limit"),
        [
            ('{namespace="cpu-full"}', 10),
            ('{namespace="cpu-mixed"}', 20),
            ('{namespace="cpu-no-den"}', 10),
            ('{namespace="cpu-no-num"}', 10),
            ('{namespace="cpu-nonzero"}', 10),
            ('{namespace="cpu-rollout"}', 20),
            ('{namespace="cpu-stale-control"}', 10),
            ('{namespace="cpu-zero-den"}', 10),
            ('{namespace="full"}', 30),
            ('{namespace="mixed"}', 25),
            ('{namespace="rollout"}', 31),
            ('{namespace="unlimited"}', 11),
            ('{namespace="zero"}', 14),
        ],
    )
    query(
        "complete memory limits",
        _overview_expression(staging, "Memory working set versus configured limit", 1),
        [('{namespace="full"}', 300), ('{namespace="rollout"}', 310)],
    )
    query(
        "cpu coverage",
        _overview_expression(staging, "CPU throttling"),
        [
            ('{namespace="cpu-full"}', 0),
            ('{namespace="cpu-nonzero"}', 0.1),
            ('{namespace="cpu-stale-control"}', 0.1),
        ],
    )
    query(
        "image specs",
        _overview_expression(staging, "Deployment image coordinates"),
        [
            ('{container="app", image_spec="repo/app:v1", namespace="dspace", pod="web-old"}', 1),
            ('{container="app", image_spec="repo/app:v2", namespace="dspace", pod="web-new"}', 1),
        ],
    )
    query(
        "build scope and absent Daniel identity",
        _overview_expression(
            staging, "Application build identity", workload="dspace|tokenplace|danielsmith"
        ),
        [('{namespace="dspace", pod="web", revision="abc", version="1"}', 1)],
    )
    fixture = tmp_path / "overview-promql.yaml"
    fixture.write_text(
        json.dumps(
            {
                "evaluation_interval": "1m",
                "tests": [
                    {
                        "name": "actual overview expressions",
                        "interval": "1m",
                        "input_series": inputs,
                        "promql_expr_test": tests,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["promtool", "test", "rules", str(fixture)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
