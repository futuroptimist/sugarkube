"""Focused safety tests for the DSPACE manifest rollback operation."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts import dspace_manifest_rollback as rollback
from scripts import dspace_release_manifest as release

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
CHART_DIGEST = "sha256:" + "2" * 64


def final() -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "app": "dspace",
        "applicationVersion": "3.2.0",
        "sourceRevision": SHA,
        "imageTag": "main-abcdef0",
        "imageDigest": DIGEST,
        "chartVersion": "3.2.0",
        "chartDigest": CHART_DIGEST,
        "semanticTag": "v3.2.0",
        "recordType": "final",
        "environment": "staging",
        "expectedDefaultChatProvider": "token-place",
        "approvedAt": "2026-07-26T12:00:00Z",
        "approvedBy": "operator",
        "helmRevision": 4,
        "pods": [
            {
                "name": "dspace-old",
                "startTime": "2026-07-26T12:00:00Z",
                "imageID": "ghcr.io/democratizedspace/dspace@" + DIGEST,
            }
        ],
        "runtimeSourceRevision": SHA,
        "runtimeSourceRevisionMethod": release.RUNTIME_METHOD,
        "verificationResults": [],
    }
    checks = sorted(release.FINAL_FIXED_CHECKS) + ["imagePlatformSourceRevision[0]"]
    value["verificationResults"] = [
        {"check": check, "passed": True, "details": "verified"} for check in checks
    ]
    return release.validate(value, True)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(recordType="candidate"),
        lambda x: x.update(imageTag="latest"),
        lambda x: x.update(imageTag="v3.2.0"),
        lambda x: x.update(imageTag="main-deadbee"),
        lambda x: x.update(unknown=True),
    ],
)
def test_target_requires_strict_finalized_evidence(change) -> None:
    value = final()
    change(value)
    with pytest.raises(release.ManifestError):
        rollback.target_candidate(value)


def test_target_projection_preserves_immutable_coordinates() -> None:
    target = rollback.target_candidate(final())
    assert target["recordType"] == "candidate"
    assert target["imageTag"] == "main-abcdef0"
    assert target["chartDigest"] == CHART_DIGEST


def test_values_chain_is_ordered_hashed_and_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "one.yaml").write_text("one: 1\n")
    (tmp_path / "two.yaml").write_text("two: 2\n")
    paths, evidence = rollback.values_evidence("one.yaml,two.yaml", tmp_path)
    assert [path.name for path in paths] == ["one.yaml", "two.yaml"]
    assert [item["path"] for item in evidence] == ["one.yaml", "two.yaml"]
    assert all(len(item["sha256"]) == 64 for item in evidence)
    with pytest.raises(rollback.RollbackError, match="not readable"):
        rollback.values_evidence("one.yaml,missing.yaml", tmp_path)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda x: x["capabilities"].update(frontendSourceRevision=False), "every required"),
        (lambda x: x.update(extra=True), "missing or unknown"),
        (lambda x: x.update(schemaVersion=2), "incompatible"),
    ],
)
def test_verifier_capabilities_fail_closed(change, message: str) -> None:
    value = {
        "schemaVersion": 1,
        "capabilities": {name: True for name in rollback.VERIFY_CAPABILITIES},
    }
    change(value)
    with pytest.raises(rollback.RollbackError, match=message):
        rollback.validate_capabilities(value)


def verifier_result() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "applicationVersion": "3.2.0",
        "runtimeSourceRevision": SHA,
        "frontendSourceRevision": SHA,
        "defaultProvider": "token-place",
        "journeys": [{"name": "/healthz", "passed": True}, {"name": "/chat", "passed": True}],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtimeSourceRevision", "0" * 40),
        ("frontendSourceRevision", "0" * 40),
        ("defaultProvider", "openai"),
    ],
)
def test_verifier_rejects_identity_mismatch(field: str, value: str) -> None:
    result = verifier_result()
    result[field] = value
    with pytest.raises(rollback.RollbackError, match=field):
        rollback.validate_verifier_result(result, rollback.target_candidate(final()))


def test_verifier_rejects_failed_or_missing_chat_journey() -> None:
    result = verifier_result()
    result["journeys"][1]["passed"] = False
    with pytest.raises(rollback.RollbackError, match="journey failed"):
        rollback.validate_verifier_result(result, rollback.target_candidate(final()))
    result = verifier_result()
    result["journeys"] = result["journeys"][:1]
    with pytest.raises(rollback.RollbackError, match="/chat"):
        rollback.validate_verifier_result(result, rollback.target_candidate(final()))


def pod(uid: str = "new-uid", image_id: str = DIGEST, terminating: bool = False) -> dict:
    metadata = {"name": "dspace-new", "uid": uid}
    if terminating:
        metadata["deletionTimestamp"] = "2026-07-27T00:00:00Z"
    return {
        "items": [
            {
                "metadata": metadata,
                "spec": {
                    "containers": [
                        {"name": "dspace", "image": "ghcr.io/democratizedspace/dspace:main-abcdef0"}
                    ]
                },
                "status": {
                    "phase": "Running",
                    "startTime": "2026-07-27T00:00:00Z",
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "containerStatuses": [{"name": "dspace", "imageID": "repo@" + image_id}],
                },
            }
        ]
    }


def test_post_pods_reject_lingering_and_image_id_mismatch() -> None:
    target = rollback.target_candidate(final())
    with pytest.raises(rollback.RollbackError, match="terminating"):
        rollback.pod_identities(pod(terminating=True), target)
    with pytest.raises(rollback.RollbackError, match="imageID"):
        rollback.pod_identities(pod(image_id="sha256:" + "9" * 64), target)


def test_reservation_collision_and_non_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    _, sidecar = rollback.reserve(
        output, rollback.manifest_fingerprint(final()), "staging", "dspace", "dspace"
    )
    assert sidecar.exists()
    with pytest.raises(rollback.RollbackError, match="already reserved"):
        rollback.reserve(
            output, rollback.manifest_fingerprint(final()), "staging", "dspace", "dspace"
        )


def test_just_recipe_uses_upgrade_without_rollback_or_reuse_values() -> None:
    source = (Path(__file__).parents[1] / "scripts/dspace_manifest_rollback.py").read_text()
    assert '"upgrade",' in source
    assert '"--reuse-values"' not in source
    assert 'args.helm, "rollback"' not in source
    justfile = (Path(__file__).parents[1] / "justfile").read_text()
    assert "dspace-manifest-rollback env='staging'" in justfile


def test_preflight_missing_manifest_creates_no_reservation_or_mutation(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    args = argparse.Namespace(
        manifest=tmp_path / "missing.json",
        environment="staging",
        evidence=tmp_path / "evidence.json",
    )
    with pytest.raises(rollback.RollbackError, match="does not exist"):
        rollback.execute(args, lambda command: calls.append(command) or "")
    assert calls == []
    assert not release.reservation_path(args.evidence).exists()
