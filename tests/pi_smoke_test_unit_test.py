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


def test_main_handles_reboot_trigger_errors(monkeypatch, capsys):
    result = MODULE.SmokeTestResult(
        host="pi",
        checks=[{"name": "one", "status": "pass"}],
        passes=1,
        total=1,
        failures=[],
    )

    monkeypatch.setattr(MODULE, "run_verifier", lambda host, args: result)
    monkeypatch.setattr(
        MODULE,
        "trigger_reboot",
        lambda host, args: (_ for _ in ()).throw(MODULE.SmokeTestError("reboot failed")),
    )
    monkeypatch.setattr(MODULE.time, "sleep", lambda _: None)

    exit_code = MODULE.main(["pi", "--reboot"])

    stderr = capsys.readouterr().err
    assert "ERROR after reboot" in stderr
    assert exit_code == 1
