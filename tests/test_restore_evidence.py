"""Synthetic records test bookkeeping only; no restore or secret access."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_restore_evidence import GATES, validate

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/restore_evidence_synthetic.json"
TEMPLATE = ROOT / "docs/k3s/restore-qualification.template.json"


@pytest.fixture
def record():
    return json.loads(FIXTURE.read_text())


def test_synthetic_record_is_complete_but_never_live_qualified(record):
    assert validate(record) == []
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_restore_evidence.py"), str(FIXTURE)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "record_complete": True,
        "live_qualified": False,
        "errors": [],
    }


def test_blank_template_explicitly_not_run():
    record = json.loads(TEMPLATE.read_text())
    assert record["recovery"] == "not_run"
    assert all(gate["status"] == "not_run" for gate in record["gates"].values())
    assert validate(record)


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize(
    "state", ["fail", "not_run", "incomplete", "interrupted", "not_applicable"]
)
def test_each_gate_fails_closed(record, gate, state):
    record["gates"][gate]["status"] = state
    assert validate(record)


@pytest.mark.parametrize("gate", GATES)
def test_each_gate_requires_evidence(record, gate):
    record["gates"][gate]["evidence_ref"] = None
    assert validate(record)
    del record["gates"][gate]
    assert validate(record)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("artifact", "restore_version", "v1.35.4+k3s1"),
        ("artifact", "sha256", "invalid"),
        ("artifact", "id", None),
        ("backup", "id", None),
        ("backup", "kind", "cold_backup"),
        ("backup", "provenance_ref", None),
        ("seed", "selected", []),
        ("seed", "selected", ["node-a", "node-b"]),
        ("seed", "decision_ref", None),
        ("measurements", "rpo_seconds", 599),
        ("measurements", "rto_seconds", True),
        ("measurements", "rpo_objective_seconds", 599),
        ("measurements", "rto_objective_seconds", 1799),
        ("measurements", "accepted_utc", None),
        ("measurements", "accepted_utc", "2026-10-01T00:45:00"),
        ("measurements", "recovered_through_utc", "2026-10-02T00:00:00Z"),
    ],
)
def test_invalid_prerequisites_and_measurements(record, section, key, value):
    record[section][key] = value
    assert validate(record)


@pytest.mark.parametrize("state", ["not_run", "incomplete", "interrupted", "failed"])
def test_recovery_must_be_completed(record, state):
    record["recovery"] = state
    assert validate(record)


@pytest.mark.parametrize("origin", ["synthetic", "template", "operator_record"])
def test_cannot_claim_live_qualification(record, origin):
    record["origin"] = origin
    record["qualification"] = "qualified"
    assert validate(record)


@pytest.mark.parametrize("value", [None, [], {}, "invalid", 1])
def test_malformed_records_rejected(value):
    assert validate(value)


def test_rejects_unknown_fields_and_private_reference_paths(record):
    record["token"] = "not-a-real-token"
    assert validate(record)
    del record["token"]
    record["backup"]["provenance_ref"] = "/private/backup"
    assert validate(record)


def test_cli_rejects_invalid_json_without_echoing_input(tmp_path):
    path = tmp_path / "record.json"
    path.write_text("invalid-content-not-to-echo")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_restore_evidence.py"), str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "invalid-content-not-to-echo" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["live_qualified"] is False


@pytest.mark.parametrize("section", ["artifact", "backup", "seed", "measurements", "gates"])
def test_every_required_field_is_required(record, section):
    for key in list(record[section]):
        value = record[section].pop(key)
        assert validate(record)
        record[section][key] = value


def test_recovery_cannot_precede_incident(record):
    record["measurements"].update(
        started_utc="2026-09-30T23:00:00Z", accepted_utc="2026-09-30T23:30:00Z"
    )
    assert validate(record)


def test_duplicate_json_fields_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    source = FIXTURE.read_text().replace(
        '"recovery": "completed"', '"recovery": "interrupted", "recovery": "completed"'
    )
    path.write_text(source)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_restore_evidence.py"), str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["record_complete"] is False
