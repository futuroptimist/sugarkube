"""Contract tests for passive Daniel controlled-performance telemetry."""

import json
from pathlib import Path

import pytest

from scripts import daniel_performance_metrics as metrics
from scripts.generate_observability_dashboards import PROFILES, render as render_dashboard

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"


def summary(*, count=40, median=2, p95=4, maximum=6):
    return {
        "state": "available",
        "sampleCount": count,
        "medianMs": median,
        "p95Ms": p95,
        "maxMs": maximum,
    }


def result(state="completed", renderer_class="hardware", fallback=False, frame=True):
    hardware = renderer_class == "hardware" and not fallback
    document = {
        "schemaVersion": 1,
        "state": state,
        "measuredAt": 1_789_516_800,
        "build": {"environment": "staging", "tag": "sha256:abc.123"},
        "environment": {
            "browser": "chromium",
            "browserMajorVersion": 140,
            "viewportWidth": 1280,
            "viewportHeight": 720,
            "renderingMode": "fallback" if fallback else "immersive",
            "rendererClass": renderer_class,
            "frameMeasurementProfile": "controlled_hardware_v1" if hardware else "unsupported",
        },
        "conditions": {
            "warmupMs": 5000,
            "interactionName": "keyboard_movement",
            "requestedActions": 20,
            "eventsPerAction": 2,
            "requestedSamples": 40,
        },
        "renderer": {
            "state": "fallback" if fallback else "immersive",
            "fallbackReason": "software_renderer" if fallback else "none",
        },
        "applicationReady": summary(count=1, median=900, p95=900, maximum=900),
        "interactionLatency": summary(),
        "frameTime": (
            summary(count=120, median=12, p95=18, maximum=22)
            if hardware and frame
            else {
                "state": "unavailable",
                "reason": (
                    "renderer_fallback"
                    if fallback
                    else "unsupported_environment" if not hardware else "not_collected"
                ),
            }
        ),
    }
    if state == "unavailable":
        document["applicationReady"] = {"state": "unavailable", "reason": "not_collected"}
    return document


def encoded(value):
    return json.dumps(value, allow_nan=False).encode()


@pytest.mark.parametrize("state", metrics.RESULT_STATES)
def test_completed_regression_and_unavailable_are_explicit(state):
    output = metrics.render(encoded(result(state)), "staging")
    assert f'state="{state}"}} 1' in output
    assert 'daniel_performance_collection_up{environment="staging"} 1' in output
    if state == "unavailable":
        assert "daniel_performance_application_ready_seconds" not in output


@pytest.mark.parametrize("renderer_class", ["hardware", "software"])
def test_software_and_hardware_are_separate_and_frames_are_never_fabricated(renderer_class):
    output = metrics.render(encoded(result(renderer_class=renderer_class)), "staging")
    assert f'renderer_class="{renderer_class}"' in output
    assert ("daniel_performance_frame_time_seconds" in output) is (renderer_class == "hardware")


def test_renderer_fallback_is_explicit_and_has_no_frames():
    output = metrics.render(encoded(result(renderer_class="software", fallback=True)), "staging")
    assert 'renderer_mode="fallback",renderer_class="software"' in output
    assert 'fallback_status="software_renderer"} 1' in output
    assert "daniel_performance_frame_time_seconds" not in output


def test_optional_hardware_frames_can_be_missing():
    output = metrics.render(encoded(result(frame=False)), "staging")
    assert 'renderer_class="hardware"' in output
    assert "daniel_performance_frame_time_seconds" not in output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(sessionId="private"),
        lambda value: value["environment"].update(url="https://private.invalid"),
        lambda value: value["renderer"].update(consoleError="secret"),
        lambda value: value["build"].update(tag="x" * 81),
        lambda value: value["environment"].update(rendererClass="raw-gpu-name"),
    ],
)
def test_malformed_privacy_sensitive_and_unbounded_values_fail_closed(mutation):
    document = result()
    mutation(document)
    with pytest.raises(metrics.InvalidResult):
        metrics.render(encoded(document), "staging")


def test_oversized_payload_fails_closed():
    with pytest.raises(OverflowError):
        metrics.parse(b"{" + b" " * metrics.MAX_BYTES + b"}")


def test_build_identity_is_bounded_and_must_match_environment():
    output = metrics.render(encoded(result()), "staging")
    assert 'build_environment="staging",build_tag="sha256:abc.123"' in output
    with pytest.raises(metrics.InvalidResult, match="does not match"):
        metrics.render(encoded(result()), "prod")


def test_collector_reuses_visitor_scheduler_and_adds_no_second_scheduler():
    docs = (ROOT / "docs/observability-operations.md").read_text()
    assert "same existing Daniel visitor-journey scheduler invocation" in docs
    assert "does not own or install a timer" in docs
    assert not list((ROOT / "scripts/systemd").glob("*daniel*performance*"))


def test_dashboard_queries_units_legends_and_no_data():
    expected = {
        "Daniel application-ready duration": (
            "daniel_performance_application_ready_seconds",
            "s",
            "{{statistic}}",
        ),
        "Daniel interaction latency": (
            "daniel_performance_interaction_latency_seconds",
            "s",
            "{{statistic}}",
        ),
        "Daniel renderer mode": (
            "daniel_performance_renderer_info",
            "short",
            "{{renderer_mode}} / {{renderer_class}}",
        ),
        "Daniel renderer fallback": (
            "daniel_performance_fallback_status",
            "short",
            "{{fallback_status}}",
        ),
        "Daniel frame time": ("daniel_performance_frame_time_seconds", "s", "{{statistic}}"),
    }
    documents = [json.loads(TEMPLATE.read_text())]
    documents += [json.loads(render_dashboard(profile)) for profile in PROFILES.values()]
    for document in documents:
        panels = {panel["title"]: panel for panel in document["panels"]}
        for title, (metric, unit, legend) in expected.items():
            panel = panels[title]
            target = panel["targets"][0]
            assert metric in target["expr"] and 'environment=~"$environment"' in target["expr"]
            assert "vector(0)" not in target["expr"]
            assert target["legendFormat"] == legend
            assert panel["fieldConfig"]["defaults"]["unit"] == unit
            assert panel["fieldConfig"]["defaults"]["noValue"] == "NO DATA"


def test_checked_in_dashboards_are_exact_generated_outputs():
    for profile in PROFILES.values():
        assert profile["path"].read_text() == render_dashboard(profile)
