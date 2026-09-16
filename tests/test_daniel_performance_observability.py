"""Contract tests for passive Daniel controlled-performance observability."""

import json
import re
from pathlib import Path

import pytest

from scripts import daniel_performance_metrics as metrics


def result(state="completed", renderer_class="hardware", fallback=False, frame=True):
    available = {
        "state": "available",
        "sampleCount": 40,
        "medianMs": 4,
        "p95Ms": 8,
        "maxMs": 12,
    }
    frame_summary = {
        "state": "available",
        "sampleCount": 120,
        "medianMs": 16,
        "p95Ms": 20,
        "maxMs": 24,
    }
    unavailable = {"state": "unavailable", "reason": "not_collected"}
    if state == "unavailable":
        available = unavailable
    if fallback:
        frame_summary = {"state": "unavailable", "reason": "renderer_fallback"}
    elif renderer_class != "hardware":
        frame_summary = {"state": "unavailable", "reason": "unsupported_environment"}
    elif not frame:
        frame_summary = unavailable
    return {
        "schemaVersion": 1,
        "state": state,
        "measuredAt": 1_800_000_000,
        "build": {"environment": "staging", "tag": "v1.2.3-sha256:abc"},
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
        "applicationReady": available,
        "interactionLatency": available,
        "frameTime": frame_summary,
    }


def encoded(**kwargs):
    return json.dumps(result(**kwargs)).encode()


@pytest.mark.parametrize("state", metrics.RESULT_STATES)
def test_completed_regression_and_unavailable_are_distinct(state):
    output = metrics.render(encoded(state=state), "staging")
    assert f'state="{state}"}} 1' in output
    if state == "unavailable":
        assert "daniel_performance_application_ready_seconds" not in output
        assert 'measurement="application_ready",reason="not_collected"} 1' in output


@pytest.mark.parametrize("renderer_class", metrics.RENDERER_CLASSES)
def test_renderer_classes_stay_distinct_and_only_hardware_has_frames(renderer_class):
    output = metrics.render(encoded(renderer_class=renderer_class), "staging")
    assert f'renderer_class="{renderer_class}"}} 1' in output
    assert ("daniel_performance_frame_time_seconds" in output) is (renderer_class == "hardware")


def test_fallback_is_explicit_and_does_not_fabricate_frames():
    output = metrics.render(
        encoded(state="unavailable", renderer_class="unknown", fallback=True), "staging"
    )
    assert 'renderer_state="fallback"} 1' in output
    assert 'fallback_status="software_renderer"} 1' in output
    assert 'measurement="frame_time",reason="renderer_fallback"} 1' in output
    assert "daniel_performance_frame_time_seconds" not in output


def test_optional_missing_frame_summary_is_no_data_not_zero():
    output = metrics.render(encoded(frame=False), "staging")
    assert 'measurement="frame_time",reason="not_collected"} 1' in output
    assert "daniel_performance_frame_time_seconds" not in output


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(sessionId="private-session"),
        lambda value: value["environment"].update(url="https://private.invalid/path"),
        lambda value: value["build"].update(tag="x" * 81),
        lambda value: value["build"].update(environment="dev"),
        lambda value: value["interactionLatency"].update(p95Ms=13),
        lambda value: value["frameTime"].update(sampleCount=119),
    ],
)
def test_malformed_privacy_sensitive_and_unbounded_payloads_fail_closed(mutate):
    value = result()
    mutate(value)
    with pytest.raises(metrics.InvalidDocument):
        metrics.parse_document(json.dumps(value).encode(), "staging")


def test_oversized_and_missing_payloads_publish_explicit_status(tmp_path):
    oversized = tmp_path / "result.json"
    oversized.write_bytes(b" " * (metrics.MAX_BYTES + 1))
    assert 'status="oversized"} 1' in metrics.collect(oversized, "staging")
    missing = metrics.collect(tmp_path / "missing.json", "staging")
    assert 'status="unavailable"} 1' in missing
    assert 'state="unavailable"} 1' in missing
    assert "_seconds{" not in missing


def test_only_bounded_labels_and_safe_build_identity_are_exported():
    output = metrics.render(encoded(), "staging")
    labels = set()
    for line in output.splitlines():
        if line.startswith("#"):
            continue
        match = re.fullmatch(r"\w+\{([^}]*)\} \S+", line)
        assert match
        labels.update(re.findall(r'(\w+)="', match.group(1)))
    assert labels == {
        "environment",
        "status",
        "state",
        "renderer_class",
        "renderer_state",
        "fallback_status",
        "build_tag",
        "measurement",
        "reason",
        "statistic",
    }
    assert 'build_tag="v1.2.3-sha256:abc"' in output


def test_atomic_textfile_entrypoint_consumes_existing_scheduler_result(tmp_path):
    source, output = tmp_path / "result.json", tmp_path / "metrics.prom"
    source.write_bytes(encoded())
    assert (
        metrics.main(["--result", str(source), "--environment", "staging", "--output", str(output)])
        == 0
    )
    assert 'daniel_performance_collection_up{environment="staging"} 1' in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o644
    # This integration is a passive adapter: it defines no timer or scheduler.
    assert not list(Path("scripts/systemd").glob("*daniel*performance*"))
