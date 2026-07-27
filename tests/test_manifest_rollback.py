"""Focused unit tests for the DSPACE manifest rollback safety boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dspace_manifest_rollback as rollback
from scripts import dspace_release_manifest as manifest

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


def final(environment: str = "staging") -> dict[str, object]:
    value = manifest.candidate(
        {
            "schemaVersion": 1,
            "app": "dspace",
            "applicationVersion": "3.2.0",
            "sourceRevision": SHA,
            "imageTag": "main-abcdef0",
            "imageDigest": DIGEST,
            "chartVersion": "3.2.0",
            "chartDigest": "sha256:" + "2" * 64,
            "semanticTag": "v3.2.0",
        },
        environment,
        "token-place",
        "2026-07-26T12:00:00Z",
        "operator",
    )
    value.update(
        recordType="final",
        helmRevision=4,
        pods=[
            {"name": "dspace-a", "startTime": "2026-07-26T12:01:00Z", "imageID": "repo@" + DIGEST}
        ],
        runtimeSourceRevision=SHA,
        runtimeSourceRevisionMethod=manifest.RUNTIME_METHOD,
        verificationResults=[
            {"check": check, "passed": True, "details": "verified"}
            for check in sorted(manifest.FINAL_FIXED_CHECKS)
        ]
        + [{"check": "imagePlatformSourceRevision[0]", "passed": True, "details": "verified"}],
    )
    return manifest.validate(value, True)


def verifier_result(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "applicationVersion": "3.2.0",
        "runtimeSourceRevision": SHA,
        "frontendSourceRevision": SHA,
        "defaultProvider": "token-place",
        "journeys": [{"name": "home", "passed": True}, {"name": "chat", "passed": True}],
    }
    value.update(changes)
    return value


def test_final_projection_rejects_candidate() -> None:
    candidate = manifest.candidate_from_final(final())
    with pytest.raises(manifest.ManifestError, match="missing fields"):
        manifest.candidate_from_final(candidate)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("imageTag", "latest"),
        ("imageTag", "v3.2.0"),
        ("environment", "dev"),
        ("sourceRevision", "f" * 40),
    ],
)
def test_final_projection_rejects_mutable_or_inconsistent_coordinates(
    field: str, value: str
) -> None:
    target = final()
    target[field] = value
    with pytest.raises(manifest.ManifestError):
        manifest.candidate_from_final(target)


def test_values_chain_is_ordered_portable_and_hashed(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("one\n")
    (tmp_path / "b.yaml").write_text("two\n")
    paths, records = rollback.values_evidence("a.yaml,b.yaml", tmp_path)
    assert paths == [tmp_path / "a.yaml", tmp_path / "b.yaml"]
    assert [item["path"] for item in records] == ["a.yaml", "b.yaml"]
    assert all(len(item["sha256"]) == 64 for item in records)


def test_missing_values_file_fails() -> None:
    with pytest.raises(manifest.ManifestError, match="values file is unavailable"):
        rollback.values_evidence("missing.yaml", Path("/"))


@pytest.mark.parametrize(
    "changes",
    [
        {"runtimeSourceRevision": "f" * 40},
        {"frontendSourceRevision": "f" * 40},
        {"defaultProvider": "openai"},
        {"journeys": [{"name": "home", "passed": True}, {"name": "chat", "passed": False}]},
        {"extra": True},
    ],
)
def test_verifier_result_fails_closed(changes: dict[str, object]) -> None:
    with pytest.raises(manifest.ManifestError):
        rollback.validate_verifier_result(verifier_result(**changes), final())


def test_verifier_result_accepts_exact_contract() -> None:
    assert (
        rollback.validate_verifier_result(verifier_result(), final())["frontendSourceRevision"]
        == SHA
    )


def test_incompatible_capabilities_fail() -> None:
    with pytest.raises(manifest.ManifestError, match="exact capabilities"):
        rollback.validate_capabilities({"schemaVersion": 1, "capabilities": ["availability"]})


def test_reservation_collision_and_immutable_write(tmp_path: Path) -> None:
    output = tmp_path / "rollback.json"
    sidecar = rollback.reserve(output, "a" * 64, "invocation")
    assert sidecar.exists() and not output.exists()
    with pytest.raises(manifest.ManifestError, match="already reserved"):
        rollback.reserve(output, "a" * 64, "other")
    rollback.write_evidence(output, sidecar, {"schemaVersion": 1})
    assert json.loads(output.read_text()) == {"schemaVersion": 1}
    assert not sidecar.exists()
    with pytest.raises(manifest.ManifestError, match="overwrite"):
        rollback.reserve(output, "a" * 64, "third")


def test_missing_manifest_fails_before_reservation(tmp_path: Path) -> None:
    output = tmp_path / "rollback.json"
    assert (
        rollback.main(
            [
                "--environment",
                "staging",
                "--manifest",
                str(tmp_path / "missing.json"),
                "--evidence",
                str(output),
                "--verifier",
                str(tmp_path / "missing-verifier"),
                "--values",
                "missing.yaml",
                "--cluster-environment",
                "staging",
                "--kubeconfig",
                "unused",
            ]
        )
        == 1
    )
    assert not output.exists()
    assert not Path(str(output) + manifest.RESERVATION_SUFFIX).exists()


def test_pod_summary_uses_uid_start_time_and_all_coordinates() -> None:
    result = rollback.pods(
        {
            "items": [
                {
                    "metadata": {"name": "p", "uid": "u"},
                    "spec": {"containers": [{"image": "repo:tag"}]},
                    "status": {
                        "startTime": "time",
                        "containerStatuses": [{"imageID": "repo@" + DIGEST}],
                    },
                }
            ]
        }
    )
    assert result == [
        {
            "name": "p",
            "uid": "u",
            "startTime": "time",
            "terminating": False,
            "images": ["repo:tag"],
            "imageIDs": ["repo@" + DIGEST],
        }
    ]
