import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
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


def test_parse_args_accepts_host_flag():
    args = MODULE.parse_args(["--host", "pi.local", "--json"])
    assert args.hosts == ["pi.local"]
    assert args.json is True


def test_parse_args_combines_positional_and_flag_hosts():
    args = MODULE.parse_args(["pi-a.local", "--host", "pi-b.local"])
    assert args.hosts == ["pi-a.local", "pi-b.local"]


def test_parse_args_requires_at_least_one_host():
    with pytest.raises(SystemExit) as excinfo:
        MODULE.parse_args([])
    assert excinfo.value.code == 2


def test_parse_verifier_output_errors_on_empty():
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.parse_verifier_output("\n \n")


def test_parse_verifier_output_discards_non_dict_entries():
    payload = {"checks": [{"name": "ok", "status": "pass"}, "nope"]}
    checks = MODULE.parse_verifier_output(json.dumps(payload))
    assert checks == [{"name": "ok", "status": "pass"}]


def test_parse_verifier_output_errors_when_all_entries_ignored():
    payload = {"checks": ["nope", 123, None]}
    with pytest.raises(MODULE.SmokeTestError):
        MODULE.parse_verifier_output(json.dumps(payload))


def test_build_env_handles_skip_and_overrides():
    args = SimpleNamespace(
        skip_token_place=True,
        token_place_url=None,
        skip_dspace=False,
        dspace_url="https://dspace.example/status",
    )
    env = MODULE.build_env(args)
    assert env["TOKEN_PLACE_HEALTH_URL"] == "skip"
    assert env["DSPACE_HEALTH_URL"] == "https://dspace.example/status"


def test_build_env_prefers_explicit_urls():
    args = SimpleNamespace(
        skip_token_place=False,
        token_place_url="https://token.place/health",
        skip_dspace=True,
        dspace_url=None,
    )
    env = MODULE.build_env(args)
    assert env["TOKEN_PLACE_HEALTH_URL"] == "https://token.place/health"
    assert env["DSPACE_HEALTH_URL"] == "skip"


def test_build_ssh_command_includes_options_and_identity():
    args = SimpleNamespace(
        user="pi",
        port=2222,
        connect_timeout=7,
        ssh_option=["StrictHostKeyChecking=no"],
        identity="~/.ssh/id_pi",
    )
    command = MODULE.build_ssh_command("pi.local", args, "echo hi")
    assert command[:3] == ["ssh", "-p", "2222"]
    assert "-i" in command and "~/.ssh/id_pi" in command
    assert command[-2:] == ["pi@pi.local", "echo hi"]


def test_run_ssh_invokes_subprocess(monkeypatch):
    args = SimpleNamespace(
        user="pi",
        port=22,
        connect_timeout=5,
        ssh_option=[],
        identity=None,
    )

    calls = {}

    def fake_run(cmd, *, capture_output, text, timeout):
        calls["cmd"] = cmd
        calls["kwargs"] = {
            "capture_output": capture_output,
            "text": text,
            "timeout": timeout,
        }
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    result = MODULE.run_ssh("pi.local", args, "echo hi", timeout=3)

    assert result.returncode == 0
    assert calls["cmd"][-2:] == ["pi@pi.local", "echo hi"]
    assert calls["kwargs"] == {"capture_output": True, "text": True, "timeout": 3}


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


def test_run_verifier_success(monkeypatch):
    args = SimpleNamespace(
        verifier_path="/bin/verifier",
        no_sudo=False,
        command_timeout=30,
        token_place_url=None,
        skip_token_place=False,
        dspace_url=None,
        skip_dspace=False,
    )

    completed = CompletedProcess(
        args=["ssh"],
        returncode=0,
        stdout=json.dumps({"checks": [{"name": "ping", "status": "pass"}]}),
        stderr="",
    )

    def fake_run_ssh(host, parsed_args, command, timeout):
        assert "sudo -n" in command
        return completed

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    result = MODULE.run_verifier("pi.local", args)
    assert result.success
    assert result.total == 1


