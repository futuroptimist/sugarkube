import importlib.util
import json
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


def test_trigger_reboot_timeout_translates_to_smoke_error(monkeypatch):
    def fake_run_ssh(*_args, **_kwargs):
        raise MODULE.subprocess.TimeoutExpired(cmd=["ssh"], timeout=5)

    monkeypatch.setattr(MODULE, "run_ssh", fake_run_ssh)

    with pytest.raises(MODULE.SmokeTestError) as excinfo:
        MODULE.trigger_reboot("pi", MODULE.argparse.Namespace(no_sudo=False, connect_timeout=5))

    assert "timed out" in str(excinfo.value)


def test_reboot_failure_is_captured(monkeypatch, capsys):
    def fake_run_verifier(host, args):
        return MODULE.SmokeTestResult(host, [], 1, 1, [])

    def fake_trigger_reboot(host, args):
        raise MODULE.SmokeTestError("sudo interaction required")

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", fake_trigger_reboot)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_args, **_kwargs: None)

    exit_code = MODULE.main(["--reboot", "--json", "pi"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ERROR during reboot" in captured.err

    start = captured.out.index("{")
    payload = json.loads(captured.out[start:])
    assert payload["results"][1]["phase"] == "reboot"
    assert "sudo interaction required" in payload["results"][1]["error"]
