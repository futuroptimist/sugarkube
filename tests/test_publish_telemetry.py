from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "publish_telemetry.py"
SPEC = importlib.util.spec_from_file_location("publish_telemetry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


def test_parse_verifier_output_filters_invalid_entries():
    payload = {
        "checks": [
            {"name": "ready", "status": "pass"},
            {"name": "projects", "status": "fail"},
            "skip-me",
            {"name": "broken"},
        ]
    }
    checks = MODULE.parse_verifier_output(json.dumps(payload))
    assert checks == [
        {"name": "ready", "status": "pass"},
        {"name": "projects", "status": "fail"},
    ]


def test_summarise_checks_reports_counts():
    checks = [
        {"name": "one", "status": "pass"},
        {"name": "two", "status": "fail"},
        {"name": "three", "status": "skip"},
        {"name": "four", "status": "weird"},
    ]
    summary = MODULE.summarise_checks(checks)
    assert summary["total"] == 4
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["other"] == 1
    assert summary["failed_checks"] == ["two"]


def test_hashed_identifier_uses_salt(monkeypatch):
    def fake_sources():
        return ["machine-id:abc", "cpu-serial:123"]

    monkeypatch.setattr(MODULE, "fingerprint_sources", fake_sources)
    no_salt = MODULE.hashed_identifier(salt="")
    salted = MODULE.hashed_identifier(salt="pepper")
    assert no_salt != salted
    assert len(no_salt) == 64
    assert len(salted) == 64


def test_build_payload_includes_summary_and_tags():
    checks = [
        {"name": "ready", "status": "pass"},
        {"name": "projects", "status": "fail"},
    ]
    env = {"kernel": "Linux 6.1"}
    payload = MODULE.build_payload(
        checks=checks,
        identifier="abc123",
        env_snapshot=env,
        errors=["verifier_timeout"],
        tags=["lab", "pi"],
    )
    assert payload["instance"] == {"id": "abc123"}
    assert payload["environment"] == env
    assert payload["errors"] == ["verifier_timeout"]
    assert payload["tags"] == ["lab", "pi"]
    summary = payload["verifier"]["summary"]
    assert summary["total"] == 2
    assert summary["failed_checks"] == ["projects"]