def test_run_verifier_surfaces_failures(monkeypatch):
    args = SimpleNamespace(
        verifier_path="/bin/verifier",
        no_sudo=True,
        command_timeout=30,
        token_place_url=None,
        skip_token_place=False,
        dspace_url=None,
        skip_dspace=False,
    )

    failure = CompletedProcess(
        args=["ssh"],
        returncode=23,
        stdout="",
        stderr="boom",
    )

    monkeypatch.setattr(MODULE, "run_ssh", lambda *_, **__: failure)
    with pytest.raises(MODULE.SmokeTestError) as excinfo:
        MODULE.run_verifier("pi.local", args)
    assert "boom" in str(excinfo.value)


def test_run_verifier_times_out(monkeypatch):
    args = SimpleNamespace(
        verifier_path="/bin/verifier",
        no_sudo=False,
        command_timeout=30,
        token_place_url=None,
        skip_token_place=False,
        dspace_url=None,
        skip_dspace=False,
    )

    class Timeout(subprocess.TimeoutExpired):
        def __init__(self):
            super().__init__(cmd="ssh", timeout=30)

    def fake_run_ssh(*_, **__):
        raise Timeout()

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)

    with pytest.raises(MODULE.SmokeTestError) as excinfo:
        MODULE.run_verifier("pi.local", args)

    assert "timed out" in str(excinfo.value)


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


def test_wait_for_ssh_success_after_retry(monkeypatch):
    args = SimpleNamespace(connect_timeout=1, poll_interval=0)
    attempts = []

    def fake_run_ssh(host, parsed_args, command, timeout):
        attempts.append(command)
        return CompletedProcess(
            args=command,
            returncode=0 if len(attempts) > 1 else 1,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)

    timestamps = iter([0, 0.1, 0.2, 0.3])

    monkeypatch.setattr(MODULE.time, "monotonic", lambda: next(timestamps))
    MODULE.wait_for_ssh("pi.local", args, timeout=1)
    assert len(attempts) >= 2


def test_wait_for_ssh_recovers_from_timeout(monkeypatch):
    args = SimpleNamespace(connect_timeout=1, poll_interval=0)

    responses = [
        subprocess.TimeoutExpired(cmd="ssh", timeout=1),
        CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ]

    def fake_run_ssh(host, parsed_args, command, timeout):
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    timestamps = iter([0, 0.1, 0.2])

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: next(timestamps))
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_: None)

    MODULE.wait_for_ssh("pi.local", args, timeout=1)


def test_wait_for_ssh_times_out(monkeypatch):
    args = SimpleNamespace(connect_timeout=1, poll_interval=0)

    monkeypatch.setattr(
        MODULE,
        "run_ssh",
        lambda *_, **__: CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
    )

    timestamps = iter([0, 0.4, 0.8, 1.2])
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: next(timestamps))

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.wait_for_ssh("pi.local", args, timeout=1)


def test_trigger_reboot_accepts_255(monkeypatch):
    args = SimpleNamespace(connect_timeout=1, no_sudo=False)
    responses = iter(
        [
            CompletedProcess(args=[], returncode=255, stdout="", stderr="connection lost"),
        ]
    )
    monkeypatch.setattr(MODULE, "run_ssh", lambda *_, **__: next(responses))
    MODULE.trigger_reboot("pi.local", args)


def test_trigger_reboot_raises_for_other_codes(monkeypatch):
    args = SimpleNamespace(connect_timeout=1, no_sudo=True)

    response = CompletedProcess(args=[], returncode=17, stdout="", stderr="no perm")
    monkeypatch.setattr(MODULE, "run_ssh", lambda *_, **__: response)

    with pytest.raises(MODULE.SmokeTestError) as excinfo:
        MODULE.trigger_reboot("pi.local", args)

    assert "17" in str(excinfo.value)


