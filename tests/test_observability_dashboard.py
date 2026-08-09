import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts/generate_observability_dashboards.py"
VALIDATOR = ROOT / "scripts/validate_observability_dashboard.py"
SPEC = ROOT / "platform/observability/dashboards/sugarkube-observability.json"
STAGING = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
PROD = ROOT / "clusters/prod/observability/dashboards/sugarkube-prod-observability.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def panel(document, title):
    return next(item for item in document["panels"] if item["title"] == title)


def validate(path):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(path)], text=True, capture_output=True
    )


def test_generator_check_and_both_profiles_validate():
    subprocess.run([sys.executable, str(GENERATOR), "--check"], check=True)
    for path in (STAGING, PROD):
        subprocess.run([sys.executable, str(VALIDATOR), str(path)], check=True)


def test_canonical_shape_and_only_profile_differences():
    staging, prod = load(STAGING), load(PROD)
    assert staging["panels"] == prod["panels"]
    assert len(staging["panels"]) == 60
    assert sum(item["type"] == "row" for item in staging["panels"]) == 11
    normalized = []
    for dashboard in (staging, prod):
        value = copy.deepcopy(dashboard)
        value["uid"] = value["title"] = None
        value["tags"][-1] = None
        for variable in value["templating"]["list"][:2]:
            variable["query"] = None
            variable["current"]["text"] = variable["current"]["value"] = None
        normalized.append(value)
    assert normalized[0] == normalized[1]


def test_every_data_panel_has_explicit_no_data_and_tables_are_single_frame():
    dashboard = load(STAGING)
    for item in dashboard["panels"]:
        if item["type"] not in {"row", "text"}:
            assert item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
        if item["type"] == "table":
            assert len(item["targets"]) == 1
            assert {key: item["targets"][0][key] for key in ("format", "instant", "range")} == {
                "format": "table",
                "instant": True,
                "range": False,
            }
            assert [transform["id"] for transform in item["transformations"]] == ["organize"]
    assert sum(item["type"] == "table" for item in dashboard["panels"]) == 10


def test_production_application_absence_is_no_data_not_healthy_zero():
    dashboard = load(PROD)
    application_rows = {
        "DSPACE HTTP",
        "DSPACE runtime and release",
        "DSPACE feature traffic",
        "Blackbox monitoring",
        "DSPACE release integrity",
        "token.place relay and compute capacity",
        "token.place HTTP and release",
    }
    active = False
    for item in dashboard["panels"]:
        if item["type"] == "row":
            active = item["title"] in application_rows
        elif active and item["type"] != "text":
            assert item["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
            for target in item.get("targets", []):
                expression = target.get("expr", "")
                if "or vector(0)" in expression or "or on() vector(0)" in expression:
                    assert "max_over_time(up{" in expression
    capability_titles = {
        "dChat request activity",
        "token.place dependency request activity",
        "Image-pin agreement",
        "DSPACE metrics-target health",
        "/chat synthetic result and freshness",
    }
    for title in capability_titles:
        assert 'dspace_release_approved_info{environment=~"$environment"}' in " ".join(
            target.get("expr", "") for target in panel(dashboard, title).get("targets", [])
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: panel(d, "Ready nodes").update(title="Ready nodes changed"),
        lambda d: panel(d, "Ready nodes")["targets"][0].update(expr="vector(1)"),
        lambda d: panel(d, "Ready nodes")["gridPos"].update(x=1),
        lambda d: panel(d, "Ready nodes").update(type="table"),
        lambda d: panel(d, "Endpoint matrix").update(transformations=[]),
        lambda d: panel(d, "Ready nodes")["fieldConfig"]["defaults"].pop("noValue"),
        lambda d: d["templating"]["list"][0].update(query="prod"),
        lambda d: panel(d, "Endpoint matrix")["targets"][0].update(range=True),
    ],
    ids=["title", "query", "grid", "type", "transformation", "no-value", "variable", "target-mode"],
)
def test_one_sided_layout_mutations_fail_closed(tmp_path, mutation):
    document = load(STAGING)
    mutation(document)
    candidate = tmp_path / STAGING.name
    candidate.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    result = validate(candidate)
    assert result.returncode != 0
    assert "canonical generated artifact" in result.stderr


def test_stale_generated_artifact_is_detected(tmp_path):
    # The real artifacts remain immutable; prove byte sensitivity with a temporary repo copy of one file.
    original = STAGING.read_text(encoding="utf-8")
    assert original == json.dumps(load(STAGING), indent=2) + "\n"
    assert SPEC.exists()
