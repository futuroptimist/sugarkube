"""Focused coverage for the passive Daniel performance integration."""

import json
from pathlib import Path

import pytest

from scripts import daniel_performance_metrics as metrics


def result(state="completed", renderer_class="hardware", fallback=False, frame=True):
    unavailable = {"state": "unavailable", "reason": "not_collected"}
    summary = {"state": "available", "sampleCount": 40, "medianMs": 2, "p95Ms": 4, "maxMs": 8}
    value = {
        "schemaVersion": 1,
        "state": state,
        "measuredAt": 1_800_000_000,
        "build": {"environment": "staging", "tag": "sha256:abc123"},
        "environment": {
            "browser": "chromium",
            "browserMajorVersion": 140,
            "viewportWidth": 1280,
            "viewportHeight": 720,
            "renderingMode": "fallback" if fallback else "immersive",
            "rendererClass": renderer_class,
            "frameMeasurementProfile": (
                "controlled_hardware_v1"
                if renderer_class == "hardware" and not fallback
                else "unsupported"
            ),
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
        "applicationReady": {
            "state": "available",
            "sampleCount": 1,
            "medianMs": 100,
            "p95Ms": 100,
            "maxMs": 100,
        },
        "interactionLatency": summary,
        "frameTime": (
            {"state": "available", "sampleCount": 120, "medianMs": 10, "p95Ms": 15, "maxMs": 20}
            if frame
            else unavailable
        ),
    }
    if state == "unavailable":
        value["interactionLatency"] = unavailable
    return value


@pytest.mark.parametrize("state", metrics.RESULT_STATES)
def test_states_are_explicit_and_bounded(state):
    output = metrics.render(json.dumps(result(state=state)).encode(), "staging")
    assert f'state="{state}"}} 1' in output
    assert output.count("daniel_performance_result_state{") == 3


@pytest.mark.parametrize("renderer_class", ["hardware", "software"])
def test_hardware_and_software_are_distinct_without_inventing_frames(renderer_class):
    value = result(renderer_class=renderer_class, frame=renderer_class == "hardware")
    output = metrics.render(json.dumps(value).encode(), "staging")
    assert f'renderer_class="{renderer_class}"}} 1' in output
    assert ("daniel_performance_frame_time_seconds" in output) == (renderer_class == "hardware")


def test_fallback_is_explicit_and_has_no_frame_series():
    output = metrics.render(
        json.dumps(result(renderer_class="software", fallback=True, frame=False)).encode(),
        "staging",
    )
    assert 'renderer_state="fallback"} 1' in output
    assert 'fallback_reason="software_renderer"} 1' in output
    assert "daniel_performance_frame_time_seconds" not in output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(sessionId="private"),
        lambda value: value["environment"].update(url="https://private.example"),
        lambda value: value["build"].update(tag="x" * 81),
        lambda value: value.update(state="success"),
    ],
)
def test_malformed_privacy_sensitive_and_unbounded_payloads_fail_closed(mutation):
    value = result(frame=False)
    mutation(value)
    with pytest.raises(metrics.InvalidResult):
        metrics.parse_result(json.dumps(value).encode(), "staging")


def test_oversized_and_missing_results_publish_no_measurements(tmp_path):
    oversized = tmp_path / "result.json"
    oversized.write_bytes(b" " * (metrics.MAX_BYTES + 1))
    for path, status in ((oversized, "oversized"), (None, "unavailable")):
        output = metrics.collect(path, "staging")
        assert f'status="{status}"}} 1' in output
        assert "application_ready_seconds" not in output
        assert 'collection_up{environment="staging"} 0' in output


def test_build_environment_must_match_collector_scope():
    with pytest.raises(metrics.InvalidResult, match="build identity"):
        metrics.parse_result(json.dumps(result()).encode(), "prod")


def test_no_new_scheduler_is_added_and_existing_handoff_is_documented():
    root = Path(__file__).parents[1]
    assert not list((root / "scripts/systemd").glob("*performance*"))
    docs = (root / "docs/danielsmith-performance-observability.md").read_text()
    assert "existing visitor-journey scheduler" in docs
    assert "does not add a timer" in docs