def test_main_handles_initial_failure(monkeypatch, capsys):
    host = "pi.local"

    def fake_run_verifier(*_, **__):
        raise MODULE.SmokeTestError("connect failed")

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)

    exit_code = MODULE.main([host, "--json"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    start = captured.out.index("{")
    payload = json.loads(captured.out[start:])
    assert payload["results"][0]["error"] == "connect failed"


def test_main_records_failed_checks(monkeypatch, capsys):
    host = "pi.local"
    failing = MODULE.SmokeTestResult(
        host=host,
        checks=[{"name": "svc", "status": "fail"}],
        passes=0,
        total=1,
        failures=[{"name": "svc", "status": "fail"}],
    )

    monkeypatch.setattr(MODULE, "run_verifier", lambda *_: failing)

    exit_code = MODULE.main([host, "--json"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "FAIL" in captured.out
    start = captured.out.index("{")
    payload = json.loads(captured.out[start:])
    assert payload["results"][0]["failures"] == [{"name": "svc", "status": "fail"}]


def test_main_success_path_with_reboot(monkeypatch, capsys):
    host = "pi.local"
    first = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])
    second = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])

    calls = {"run_verifier": 0, "trigger_reboot": 0, "wait_for_ssh": 0}

    def fake_run_verifier(requested_host, args):
        calls["run_verifier"] += 1
        return first if calls["run_verifier"] == 1 else second

    def fake_trigger_reboot(requested_host, args):
        calls["trigger_reboot"] += 1

    def fake_wait_for_ssh(requested_host, args, timeout):
        calls["wait_for_ssh"] += 1

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", fake_trigger_reboot)
    monkeypatch.setattr(MODULE, "wait_for_ssh", fake_wait_for_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_, **__: None)

    exit_code = MODULE.main([host, "--reboot", "--json"])
    assert exit_code == 0
    assert calls == {"run_verifier": 2, "trigger_reboot": 1, "wait_for_ssh": 1}

    captured = capsys.readouterr()
    start = captured.out.index("{")
    payload = json.loads(captured.out[start:])
    assert payload["results"][0]["passes"] == 1


def test_main_handles_post_reboot_failure(monkeypatch, capsys):
    host = "pi.local"
    first = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])

    state = {"first": True}

    def fake_run_verifier(requested_host, args):
        if state["first"]:
            state["first"] = False
            return first
        raise MODULE.SmokeTestError("post reboot fail")

    def fake_wait_for_ssh(*_, **__):
        return None

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", lambda *_, **__: None)
    monkeypatch.setattr(MODULE, "wait_for_ssh", fake_wait_for_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_, **__: None)

    exit_code = MODULE.main([host, "--reboot", "--json"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "ERROR after reboot" in captured.err
    start = captured.out.index("{")
    payload = json.loads(captured.out[start:])
    assert payload["results"][1]["phase"] == "post-reboot"
    assert payload["results"][1]["error"] == "post reboot fail"


def test_main_records_post_reboot_failures(monkeypatch, capsys):
    host = "pi.local"
    first = MODULE.SmokeTestResult(host=host, checks=[], passes=1, total=1, failures=[])
    failing = MODULE.SmokeTestResult(
        host=host,
        checks=[{"name": "svc", "status": "fail"}],
        passes=0,
        total=1,
        failures=[{"name": "svc", "status": "fail"}],
    )

    calls = {"run_verifier": 0}

    def fake_run_verifier(requested_host, args):
        calls["run_verifier"] += 1
        return first if calls["run_verifier"] == 1 else failing

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", lambda *_, **__: None)
    monkeypatch.setattr(MODULE, "wait_for_ssh", lambda *_, **__: None)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_, **__: None)

    exit_code = MODULE.main([host, "--reboot", "--json"])
    assert exit_code == 1

    captured = capsys.readouterr()
    start = captured.out.index("{")
    payload = json.loads(captured.out[start:])
    assert payload["results"][1]["failures"] == [{"name": "svc", "status": "fail"}]
