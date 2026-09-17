"""Contract tests for passive Daniel controlled-performance observability."""

import json
import re
import runpy
import subprocess
import sys

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
        "measuredAt": 1_700_000_000,
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


def test_measurement_timestamp_is_exported_for_dashboard_freshness():
    output = metrics.render(encoded(), "staging")
    assert (
        'daniel_performance_measurement_timestamp_seconds{environment="staging"} '
        "1700000000" in output
    )


def test_boolean_schema_version_fails_closed():
    value = result()
    value["schemaVersion"] = True
    with pytest.raises(metrics.InvalidDocument):
        metrics.parse_document(json.dumps(value).encode(), "staging")


def test_future_timestamp_uses_injected_clock_and_fails_closed(tmp_path):
    value = result()
    value["measuredAt"] = 10_061
    payload = json.dumps(value).encode()
    with pytest.raises(metrics.InvalidDocument, match="clock skew"):
        metrics.parse_document(payload, "staging", now=10_000)
    source = tmp_path / "future.json"
    source.write_bytes(payload)
    output = metrics.collect(source, "staging", now=10_000)
    assert 'status="malformed"} 1' in output
    assert "measurement_timestamp_seconds" not in output


@pytest.mark.parametrize("renderer_class", metrics.RENDERER_CLASSES)
def test_renderer_classes_stay_distinct_and_only_hardware_has_frames(renderer_class):
    output = metrics.render(encoded(renderer_class=renderer_class), "staging")
    assert f'renderer_class="{renderer_class}"}} 1' in output
    assert ("daniel_performance_frame_time_seconds" in output) is (renderer_class == "hardware")
    assert (
        f'daniel_performance_application_ready_seconds{{environment="staging",'
        f'renderer_class="{renderer_class}",renderer_state="immersive",'
        'fallback_status="none",statistic="p95"} 0.008'
    ) in output


def test_fallback_is_explicit_and_does_not_fabricate_frames():
    output = metrics.render(
        encoded(state="unavailable", renderer_class="unknown", fallback=True), "staging"
    )
    assert 'renderer_state="fallback"} 1' in output
    assert 'fallback_status="software_renderer"} 1' in output
    assert 'measurement="frame_time",reason="renderer_fallback"} 1' in output
    assert "daniel_performance_frame_time_seconds" not in output
    assert (
        'renderer_class="unknown",renderer_state="fallback",'
        'fallback_status="software_renderer",statistic="p95"'
    ) not in output  # unavailable results have no timing series


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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["environment"].update(browser="netscape"),
        lambda value: value["environment"].update(browserMajorVersion=True),
        lambda value: value["environment"].update(viewportWidth=0),
        lambda value: value["environment"].update(frameMeasurementProfile="experimental"),
        lambda value: value["conditions"].update(warmupMs=True),
        lambda value: value["conditions"].update(warmupMs=float("inf")),
        lambda value: value["conditions"].update(eventsPerAction=3),
        lambda value: value["conditions"].update(requestedSamples=39),
        lambda value: value["renderer"].update(state="broken"),
        lambda value: value["renderer"].update(fallbackReason="none", state="fallback"),
        lambda value: value.update(applicationReady=[]),
        lambda value: value["applicationReady"].update(state="broken"),
        lambda value: value.update(applicationReady={"state": "unavailable", "reason": "private"}),
        lambda value: value.update(state="unavailable"),
        lambda value: value["interactionLatency"].update(sampleCount=39),
        lambda value: value["environment"].update(
            rendererClass="software", frameMeasurementProfile="controlled_hardware_v1"
        ),
    ],
)
def test_invalid_contract_values_fail_closed(mutate):
    value = result()
    mutate(value)
    with pytest.raises(metrics.InvalidDocument):
        metrics.parse_document(json.dumps(value, allow_nan=True).encode(), "staging")


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
        "measurement",
        "reason",
        "statistic",
    }
    assert "daniel_performance_build_info" not in output

    changed_build = result()
    changed_build["build"]["tag"] = "another-valid-build"
    assert metrics.render(json.dumps(changed_build).encode(), "staging") == output


def test_atomic_textfile_entrypoint_consumes_existing_scheduler_result(tmp_path):
    source, output = tmp_path / "result.json", tmp_path / "metrics.prom"
    source.write_bytes(encoded())
    assert (
        metrics.main(["--result", str(source), "--environment", "staging", "--output", str(output)])
        == 0
    )
    assert 'daniel_performance_collection_up{environment="staging"} 1' in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o644


def test_cli_without_result_publishes_bounded_unavailable_metrics(tmp_path):
    output = tmp_path / "metrics.prom"
    completed = subprocess.run(
        [
            sys.executable,
            str(metrics.Path(metrics.__file__)),
            "--environment",
            "staging",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout == completed.stderr == ""
    content = output.read_text()
    assert len(content) < 2_000
    assert 'status="unavailable"} 1' in content
    assert "_seconds{" not in content


def test_main_module_path_and_omitted_result_are_covered(tmp_path, monkeypatch):
    output = tmp_path / "module-metrics.prom"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(metrics.Path(metrics.__file__)),
            "--environment",
            "staging",
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(metrics.Path(metrics.__file__)), run_name="__main__")
    assert 'status="unavailable"} 1' in output.read_text()


def test_atomic_replacement_failure_preserves_output_and_removes_temporary_file(
    tmp_path, monkeypatch
):
    output = tmp_path / "metrics.prom"
    output.write_text("prior output\n")

    def fail_replace(_source, _destination):
        raise OSError("injected replacement failure")

    monkeypatch.setattr(metrics.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        metrics.write_textfile(output, "new output\n")

    assert output.read_text() == "prior output\n"
    assert list(tmp_path.glob(".daniel-performance-*")) == []


@pytest.mark.parametrize("failure", ["missing", "unreadable", "malformed", "oversized", "private"])
def test_valid_output_is_atomically_replaced_by_failure_without_private_data(tmp_path, failure):
    source, output = tmp_path / "result.json", tmp_path / "metrics.prom"
    source.write_bytes(encoded())
    metrics.write_textfile(output, metrics.collect(source, "staging"))
    assert "application_ready_seconds" in output.read_text()
    if failure == "missing":
        source.unlink()
    elif failure == "unreadable":
        source = tmp_path  # opening a directory as a file fails on every supported platform
    elif failure == "malformed":
        source.write_text("not-json")
    elif failure == "oversized":
        source.write_bytes(b"x" * (metrics.MAX_BYTES + 1))
    else:
        private = result()
        private["sessionToken"] = "SECRET_PRIVATE_VALUE"
        source.write_text(json.dumps(private))
    metrics.write_textfile(output, metrics.collect(source, "staging"))
    replaced = output.read_text()
    assert "application_ready_seconds" not in replaced
    assert "SECRET_PRIVATE_VALUE" not in replaced
    assert 'daniel_performance_collection_up{environment="staging"} 0' in replaced
