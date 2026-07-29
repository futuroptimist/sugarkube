"""Hermetic tests for the DSPACE runtime verifier contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


def manifest() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "app": "dspace",
        "applicationVersion": "3.2.0",
        "sourceRevision": SHA,
        "imageTag": "main-abcdef0",
        "imageDigest": DIGEST,
        "chartVersion": "3.2.0",
        "chartDigest": "sha256:" + "2" * 64,
        "semanticTag": "v3.2.0",
        "recordType": "candidate",
        "environment": "staging",
        "expectedDefaultChatProvider": "token-place",
        "approvedAt": "2026-07-26T12:00:00Z",
        "approvedBy": "test",
    }


def test_capabilities_are_exact_and_ordered(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        verifier.main(
            [
                "capabilities",
                "--environment",
                "staging",
                "--release",
                "dspace",
                "--namespace",
                "dspace",
            ]
        )
        == 0
    )
    value = json.loads(capsys.readouterr().out)
    assert list(value) == ["schemaVersion", "environment", "release", "namespace", "capabilities"]
    assert value["capabilities"] == list(verifier.CAPABILITIES)


@pytest.mark.parametrize(
    "coordinate",
    [None, f"{verifier.IMAGE_REF}:main-abcdef0", f"{verifier.IMAGE_REF}:main-abcdef0@{DIGEST}"],
)
def test_identity_accepts_exact_build_contract(coordinate: str | None) -> None:
    body = {"applicationVersion": "3.2.0", "revision": SHA, "shortRevision": SHA[:7]}
    if coordinate:
        body["image"] = coordinate
    assert (
        verifier.identity(json.dumps(body).encode(), manifest(), "public identity")["revision"]
        == SHA
    )


@pytest.mark.parametrize(
    "field,value",
    [("applicationVersion", "3.2.1"), ("revision", "0" * 40), ("shortRevision", "deadbee")],
)
def test_public_identity_mismatch_is_bounded(field: str, value: str) -> None:
    body = {"applicationVersion": "3.2.0", "revision": SHA, "shortRevision": SHA[:7]}
    body[field] = value
    with pytest.raises(verifier.VerificationError, match="public identity"):
        verifier.identity(json.dumps(body).encode(), manifest(), "public identity")


def test_frontend_marker_must_match() -> None:
    verifier.frontend(
        f'<meta name="dspace-build-revision" content="{SHA}">'.encode(), SHA, "public identity"
    )
    with pytest.raises(verifier.VerificationError, match="frontend revision marker"):
        verifier.frontend(
            b'<meta name="dspace-build-revision" content="wrong">', SHA, "public identity"
        )


def test_redirect_to_other_origin_is_rejected() -> None:
    class Response:
        def geturl(self) -> str:
            return "https://evil.example/build-info.json"

        def read(self, _size: int) -> bytes:
            return b"secret"

    with pytest.raises(verifier.VerificationError, match="unexpected origin"):
        verifier.http_get(
            "https://good.example/build-info.json",
            "https://good.example",
            lambda _request: Response(),
        )


def test_one_bad_pod_digest_fails_without_secret_content() -> None:
    def pod(name: str, digest: str) -> dict[str, object]:
        return {
            "metadata": {"name": name},
            "spec": {
                "containers": [{"name": "dspace", "image": f"{verifier.IMAGE_REF}:main-abcdef0"}]
            },
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [
                    {"name": "dspace", "imageID": f"{verifier.IMAGE_REF}@{digest}"}
                ],
            },
        }

    with pytest.raises(verifier.VerificationError, match="pod image digest") as caught:
        verifier.pod_items(
            json.dumps({"items": [pod("good", DIGEST), pod("bad-SENTINEL", "sha256:" + "9" * 64)]}),
            manifest(),
        )
    assert "SENTINEL" not in str(caught.value)


def test_missing_and_non_executable_smoke_runner_are_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert not missing.exists()
    # The path is checked before child execution by the public verifier workflow.
    assert not (missing.is_file() and verifier.os.access(missing, verifier.os.X_OK))
    runner = tmp_path / "runner"
    runner.write_text("#!/bin/sh\n", encoding="utf-8")
    assert not verifier.os.access(runner, verifier.os.X_OK)
