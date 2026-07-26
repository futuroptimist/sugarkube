from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import release_manifest as manifest

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
CHART_DIGEST = "sha256:" + "2" * 64


def upstream() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "app": "dspace",
        "applicationVersion": "3.2.0",
        "sourceRevision": SHA,
        "imageTag": "main-abcdef0",
        "imageDigest": DIGEST,
        "chartVersion": "3.2.1",
        "chartDigest": CHART_DIGEST,
        "semanticTag": "v3.2.0",
    }


def approved() -> dict[str, object]:
    return manifest.candidate(
        upstream(), "staging", "openai", "2026-07-26T12:00:00Z", "operator@example.test"
    )


def test_valid_import_has_canonical_round_trip() -> None:
    candidate = approved()
    assert json.loads(manifest.canonical(candidate)) == candidate
    assert manifest.canonical(candidate).endswith("\n")


@pytest.mark.parametrize("change", [{"extra": True}, {"sourceRevision": None}])
def test_unknown_and_missing_or_malformed_fields_fail(change: dict[str, object]) -> None:
    value = approved()
    if change["sourceRevision"] is None if "sourceRevision" in change else False:
        value.pop("sourceRevision")
    else:
        value.update(change)
    with pytest.raises(manifest.ManifestError):
        manifest.validate(value)


@pytest.mark.parametrize("tag", ["latest", "main", "v3.2.0", "staging-abcdef0", "main-deadbee"])
def test_mutable_semantic_environment_and_mismatched_tags_fail(tag: str) -> None:
    value = approved()
    value["imageTag"] = tag
    with pytest.raises(manifest.ManifestError, match="imageTag"):
        manifest.validate(value)


def test_wrong_environment_provider_and_approver_fail() -> None:
    for key, value in (
        ("environment", "dev"),
        ("expectedDefaultChatProvider", "tokenplace"),
        ("approvedBy", ""),
    ):
        candidate = approved()
        candidate[key] = value
        with pytest.raises(manifest.ManifestError):
            manifest.validate(candidate)


def runner_for(image_digest: str = DIGEST, revision: str = SHA, chart_digest: str = CHART_DIGEST):
    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        payload = (
            {"Digest": image_digest, "Labels": {"org.opencontainers.image.revision": revision}}
            if command[0] == "skopeo"
            else {
                "digest": chart_digest,
                "annotations": {"org.opencontainers.image.revision": revision},
            }
        )
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    return calls, run


def test_preflight_success_order_and_mismatches() -> None:
    calls, runner = runner_for()
    manifest.preflight(approved(), "example/dspace", "example/charts/dspace", runner)
    assert [call[0] for call in calls] == ["skopeo", "oras"]
    for kwargs, message in (
        ({"image_digest": "sha256:" + "9" * 64}, "image digest"),
        ({"chart_digest": "sha256:" + "9" * 64}, "chart digest"),
        ({"revision": "0" * 40}, "source-revision"),
    ):
        _, bad_runner = runner_for(**kwargs)
        with pytest.raises(manifest.ManifestError, match=message):
            manifest.preflight(approved(), "image", "chart", bad_runner)


def test_multi_pod_finalize_and_image_mismatch() -> None:
    pods = {
        "items": [
            {
                "metadata": {"name": "dspace-a"},
                "status": {
                    "startTime": "2026-07-26T12:01:00Z",
                    "containerStatuses": [{"imageID": "ghcr.io/example/dspace@" + DIGEST}],
                },
            },
            {
                "metadata": {"name": "dspace-b"},
                "status": {
                    "startTime": "2026-07-26T12:02:00Z",
                    "containerStatuses": [{"imageID": "ghcr.io/example/dspace@" + DIGEST}],
                },
            },
        ]
    }
    final = manifest.finalize(
        approved(),
        {"version": 7},
        pods,
        [{"name": "rollout", "passed": True, "details": "complete"}],
        SHA,
    )
    assert [pod["name"] for pod in final["pods"]] == ["dspace-a", "dspace-b"]
    pods["items"][1]["status"]["containerStatuses"][0]["imageID"] = "image@sha256:" + "9" * 64
    with pytest.raises(manifest.ManifestError, match="pod imageID"):
        manifest.finalize(
            approved(),
            {"version": 7},
            pods,
            [{"name": "rollout", "passed": True, "details": "complete"}],
            SHA,
        )


def test_atomic_write_refuses_overwrite_and_contains_no_token(tmp_path: Path) -> None:
    output = tmp_path / "record.json"
    manifest.write_atomic(output, approved())
    assert "token" not in output.read_text(encoding="utf-8").lower()
    with pytest.raises(manifest.ManifestError, match="overwrite"):
        manifest.write_atomic(output, approved())
