import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

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


def test_parse_verifier_output_requires_checks_array():
    payload = {"checks": ["bad", "data"]}
    output = json.dumps(payload)
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.parse_verifier_output(output)


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
    args = argparse.Namespace(
        skip_token_place=True,
        token_place_url="https://example.invalid",
        skip_dspace=True,
        dspace_url="https://example.invalid",
    )
    env = MODULE.build_env(args)
    assert env["TOKEN_PLACE_HEALTH_URL"] == "skip"
    assert env["DSPACE_HEALTH_URL"] == "skip"


def test_build_env_uses_overrides():
    args = argparse.Namespace(
        skip_token_place=False,
        token_place_url="https://token.place",
        skip_dspace=False,
        dspace_url="https://dspace",
    )
    env = MODULE.build_env(args)
    assert env["TOKEN_PLACE_HEALTH_URL"] == "https://token.place"
    assert env["DSPACE_HEALTH_URL"] == "https://dspace"


def test_build_ssh_command_includes_identity_and_options():
    args = argparse.Namespace(
        user="pi",
        port=2222,
        connect_timeout=5,
        ssh_option=["StrictHostKeyChecking=yes"],
        identity="/tmp/key",
    )
    command = MODULE.build_ssh_command("host", args, "echo hi")
    assert "-i" in command
    assert "/tmp/key" in command
    assert "StrictHostKeyChecking=yes" in command
    assert command[-1] == "echo hi"


def _namespace_for_run():
    return argparse.Namespace(
        user="pi",
        port=22,
        connect_timeout=5,
        ssh_option=[],
        identity=None,
        command_timeout=30,
        verifier_path="/usr/local/sbin/pi_node_verifier.sh",
        token_place_url=None,
        skip_token_place=False,
        dspace_url=None,
        skip_dspace=False,
        no_sudo=False,
        poll_interval=0,
        reboot_timeout=10,
    )


def test_run_verifier_builds_expected_command(monkeypatch):
    args = _namespace_for_run()
    payload = {"checks": [{"name": "ok", "status": "pass"}]}
    stdout = "log line\n" + json.dumps(payload)

    def fake_run_ssh(host, received_args, remote_command, timeout):
        assert host == "pi.local"
        assert received_args is args
        assert "sudo -n" in remote_command
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    result = MODULE.run_verifier("pi.local", args)
    assert result.host == "pi.local"
    assert result.passes == 1


def test_run_verifier_raises_on_timeout(monkeypatch):
    args = _namespace_for_run()

    def fake_run_ssh(*_, **__):
        raise subprocess.TimeoutExpired(cmd=["ssh"], timeout=args.command_timeout)

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.run_verifier("pi.local", args)


def test_run_verifier_raises_on_failure(monkeypatch):
    args = _namespace_for_run()

    def fake_run_ssh(*_, **__):
        return subprocess.CompletedProcess([], 1, stdout="", stderr="boom")

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    with pytest.raises(MODULE.SmokeTestError) as excinfo:
        MODULE.run_verifier("pi.local", args)
    assert "boom" in str(excinfo.value)


class _FakeTime:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        value = self.now
        self.now += 1
        return value

    def sleep(self, interval):
        self.now += interval


def _wait_args():
    return argparse.Namespace(
        user="pi",
        port=22,
        connect_timeout=1,
        ssh_option=[],
        identity=None,
        poll_interval=0,
        no_sudo=False,
    )


def test_wait_for_ssh_eventually_succeeds(monkeypatch):
    args = _wait_args()
    attempts = []

    def fake_run_ssh(host, received_args, remote_command, timeout):
        attempts.append(remote_command)
        if len(attempts) < 2:
            return subprocess.CompletedProcess([], 255, "", "")
        return subprocess.CompletedProcess([], 0, "", "")

    fake_time = _FakeTime()
    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    monkeypatch.setattr(MODULE.time, "monotonic", fake_time.monotonic)
    monkeypatch.setattr(MODULE.time, "sleep", fake_time.sleep)

    MODULE.wait_for_ssh("pi.local", args, timeout=5)
    assert len(attempts) >= 2


def test_wait_for_ssh_times_out(monkeypatch):
    args = _wait_args()

    def fake_run_ssh(*_, **__):
        return subprocess.CompletedProcess([], 255, "", "")

    fake_time = _FakeTime()
    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    monkeypatch.setattr(MODULE.time, "monotonic", fake_time.monotonic)
    monkeypatch.setattr(MODULE.time, "sleep", fake_time.sleep)

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.wait_for_ssh("pi.local", args, timeout=2)


def test_trigger_reboot_allows_ssh_exit_255(monkeypatch):
    args = _wait_args()

    def fake_run_ssh(*_, **__):
        return subprocess.CompletedProcess([], 255, "", "")

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    MODULE.trigger_reboot("pi.local", args)


def test_trigger_reboot_raises_on_failure(monkeypatch):
    args = _wait_args()

    def fake_run_ssh(*_, **__):
        return subprocess.CompletedProcess([], 42, "", "bad")

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.trigger_reboot("pi.local", args)


def test_main_handles_success_without_reboot(monkeypatch, capsys):
    host = "pi.local"
    summary = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])

    def fake_run_verifier(requested_host, args):
        assert requested_host == host
        return summary

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    exit_code = MODULE.main([host, "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "PASS" in captured.out
    json_start = captured.out.index("{")
    payload = json.loads(captured.out[json_start:])
    assert payload["results"][0]["passes"] == 1


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


def test_main_records_post_reboot_failures(monkeypatch, capsys):
    host = "pi.local"
    summary = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])
    failing = MODULE.SmokeTestResult(
        host=host,
        checks=[],
        passes=0,
        total=1,
        failures=[{"name": "bad"}],
    )

    responses = [summary, failing]

    def fake_run_verifier(requested_host, args):
        assert requested_host == host
        return responses.pop(0)

    def fake_trigger_reboot(*_, **__):
        return None

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", fake_trigger_reboot)
    monkeypatch.setattr(MODULE, "wait_for_ssh", lambda *_, **__: None)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_, **__: None)

    exit_code = MODULE.main([host, "--reboot", "--json"])
    assert exit_code == 1
    captured = capsys.readouterr()
    json_start = captured.out.index("{")
    payload = json.loads(captured.out[json_start:])
    phases = [entry.get("phase") for entry in payload["results"] if "phase" in entry]
    assert "post-reboot" in phases
