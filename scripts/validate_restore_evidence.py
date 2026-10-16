#!/usr/bin/env python3
"""Check a sanitized evidence record offline; never certify a restore or open references."""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

GATES = (
    "backup_inventory",
    "backup_integrity",
    "backup_complete",
    "storage_independence",
    "access_without_api",
    "token_available",
    "token_matches_backup",
    "config_reviewed",
    "version_supported",
    "isolation",
    "all_servers_stopped",
    "seed_selection_approved",
    "reset_approved",
    "restore_completed",
    "seed_objects_verified",
    "peer_data_preserved",
    "peer_moves_approved",
    "sequential_rejoin",
    "membership_voters",
    "api",
    "addresses_tls",
    "leases_restarts",
    "pod_networking",
    "objects",
    "pvc_data",
    "application_journeys",
    "acknowledged_writes",
    "monitoring_reference",
    "rollback_reviewed",
    "operator_acceptance",
)
STATES = {"pass", "fail", "incomplete", "not_run", "interrupted", "not_applicable"}
ID = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
VERSION = r"v\d+\.\d+\.\d+\+k3s\d+"


def validate(record):
    """Return errors in declared evidence, without inspecting any underlying assets."""
    errors = []

    def require(ok, message):
        if not ok:
            errors.append(message)

    def fields(value, names, label):
        ok = isinstance(value, dict) and set(value) == set(names)
        require(ok, f"{label}: unexpected or missing fields")
        return value if isinstance(value, dict) else {}

    def matches(pattern, value):
        return isinstance(value, str) and re.fullmatch(pattern, value) is not None

    r = fields(
        record,
        (
            "schema_version",
            "origin",
            "qualification",
            "artifact",
            "backup",
            "seed",
            "recovery",
            "measurements",
            "gates",
        ),
        "record",
    )
    require(
        type(r.get("schema_version")) is int and r.get("schema_version") == 1,
        "schema_version: expected 1",
    )
    require(r.get("origin") in ("template", "synthetic", "operator_record"), "origin: invalid")
    require(
        r.get("qualification") == "not_qualified",
        "qualification: offline records must remain not_qualified",
    )
    artifact = fields(
        r.get("artifact"), ("id", "sha256", "backup_version", "restore_version"), "artifact"
    )
    require(matches(ID, artifact.get("id")), "artifact: missing sanitized artifact ID")
    require(matches(r"[0-9a-f]{64}", artifact.get("sha256")), "artifact: invalid SHA256")
    for key in ("backup_version", "restore_version"):
        require(matches(VERSION, artifact.get(key)), f"artifact: invalid {key}")
    require(
        artifact.get("backup_version") == artifact.get("restore_version"),
        "artifact: version mismatch",
    )
    backup = fields(r.get("backup"), ("id", "kind", "provenance_ref"), "backup")
    for key in ("id", "provenance_ref"):
        require(matches(ID, backup.get(key)), f"backup: missing sanitized {key}")
    require(backup.get("kind") == "scheduled_snapshot", "backup: scheduled snapshot required")
    seed = fields(r.get("seed"), ("selected", "decision_ref"), "seed")
    selected = seed.get("selected")
    require(
        isinstance(selected, list) and len(selected) == 1 and matches(ID, selected[0]),
        "seed: exactly one explicit sanitized seed ID required",
    )
    require(matches(ID, seed.get("decision_ref")), "seed: missing decision evidence")
    require(r.get("recovery") == "completed", "recovery: incomplete, not run or interrupted")
    measurements = fields(
        r.get("measurements"),
        (
            "recovered_through_utc",
            "incident_utc",
            "started_utc",
            "accepted_utc",
            "rpo_seconds",
            "rto_seconds",
            "rpo_objective_seconds",
            "rto_objective_seconds",
            "evidence_ref",
        ),
        "measurements",
    )
    require(matches(ID, measurements.get("evidence_ref")), "measurements: missing evidence")
    times = {}
    for key in ("recovered_through_utc", "incident_utc", "started_utc", "accepted_utc"):
        value = measurements.get(key)
        try:
            if not isinstance(value, str) or not value.endswith("Z"):
                raise ValueError
            times[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"measurements: invalid UTC {key}")
    for metric, start, end in (
        ("rpo", "recovered_through_utc", "incident_utc"),
        ("rto", "started_utc", "accepted_utc"),
    ):
        actual = measurements.get(f"{metric}_seconds")
        objective = measurements.get(f"{metric}_objective_seconds")
        valid = all(type(v) is int and v >= 0 for v in (actual, objective))
        require(valid, f"measurements: invalid {metric} seconds/objective")
        if valid:
            require(actual <= objective, f"measurements: {metric} objective exceeded")
            if start in times and end in times:
                require(
                    (times[end] - times[start]).total_seconds() == actual,
                    f"measurements: inconsistent {metric} timestamps",
                )
    gates = fields(r.get("gates"), GATES, "gates")
    for name in GATES:
        gate = fields(gates.get(name), ("status", "evidence_ref"), f"gate {name}")
        status = gate.get("status")
        require(isinstance(status, str) and status in STATES, f"gate {name}: invalid status")
        # Even not_applicable needs separate human review, never an automatic pass.
        require(status == "pass", f"gate {name}: evidence incomplete")
        require(matches(ID, gate.get("evidence_ref")), f"gate {name}: missing evidence reference")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(json.loads(args.manifest.read_text()))
    except (OSError, ValueError, TypeError):
        # Do not echo potentially sensitive file contents or locations.
        errors = ["Unable to read a valid JSON evidence record"]
    print(json.dumps({"record_complete": not errors, "live_qualified": False, "errors": errors}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
