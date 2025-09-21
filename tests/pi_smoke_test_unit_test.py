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


def test_reboot_failure_is_reported_and_does_not_abort(monkeypatch, capsys):
    def fake_run_verifier(host, args):
        return MODULE.SmokeTestResult(
            host,
            [{"name": "dummy", "status": "pass"}],
            1,
            1,
            [],
        )

    reboot_calls: list[str] = []

    def fake_trigger_reboot(host, args):
        reboot_calls.append(host)
        if host == "one":
            raise MODULE.SmokeTestError("reboot failed")

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "trigger_reboot", fake_trigger_reboot)
    monkeypatch.setattr(MODULE, "wait_for_ssh", lambda *args, **kwargs: None)
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_args, **_kwargs: None)

    exit_code = MODULE.main(["--reboot", "--json", "one", "two"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert reboot_calls == ["one", "two"]
    assert "[one] ERROR during reboot: reboot failed" in captured.err

    json_start = captured.out.index("{")
    json_text = captured.out[json_start:]
    payload = json.loads(json_text)

    assert any(
        entry == {"host": "one", "phase": "reboot", "error": "reboot failed"}
        for entry in payload["results"]
    )
    assert any(
        entry.get("host") == "two" and entry.get("phase") == "post-reboot"
        for entry in payload["results"]
    )
