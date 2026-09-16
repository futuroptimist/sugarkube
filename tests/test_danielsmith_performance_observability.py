import json
import re
from pathlib import Path

import pytest

from scripts import daniel_performance_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]


def result(**changes):
    value = {
        "schemaVersion": 1,
        "state": "completed",
        "measuredAt": 1_800_000_000,
        "build": {"environment": "staging", "tag": "main-abc1234"},
        "environment": {
            "browser": "chromium",
            "browserMajorVersion": 128,
            "viewportWidth": 1280,
            "viewportHeight": 720,
            "renderingMode": "immersive",
            "rendererClass": "hardware",
            "frameMeasurementProfile": "controlled_hardware_v1",
        },
        "conditions": {
            "warmupMs": 5000,
            "interactionName": "keyboard_movement",
            "requestedActions": 20,
            "eventsPerAction": 2,
            "requestedSamples": 40,
        },
        "renderer": {"state": "immersive", "fallbackReason": "none"},
        "applicationReady": {
            "state": "available",
            "sampleCount": 1,
            "medianMs": 820,
            "p95Ms": 820,
            "maxMs": 820,
        },
        "interactionLatency": {
            "state": "available",
            "sampleCount": 40,
            "medianMs": 16,
            "p95Ms": 32,
            "maxMs": 40,
        },
        "frameTime": {
            "state": "available",
            "sampleCount": 120,
            "medianMs": 16,
            "p95Ms": 24,
            "maxMs": 35,
        },
    }
    for key, change in changes.items():
        if key in {"build", "environment", "conditions", "renderer"} and isinstance(change, dict):
            value[key].update(change)
        else:
            value[key] = change
    return value


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


@pytest.mark.parametrize("state", metrics.RESULT_STATES)
def test_completed_regression_and_unavailable_are_distinct(state):
    value = result(state=state)
    if state == "unavailable":
        value["applicationReady"] = {"state": "unavailable", "reason": "not_collected"}
    output = metrics.render(encode(value), "staging")
    assert f'daniel_performance_result_state{{environment="staging",state="{state}"}} 1' in output
    assert ("daniel_performance_application_ready_seconds" in output) == (state != "unavailable")


@pytest.mark.parametrize("renderer_class", ["hardware", "software"])
def test_hardware_and_software_are_separate_populations(renderer_class):
    value = result(environment={"rendererClass": renderer_class})
    if renderer_class == "software":
        value["environment"]["frameMeasurementProfile"] = "unsupported"
        value["frameTime"] = {"state": "unavailable", "reason": "unsupported_environment"}
    output = metrics.render(encode(value), "staging")
    assert f'renderer_class="{renderer_class}"}} 1' in output
    assert ("daniel_performance_frame_time_seconds" in output) == (renderer_class == "hardware")


def test_renderer_fallback_is_explicit_and_never_fabricates_frames():
    value = result(
        environment={
            "renderingMode": "fallback",
            "rendererClass": "software",
            "frameMeasurementProfile": "unsupported",
        },
        renderer={"state": "fallback", "fallbackReason": "software_renderer"},
        frameTime={"state": "unavailable", "reason": "renderer_fallback"},
    )
    output = metrics.render(encode(value), "staging")
    assert 'fallback_reason="software_renderer"} 1' in output
    assert 'measurement="frame_time",environment="staging",reason="renderer_fallback"} 1' in output
    assert "daniel_performance_frame_time_seconds" not in output


@pytest.mark.parametrize("reason", metrics.UNAVAILABLE_REASONS[1:])
def test_missing_or_unsupported_frames_are_no_data(reason):
    value = result(
        environment={"frameMeasurementProfile": "unsupported", "rendererClass": "unknown"}
    )
    value["frameTime"] = {"state": "unavailable", "reason": reason}
    output = metrics.render(encode(value), "staging")
    assert "daniel_performance_frame_time_seconds" not in output
    assert f'reason="{reason}"}} 1' in output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(sessionId="private"),
        lambda value: value["environment"].update(url="https://example.test/private"),
        lambda value: value["renderer"].update(rawConsoleError="secret"),
        lambda value: value["build"].update(tag="x" * 81),
        lambda value: value["interactionLatency"].update(sampleCount=39),
        lambda value: value["frameTime"].update(sampleCount=119),
    ],
)
def test_malformed_unbounded_and_privacy_sensitive_payloads_fail_closed(mutation):
    value = result()
    mutation(value)
    with pytest.raises(ValueError):
        metrics.render(encode(value), "staging")


def test_oversized_payload_fails_closed():
    with pytest.raises(ValueError, match="payload size"):
        metrics.parse_result(b" " * (metrics.MAX_PAYLOAD_BYTES + 1), "staging")


def test_labels_and_build_identity_are_bounded():
    output = metrics.render(encode(result()), "staging")
    labels = re.findall(r"\{([^}]+)\}", output)
    allowed = {
        "environment",
        "state",
        "renderer_class",
        "renderer_state",
        "fallback_reason",
        "build_environment",
        "build_tag",
        "measurement",
        "reason",
        "statistic",
    }
    assert all({part.split("=", 1)[0] for part in group.split(",")} <= allowed for group in labels)
    assert 'build_environment="staging",build_tag="main-abc1234"' in output
    mismatch = result(build={"environment": "prod"})
    with pytest.raises(ValueError):
        metrics.render(encode(mismatch), "staging")


def test_malformed_result_replaces_previous_samples(tmp_path, monkeypatch):
    output = tmp_path / "daniel-performance.prom"
    output.write_text(metrics.render(encode(result()), "staging"))
    source = tmp_path / "result.json"
    source.write_text('{"sessionId":"private"}')
    monkeypatch.setattr(
        "sys.argv",
        ["collector", "--result", str(source), "--output", str(output), "--environment", "staging"],
    )
    assert metrics.main() == 1
    assert output.read_text() == metrics.failure_metrics("staging")


def test_performance_reuses_visitor_scheduler_without_new_timer():
    timers = list((ROOT / "scripts/systemd").glob("*daniel*performance*"))
    assert timers == []
    docs = (ROOT / "docs/danielsmith-performance-observability.md").read_text()
    assert "existing Daniel visitor-journey scheduler" in docs
    assert "must not create a second timer" in docs
