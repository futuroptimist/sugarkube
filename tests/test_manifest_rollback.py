"""Focused fail-closed tests for DSPACE manifest rollback primitives."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import dspace_manifest_rollback as rollback
from scripts import dspace_release_manifest as manifest

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


def final(environment: str = "staging") -> dict[str, object]:
    value = {
        "schemaVersion": 1,
        "app": "dspace",
        "applicationVersion": "3.2.0",
        "sourceRevision": SHA,
        "imageTag": "main-abcdef0",
        "imageDigest": DIGEST,
        "chartVersion": "3.2.0",
        "chartDigest": "sha256:" + "2" * 64,
        "semanticTag": "v3.2.0",
        "recordType": "final",
        "environment": environment,
        "expectedDefaultChatProvider": "token-place",
        "approvedAt": "2026-07-26T12:00:00Z",
        "approvedBy": "operator",
        "helmRevision": 7,
        "pods": [
            {"name": "dspace-old", "startTime": "2026-07-26T12:01:00Z", "imageID": "repo@" + DIGEST}
        ],
        "runtimeSourceRevision": SHA,
        "runtimeSourceRevisionMethod": manifest.RUNTIME_METHOD,
        "verificationResults": [
            {"check": name, "passed": True, "details": "verified"}
            for name in sorted(manifest.FINAL_FIXED_CHECKS)
        ]
        + [{"check": "imagePlatformSourceRevision[0]", "passed": True, "details": "verified"}],
    }
    return manifest.validate(value, True)


def verifier_result(**changes) -> dict[str, object]:
    value = {
        "schemaVersion": rollback.CAPABILITY_SCHEMA,
        "applicationVersion": "3.2.0",
        "runtimeSourceRevision": SHA,
        "frontendSourceRevision": SHA,
        "defaultProvider": "token-place",
        "journeys": [{"name": name, "passed": True} for name in rollback.REQUIRED_JOURNEYS],
    }
    value.update(changes)
    return value


def test_missing_manifest_and_candidate_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(rollback.RollbackError, match="cannot read"):
        rollback.load_target(tmp_path / "missing.json", "staging")
    value = final()
    value["recordType"] = "candidate"
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(value))
    with pytest.raises(rollback.RollbackError, match="finalized"):
        rollback.load_target(path, "staging")


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(imageTag="latest"),
        lambda x: x.update(imageTag="v3.2.0"),
        lambda x: x.update(imageTag="main-deadbee"),
        lambda x: x.update(extra="unknown"),
    ],
)
def test_strict_final_target_rejects_mutable_or_inconsistent_records(
    tmp_path: Path, change
) -> None:
    value = final()
    change(value)
    path = tmp_path / "target.json"
    path.write_text(json.dumps(value))
    with pytest.raises(rollback.RollbackError):
        rollback.load_target(path, "staging")


def test_wrong_environment_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "target.json"
    path.write_text(json.dumps(final("prod")))
    with pytest.raises(rollback.RollbackError, match="environment"):
        rollback.load_target(path, "staging")


def test_projection_reuses_candidate_validation() -> None:
    value = rollback.target_projection(final())
    assert value["recordType"] == "candidate" and value["imageTag"] == "main-abcdef0"


def test_production_confirmation_is_exact_and_staging_is_noninteractive() -> None:
    rollback.confirmation("prod", final("prod"), "DSPACE:prod:" + SHA)
    for wrong in ("", "yes", "DSPACE:prod:" + "0" * 40):
        with pytest.raises(rollback.RollbackError):
            rollback.confirmation("prod", final("prod"), wrong)
    with pytest.raises(rollback.RollbackError):
        rollback.confirmation("staging", final(), "yes")


def test_values_chain_is_ordered_hashed_and_requires_readable_portable_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.yaml").write_text("a: 1\n")
    (tmp_path / "b.yaml").write_text("b: 2\n")
    result = rollback.values_evidence({"SUGARKUBE_VALUES": "a.yaml,b.yaml"}, tmp_path)
    assert [item["path"] for item in result] == ["a.yaml", "b.yaml"]
    assert all(len(item["sha256"]) == 64 for item in result)
    with pytest.raises(rollback.RollbackError, match="missing"):
        rollback.values_evidence({"SUGARKUBE_VALUES": "missing.yaml"}, tmp_path)
    with pytest.raises(rollback.RollbackError, match="portable"):
        rollback.values_evidence({"SUGARKUBE_VALUES": "../secret"}, tmp_path)


def test_verifier_capabilities_require_executable_and_exact_contract(tmp_path: Path) -> None:
    verifier = tmp_path / "verify"
    verifier.write_text("#!/bin/sh\n")
    os.chmod(verifier, 0o755)
    good = {
        "schemaVersion": rollback.CAPABILITY_SCHEMA,
        "checks": [
            "applicationVersion",
            "runtimeSourceRevision",
            "frontendSourceRevision",
            "defaultProvider",
            *rollback.REQUIRED_JOURNEYS,
        ],
        "acceptsRequestOnStdin": True,
    }
    assert rollback.verifier_capabilities(verifier, lambda command: json.dumps(good)) == good
    with pytest.raises(rollback.RollbackError, match="unknown"):
        rollback.verifier_capabilities(verifier, lambda command: json.dumps({**good, "extra": 1}))
    with pytest.raises(rollback.RollbackError, match="available"):
        rollback.verifier_capabilities(tmp_path / "absent")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"runtimeSourceRevision": "0" * 40}, "runtimeSourceRevision"),
        ({"frontendSourceRevision": "0" * 40}, "frontendSourceRevision"),
        ({"defaultProvider": "openai"}, "defaultProvider"),
    ],
)
def test_verifier_identity_mismatches_fail(change, message) -> None:
    with pytest.raises(rollback.RollbackError, match=message):
        rollback.validate_verifier_result(verifier_result(**change), final())


def test_failed_or_unknown_public_journey_fails() -> None:
    value = verifier_result()
    value["journeys"][2]["passed"] = False
    with pytest.raises(rollback.RollbackError, match="journey failed"):
        rollback.validate_verifier_result(value, final())
    value = verifier_result()
    value["journeys"][2]["name"] = "availability"
    with pytest.raises(rollback.RollbackError, match="missing, unknown"):
        rollback.validate_verifier_result(value, final())


def test_reservation_is_exclusive_and_does_not_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "rollback.json"
    _, sidecar = rollback.reserve(output, final(), "staging")
    assert sidecar.exists() and not output.exists()
    with pytest.raises(rollback.RollbackError, match="already reserved"):
        rollback.reserve(output, final(), "staging")


def test_pod_identity_includes_uid_time_coordinates_and_ids() -> None:
    pods = {
        "items": [
            {
                "metadata": {"name": "p", "uid": "u"},
                "spec": {"containers": [{"name": "dspace", "image": "repo:tag"}]},
                "status": {
                    "phase": "Running",
                    "startTime": "time",
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "containerStatuses": [{"name": "dspace", "imageID": "repo@" + DIGEST}],
                },
            }
        ]
    }
    assert rollback.pod_identities(pods) == [
        {
            "name": "p",
            "uid": "u",
            "startTime": "time",
            "deletionTimestamp": None,
            "phase": "Running",
            "ready": True,
            "containers": [{"name": "dspace", "image": "repo:tag", "imageID": "repo@" + DIGEST}],
        }
    ]


def test_recipe_is_digest_upgrade_without_revision_rollback_or_reuse() -> None:
    source = Path("scripts/dspace_manifest_rollback.py").read_text()
    assert '"upgrade",' in source and '"dspace",' in source
    assert "--reuse-values" not in source and '"rollback"' not in source
    assert "release_manifest.chart_coordinate(projected)" in source
