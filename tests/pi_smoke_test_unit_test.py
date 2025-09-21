import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "pi_smoke_test.py"
SPEC = importlib.util.spec_from_file_location("pi_smoke_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_verifier_output_success():
    payload = {
        "checks": [
            {"name": "cloud_init", "status": "pass"},
            {"name": "k3s", "status": "skip"},
        ]
    }
    output = json.dumps(payload)
    checks = MODULE.parse_verifier_output(output)
    assert checks == payload["checks"]


def test_parse_verifier_output_errors_on_empty():
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.parse_verifier_output("\n \n")


def test_summarise_checks_counts_failures():
    checks = [
        {"name": "one", "status": "pass"},
        {"name": "two", "status": "skip"},
        {"name": "three", "status": "fail"},
    ]
    result = MODULE.summarise_checks(checks)
    assert result.passes == 1
    assert result.total == 3
    assert len(result.failures) == 1
    assert result.failures[0]["name"] == "three"


def test_parse_verifier_output_requires_checks_key():
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.parse_verifier_output("{}")


def test_build_env_prefers_skip_flags():
    args = SimpleNamespace(
        skip_token_place=True,
        token_place_url="https://override",
        skip_dspace=False,
        dspace_url="https://dspace",
    )

    env = MODULE.build_env(args)
    assert env["TOKEN_PLACE_HEALTH_URL"] == "skip"
    assert env["DSPACE_HEALTH_URL"] == "https://dspace"


def test_build_ssh_command_includes_options():
    args = SimpleNamespace(
        user="pi",
        port=2222,
        connect_timeout=5,
        ssh_option=["StrictHostKeyChecking=yes"],
        identity="~/.ssh/id_rsa",
    )

    command = MODULE.build_ssh_command("pi.local", args, "echo ok")
    assert "-i" in command
    assert "StrictHostKeyChecking=yes" in command
    assert "pi@pi.local" in command


def test_run_verifier_handles_timeout(monkeypatch):
    args = MODULE.parse_args(["pi.local"])
    monkeypatch.setattr(MODULE, "build_env", lambda _: {})

    def fake_run_ssh(*_, **__):
        raise MODULE.subprocess.TimeoutExpired(cmd="ssh", timeout=1)

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)

    with pytest.raises(MODULE.SmokeTestError) as excinfo:
        MODULE.run_verifier("pi.local", args)

    assert "timed out" in str(excinfo.value)


def test_run_verifier_handles_nonzero_exit(monkeypatch):
    args = MODULE.parse_args(["pi.local"])
    monkeypatch.setattr(MODULE, "build_env", lambda _: {})

    result = MODULE.subprocess.CompletedProcess(
        args=["ssh"], returncode=1, stdout="", stderr="permission denied"
    )
    monkeypatch.setattr(MODULE, "run_ssh", lambda *_, **__: result)

    with pytest.raises(MODULE.SmokeTestError) as excinfo:
        MODULE.run_verifier("pi.local", args)

    assert "permission denied" in str(excinfo.value)


def test_wait_for_ssh_retries_until_success(monkeypatch):
    attempts = [
        MODULE.subprocess.TimeoutExpired(cmd="ssh", timeout=1),
        MODULE.subprocess.CompletedProcess(args=[], returncode=255, stdout="", stderr=""),
        MODULE.subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ]

    def fake_run_ssh(*args, **kwargs):
        outcome = attempts.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    timeline = [0, 0, 1, 2]

    def fake_monotonic():
        return timeline.pop(0)

    args = SimpleNamespace(connect_timeout=1, poll_interval=0)
    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_: None)
    monkeypatch.setattr(MODULE.time, "monotonic", fake_monotonic)

    MODULE.wait_for_ssh("pi.local", args, timeout=3)


def test_wait_for_ssh_raises_after_timeout(monkeypatch):
    def fake_run_ssh(*_, **__):
        return MODULE.subprocess.CompletedProcess(args=[], returncode=255, stdout="", stderr="")

    timeline = [0, 0, 1, 2, 3, 4]

    def fake_monotonic():
        return timeline.pop(0)

    args = SimpleNamespace(connect_timeout=1, poll_interval=0)
    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_: None)
    monkeypatch.setattr(MODULE.time, "monotonic", fake_monotonic)

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.wait_for_ssh("pi.local", args, timeout=3)


def test_main_records_post_reboot_failures(monkeypatch, capsys):
    host = "pi.local"
    success = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])

    def fake_run_verifier(requested_host, args):
        return success

    def fake_wait_for_ssh(*_, **__):
        raise MODULE.SmokeTestError("never came back")

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", lambda *_, **__: None)
    monkeypatch.setattr(MODULE, "wait_for_ssh", fake_wait_for_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_: None)

    exit_code = MODULE.main([host, "--reboot", "--json"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "ERROR after reboot" in captured.err

    json_start = captured.out.index("{")
    payload = json.loads(captured.out[json_start:])
    assert payload["results"][1]["phase"] == "post-reboot"
    assert payload["results"][1]["error"] == "never came back"


def test_format_summary_includes_counts():
    result = MODULE.SmokeTestResult(
        host="pi.local",
        checks=[],
        passes=2,
        total=3,
        failures=[{"name": "one"}],
    )

    summary = MODULE.format_summary(result)
    assert "PASS" not in summary  # because failures exist
    assert "FAIL" in summary
    assert "2/3" in summary


def test_main_handles_reboot_failure(monkeypatch, capsys):
    host = "pi.local"
    summary = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])

    def fake_run_verifier(requested_host, args):
        assert requested_host == host
        summary.host = requested_host
        return summary

    def fake_trigger_reboot(requested_host, args):
        raise MODULE.SmokeTestError("reboot failed")

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", fake_trigger_reboot)
    monkeypatch.setattr(MODULE, "wait_for_ssh", lambda *_, **__: None)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_, **__: None)

    exit_code = MODULE.main([host, "--reboot", "--json"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "ERROR during reboot" in captured.err

    json_start = captured.out.index("{")
    payload = json.loads(captured.out[json_start:])
    assert payload["results"][0]["host"] == host
    assert payload["results"][1]["phase"] == "reboot"
    assert payload["results"][1]["error"] == "reboot failed"
