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
