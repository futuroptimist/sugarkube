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


def test_build_env_honours_overrides():
    args = MODULE.argparse.Namespace(
        skip_token_place=False,
        token_place_url="https://token.place",
        skip_dspace=True,
        dspace_url=None,
    )
    env = MODULE.build_env(args)
    assert env["TOKEN_PLACE_HEALTH_URL"] == "https://token.place"
    assert env["DSPACE_HEALTH_URL"] == "skip"


def test_build_ssh_command_includes_identity_and_options():
    args = MODULE.argparse.Namespace(
        user="pi",
        port=2222,
        connect_timeout=5,
        ssh_option=["StrictHostKeyChecking=yes", "LogLevel=ERROR"],
        identity="/tmp/id_ed25519",
    )
    command = MODULE.build_ssh_command("host", args, "echo hi")
    assert command[:10] == [
        "ssh",
        "-p",
        "2222",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
    ]
    assert "StrictHostKeyChecking=yes" in command
    assert "LogLevel=ERROR" in command
    assert command[-2:] == ["pi@host", "echo hi"]


def test_run_verifier_success(monkeypatch):
    stdout = json.dumps({"checks": [{"name": "test", "status": "pass"}]})
    completed = subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout=stdout, stderr="")

    def fake_run_ssh(host, args, remote_command, timeout):
        assert remote_command.endswith("--json --no-log")
        return completed

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    args = MODULE.argparse.Namespace(
        verifier_path="/usr/local/bin/verify",
        no_sudo=True,
        command_timeout=30,
        skip_token_place=False,
        token_place_url=None,
        skip_dspace=False,
        dspace_url=None,
    )

    result = MODULE.run_verifier("host", args)
    assert result.success
    assert result.passes == 1


def test_run_verifier_timeout(monkeypatch):
    def fake_run_ssh(host, args, remote_command, timeout):
        raise subprocess.TimeoutExpired(cmd=remote_command, timeout=timeout)

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    args = MODULE.argparse.Namespace(
        verifier_path="/bin/verify",
        no_sudo=False,
        command_timeout=5,
        skip_token_place=False,
        token_place_url=None,
        skip_dspace=False,
        dspace_url=None,
    )

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.run_verifier("host", args)


def test_run_verifier_nonzero(monkeypatch):
    completed = subprocess.CompletedProcess(args=["ssh"], returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(MODULE, "run_ssh", lambda *_, **__: completed)
    args = MODULE.argparse.Namespace(
        verifier_path="/bin/verify",
        no_sudo=False,
        command_timeout=5,
        skip_token_place=False,
        token_place_url=None,
        skip_dspace=False,
        dspace_url=None,
    )

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.run_verifier("host", args)


def test_wait_for_ssh_eventually_succeeds(monkeypatch):
    calls = {"count": 0}

    def fake_run_ssh(host, args, remote_command, timeout):
        calls["count"] += 1
        if calls["count"] < 3:
            return subprocess.CompletedProcess(args=[], returncode=255, stdout="", stderr="")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    timeline = iter([0, 1, 2, 3, 4])

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_, **__: None)
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: next(timeline))

    args = MODULE.argparse.Namespace(connect_timeout=1, poll_interval=0)
    MODULE.wait_for_ssh("host", args, timeout=5)
    assert calls["count"] == 3


def test_wait_for_ssh_times_out(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_ssh",
        lambda *_, **__: subprocess.CompletedProcess(args=[], returncode=255, stdout="", stderr=""),
    )
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_, **__: None)
    timeline = iter([0, 1, 2, 3, 4, 5, 6])
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: next(timeline))

    args = MODULE.argparse.Namespace(connect_timeout=1, poll_interval=0)
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.wait_for_ssh("host", args, timeout=5)


def test_trigger_reboot_accepts_255(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_ssh",
        lambda *_, **__: subprocess.CompletedProcess(args=[], returncode=255, stdout="", stderr=""),
    )
    args = MODULE.argparse.Namespace(connect_timeout=1, no_sudo=False)
    MODULE.trigger_reboot("host", args)


def test_trigger_reboot_raises(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_ssh",
        lambda *_, **__: subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="permission denied"
        ),
    )
    args = MODULE.argparse.Namespace(connect_timeout=1, no_sudo=True)
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.trigger_reboot("host", args)


def test_format_summary_reports_failures():
    result = MODULE.SmokeTestResult(
        host="host",
        checks=[{"name": "one", "status": "fail"}],
        passes=0,
        total=1,
        failures=[{"name": "one", "status": "fail"}],
    )
    summary = MODULE.format_summary(result)
    assert summary.startswith("[host] FAIL")


def test_main_handles_initial_failure(monkeypatch, capsys):
    def fake_run_verifier(host, args):
        raise MODULE.SmokeTestError("no ssh")

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    exit_code = MODULE.main(["pi.local", "--json"])
    assert exit_code == 1

    output = capsys.readouterr().out
    start = output.index("{")
    payload = json.loads(output[start:])
    assert payload["results"][0]["error"] == "no ssh"


def test_main_records_post_reboot_failure(monkeypatch, capsys):
    host = "pi.local"
    initial = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])

    def fake_run_verifier(requested_host, args):
        if not getattr(fake_run_verifier, "called", False):
            fake_run_verifier.called = True
            return initial
        raise MODULE.SmokeTestError("post reboot failed")

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", lambda *_, **__: None)
    monkeypatch.setattr(MODULE, "wait_for_ssh", lambda *_, **__: None)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_, **__: None)

    exit_code = MODULE.main([host, "--reboot", "--json"])
    assert exit_code == 1

    captured = capsys.readouterr()
    start = captured.out.index("{")
    payload = json.loads(captured.out[start:])
    assert payload["results"][1]["phase"] == "post-reboot"
    assert payload["results"][1]["error"] == "post reboot failed"


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
