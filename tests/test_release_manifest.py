"""Focused DSPACE release-manifest contract tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import release_manifest as rm

SHA = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "sha256:" + "a" * 64
CHART_DIGEST = "sha256:" + "b" * 64


def upstream() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "app": "dspace",
        "applicationVersion": "3.1.0",
        "sourceRevision": SHA,
        "imageTag": "main-0123456",
        "imageDigest": DIGEST,
        "chartVersion": "3.1.1",
        "chartDigest": CHART_DIGEST,
        "semanticTag": "v3.1.0",
    }


def candidate(**changes: object) -> dict[str, object]:
    value = {
        **upstream(),
        "environment": "staging",
        "expectedDefaultChatProvider": "token-place",
        "approvedAt": "2026-07-24T12:34:56Z",
        "approvedBy": "synthetic-test-approver",
    }
    value.update(changes)
    return value


def completed(stdout: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, "stub failure" if code else "")


def test_upstream_candidate_canonical_round_trip(tmp_path: Path) -> None:
    source, output = tmp_path / "upstream.json", tmp_path / "candidate.json"
    source.write_text(json.dumps(upstream()), encoding="utf-8")
    assert (
        rm.main(
            [
                "candidate",
                "--upstream",
                str(source),
                "--environment",
                "staging",
                "--expected-default-chat-provider",
                "token-place",
                "--approved-at",
                "2026-07-24T12:34:56Z",
                "--approved-by",
                "operator",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_text() == rm.canonical(rm.validate(json.loads(output.read_text())))
    assert rm.main(["validate", str(output)]) == 0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"sourceRevision": "0123456"}, "full lowercase"),
        ({"sourceRevision": SHA.upper()}, "full lowercase"),
        ({"imageTag": "latest"}, "immutable"),
        ({"imageTag": "v3.1.0"}, "immutable"),
        ({"imageTag": "main-abcdef0"}, "matching"),
        ({"imageDigest": "sha256:abc"}, "sha256"),
        ({"chartDigest": "sha256:abc"}, "sha256"),
        ({"chartVersion": "v3.1.0"}, "SemVer"),
        ({"environment": "production"}, "staging or prod"),
        ({"expectedDefaultChatProvider": "tokenplace"}, "openai or token-place"),
        ({"approvedBy": ""}, "non-empty"),
    ],
)
def test_strict_candidate_failures(change: dict[str, object], message: str) -> None:
    with pytest.raises(rm.ManifestError, match=message):
        rm.validate(candidate(**change))


def test_missing_and_unknown_fields() -> None:
    value = candidate()
    del value["chartDigest"]
    with pytest.raises(rm.ManifestError, match="missing fields"):
        rm.validate(value)
    with pytest.raises(rm.ManifestError, match="unknown fields"):
        rm.validate({**candidate(), "token": "secret"})


def test_preflight_success_and_command_order() -> None:
    calls: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:2] == ["crane", "digest"]:
            return completed(DIGEST + "\n")
        if command[:2] == ["crane", "config"]:
            return completed(
                json.dumps({"config": {"Labels": {"org.opencontainers.image.revision": SHA}}})
            )
        return completed(
            json.dumps(
                {"digest": CHART_DIGEST, "annotations": {"org.opencontainers.image.revision": SHA}}
            )
        )

    rm.preflight(candidate(), runner)
    assert [call[:2] for call in calls] == [
        ["crane", "digest"],
        ["crane", "config"],
        ["oras", "manifest"],
    ]


@pytest.mark.parametrize(
    "failure", ["image-digest", "image-revision", "chart-digest", "chart-revision"]
)
def test_preflight_mismatches_fail(failure: str) -> None:
    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["crane", "digest"]:
            return completed((CHART_DIGEST if failure == "image-digest" else DIGEST) + "\n")
        if command[:2] == ["crane", "config"]:
            return completed(
                json.dumps(
                    {
                        "config": {
                            "Labels": {
                                "org.opencontainers.image.revision": (
                                    "f" * 40 if failure == "image-revision" else SHA
                                )
                            }
                        }
                    }
                )
            )
        return completed(
            json.dumps(
                {
                    "digest": DIGEST if failure == "chart-digest" else CHART_DIGEST,
                    "annotations": {
                        "org.opencontainers.image.revision": (
                            "f" * 40 if failure == "chart-revision" else SHA
                        )
                    },
                }
            )
        )

    with pytest.raises(rm.ManifestError):
        rm.preflight(candidate(), runner)


def test_multi_pod_finalize_and_mismatch() -> None:
    pods = {
        "items": [
            {
                "metadata": {"name": name},
                "status": {
                    "startTime": start,
                    "containerStatuses": [
                        {"imageID": f"ghcr.io/democratizedspace/dspace@{digest}"}
                    ],
                },
            }
            for name, start, digest in [
                ("dspace-b", "2026-07-24T12:02:00Z", DIGEST),
                ("dspace-a", "2026-07-24T12:01:00Z", DIGEST),
            ]
        ]
    }
    record = rm.finalize(
        candidate(),
        {"version": 7},
        pods,
        [{"name": "health", "passed": True, "details": "synthetic"}],
    )
    assert [pod["name"] for pod in record["pods"]] == ["dspace-a", "dspace-b"]
    pods["items"][0]["status"]["containerStatuses"][0]["imageID"] = "image@sha256:" + "c" * 64
    with pytest.raises(rm.ManifestError, match="does not match"):
        rm.finalize(
            candidate(),
            {"version": 7},
            pods,
            [{"name": "health", "passed": True, "details": "synthetic"}],
        )


def test_atomic_output_and_overwrite_refusal(tmp_path: Path) -> None:
    output = tmp_path / "evidence" / "record.json"
    rm.atomic_create(output, candidate())
    assert output.read_text() == rm.canonical(candidate())
    with pytest.raises(rm.ManifestError, match="overwrite"):
        rm.atomic_create(output, candidate())
    assert not list(output.parent.glob(f".{output.name}.*"))


def test_schema_excludes_credentials() -> None:
    text = rm.canonical(candidate())
    excluded = ("pass" + "word", "credential", "private token")
    assert all(word not in text.lower() for word in excluded)
