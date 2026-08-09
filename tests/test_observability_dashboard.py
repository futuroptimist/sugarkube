"""Contracts for the generated, shared Sugarkube observability dashboard."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import generate_observability_dashboards as generator  # noqa: E402
from scripts import validate_observability_dashboard as validator  # noqa: E402

STAGING = generator.PROFILES["staging"]["path"]
PROD = generator.PROFILES["prod"]["path"]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def panel(document, title):
    return next(item for item in document["panels"] if item["title"] == title)


def expressions(document, title):
    return [target["expr"] for target in panel(document, title).get("targets", [])]


def write_mutation(tmp_path, document):
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def test_generated_artifacts_are_current_and_valid():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_observability_dashboards.py"), "--check"],
        cwd=ROOT,
        check=True,
    )
    validator.validate_dashboard(STAGING)
    validator.validate_dashboard(PROD)


def test_profiles_share_exact_canonical_panels():
    staging, prod = load(STAGING), load(PROD)
    assert staging["panels"] == prod["panels"]
    assert len(staging["panels"]) == 60
    assert sum(item["type"] == "row" for item in staging["panels"]) == 11
    assert [
        item["title"] for item in staging["panels"] if item["type"] == "row"
    ] == validator.ROW_TITLES


def test_only_allowlisted_profile_fields_differ():
    staging, prod = load(STAGING), load(PROD)
    assert staging["uid"] == "sugarkube-staging-observability"
    assert prod["uid"] == "sugarkube-prod-observability"
    assert staging["title"] == "Sugarkube Staging Observability"
    assert prod["title"] == "Sugarkube Production Observability"
    assert staging["tags"][-1] == "staging"
    assert prod["tags"][-1] == "prod"
    for document, environment, cluster in (
        (staging, "staging", "sugarkube-int"),
        (prod, "prod", "sugarkube-prod"),
    ):
        variables = document["templating"]["list"]
        assert [(item["name"], item["type"]) for item in variables] == [
            ("environment", "constant"),
            ("cluster", "constant"),
            ("app", "query"),
            ("route", "query"),
        ]
        assert variables[0]["query"] == environment
        assert variables[1]["query"] == cluster
        assert variables[2]["allValue"] == variables[3]["allValue"] == ".*"
    normalized_staging = copy.deepcopy(staging)
    normalized_prod = copy.deepcopy(prod)
    for document in (normalized_staging, normalized_prod):
        document["uid"] = document["title"] = document["tags"][-1] = "PROFILE"
        for variable in document["templating"]["list"][:2]:
            variable["query"] = "PROFILE"
            variable["current"] = {"text": "PROFILE", "value": "PROFILE"}
    assert normalized_staging == normalized_prod


def test_canonical_dashboard_defaults_and_no_data_contract():
    dashboard = load(STAGING)
    assert dashboard["schemaVersion"] == 41
    assert dashboard["timezone"] == "browser"
    assert dashboard["editable"] is False
    assert dashboard["refresh"] == "30s"
    assert dashboard["time"] == {"from": "now-6h", "to": "now"}
    for item in dashboard["panels"]:
        if item["type"] not in {"row", "text"}:
            assert item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"


def test_all_ten_tables_are_simultaneous_single_frames():
    tables = [item for item in load(STAGING)["panels"] if item["type"] == "table"]
    assert len(tables) == 10
    for item in tables:
        assert len(item["targets"]) == 1
        assert {key: item["targets"][0][key] for key in ("format", "instant", "range")} == {
            "format": "table",
            "instant": True,
            "range": False,
        }
        assert len(item["transformations"]) == 1
        assert item["transformations"][0]["id"] == "organize"


def test_environment_neutral_and_bounded_selectors():
    dashboard = load(STAGING)
    blackbox = " ".join(
        expression
        for title in (
            "Public availability summary",
            "Endpoint matrix",
            "Probe duration",
            "HTTP response status",
            "TLS certificate lifetime",
        )
        for expression in expressions(dashboard, title)
    )
    assert "-$environment-.*" in blackbox
    tokenplace = " ".join(
        target["expr"]
        for item in dashboard["panels"]
        if item["title"].startswith("token.place")
        for target in item.get("targets", [])
    )
    assert 'cluster=~"$cluster"' in tokenplace
    assert 'environment=~"$environment"' in tokenplace
    assert 'namespace="tokenplace"' in tokenplace


def test_absent_production_application_capabilities_remain_no_data_not_healthy_zero():
    dashboard = load(PROD)
    application_titles = [
        "DSPACE scrape availability",
        "DSPACE instrumentation health",
        "Endpoint matrix",
        "Approved revision",
        "token.place scrape availability",
        "token.place instrumentation health",
    ]
    for title in application_titles:
        item = panel(dashboard, title)
        assert item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
        assert all("vector(0)" not in target.get("expr", "") for target in item.get("targets", []))
    for title in (
        "Image-pin agreement",
        "DSPACE metrics-target health",
        "/chat synthetic result and freshness",
    ):
        joined = " ".join(expressions(dashboard, title))
        assert "dspace_release_approved_info" in joined
        if "0 *" in joined:
            assert "count(dspace_release_approved_info" in joined


def test_event_zeroes_require_instrumentation_capability():
    dashboard = load(PROD)
    for title in ("dChat request activity", "token.place dependency request activity"):
        expression = expressions(dashboard, title)[0]
        assert "0 *" in expression
        assert "dspace_instrumentation_up" in expression
        assert "vector(0)" not in expression


def test_image_pin_uses_approved_release_label_contract():
    expression = expressions(load(STAGING), "Image-pin agreement")[0]
    assert '"image", "(.*)"' in expression
    assert '"image_digest", "(.*)"' in expression
    assert "main-018687f" not in expression
    assert "2b95b7fd" not in expression


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: panel(d, "Ready nodes").update(title="Ready node count"),
        lambda d: panel(d, "Ready nodes")["targets"][0].update(expr="vector(1)"),
        lambda d: panel(d, "Ready nodes")["gridPos"].update(x=0),
        lambda d: panel(d, "Ready nodes").update(type="timeseries"),
        lambda d: panel(d, "Node readiness")["transformations"][0].update(id="reduce"),
        lambda d: panel(d, "Ready nodes")["fieldConfig"]["defaults"].update(noValue="0"),
        lambda d: d["templating"]["list"][0].update(query="staging"),
        lambda d: panel(d, "Node readiness")["targets"][0].update(instant=False),
    ],
    ids=["title", "query", "grid", "type", "transformation", "noValue", "variable", "target-mode"],
)
def test_one_sided_mutations_fail_closed(tmp_path, mutation):
    dashboard = load(PROD)
    mutation(dashboard)
    with pytest.raises(SystemExit):
        validator.validate_dashboard(write_mutation(tmp_path, dashboard))


def test_generator_does_not_read_generated_peer(monkeypatch):
    def forbidden_read(*args, **kwargs):
        raise AssertionError("generated dashboard was read")

    original = Path.read_text

    def guarded(path, *args, **kwargs):
        if path in {STAGING, PROD}:
            return forbidden_read()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    assert generator.render_dashboard("staging")["uid"] == "sugarkube-staging-observability"
    assert generator.render_dashboard("prod")["uid"] == "sugarkube-prod-observability"
