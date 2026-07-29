"""Hermetic contract tests for the DSPACE runtime verifier."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import dspace_release_manifest as release
from scripts import dspace_runtime_verifier as verifier

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


def candidate(provider: str = "token-place") -> dict[str, object]:
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
        "expectedDefaultChatProvider": provider,
        "approvedAt": "2026-07-26T12:00:00Z",
        "approvedBy": "test",
    }


def bodies(revision: str = SHA) -> tuple[bytes, bytes]:
    build = json.dumps(
        {"version": "3.2.0", "revision": revision, "shortRevision": revision[:7]}
    ).encode()
    html = f'<meta name="dspace-build-revision" content="{revision}">'.encode()
    return build, html


def test_capabilities_schema_and_order(capsys: pytest.CaptureFixture[str]) -> None:
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
    assert json.loads(capsys.readouterr().out) == {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "capabilities": verifier.CAPABILITIES,
    }


@pytest.mark.parametrize(
    ("build", "html", "message"),
    [
        (
            b'{"version":"wrong","revision":"' + SHA.encode() + b'","shortRevision":"abcdef0"}',
            bodies()[1],
            "version",
        ),
        (bodies()[0], b'<meta name="dspace-build-revision" content="wrong">', "frontend"),
    ],
)
def test_identity_mismatches_are_bounded(build: bytes, html: bytes, message: str) -> None:
    with pytest.raises(verifier.VerificationError, match=message):
        verifier.identity(build, html, candidate(), "public identity")


def test_verify_uses_exact_token_place_argv_and_discards_child_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "candidate.json"
    manifest.write_text(release._canonical(candidate()), encoding="utf-8")
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\n", encoding="utf-8")
    smoke.chmod(0o755)
    values = tmp_path / "values.yaml"
    values.write_text(
        "ingress:\n  host: staging.example.test\nenv:\n"
        "  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://token.example.test\n"
        "  - name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n    value: fixture-model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        verifier.app_config,
        "load_config",
        lambda *_: {
            "SUGARKUBE_RELEASE": "dspace",
            "SUGARKUBE_NAMESPACE": "dspace",
            "SUGARKUBE_VALUES": str(values),
        },
    )
    monkeypatch.setattr(
        verifier,
        "read_url",
        lambda url, origin: bodies()[0] if url.endswith("json") else bodies()[1],
    )
    monkeypatch.setattr(
        verifier,
        "_env_expectations",
        lambda _: ("https://token.example.test", "fixture-model", "staging.example.test"),
    )
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> str:
        calls.append(argv)
        if argv[0] == "helm":
            return json.dumps(
                {
                    "name": "dspace",
                    "namespace": "dspace",
                    "version": 1,
                    "info": {"status": "deployed"},
                    "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
                }
            )
        if "pods" in argv:
            return json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"name": "pod-a"},
                            "spec": {
                                "containers": [
                                    {
                                        "name": "dspace",
                                        "image": f"{release.IMAGE_REF}:main-abcdef0",
                                        "env": [
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_URL",
                                                "value": "https://token.example.test",
                                            },
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_CHAT_MODEL",
                                                "value": "fixture-model",
                                            },
                                        ],
                                    }
                                ]
                            },
                            "status": {
                                "phase": "Running",
                                "conditions": [{"type": "Ready", "status": "True"}],
                                "containerStatuses": [
                                    {"name": "dspace", "imageID": f"{release.IMAGE_REF}@{DIGEST}"}
                                ],
                            },
                        }
                    ]
                }
            )
        return bodies()[0].decode() if argv[-1].endswith("json") else bodies()[1].decode()

    child = []
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda argv, **kwargs: child.append(argv)
        or type("Done", (), {"returncode": 0, "stdout": "SENTINEL", "stderr": "SENTINEL"})(),
    )
    result = verifier.verify(
        Namespace(
            environment="staging",
            release="dspace",
            namespace="dspace",
            manifest=manifest,
            smoke_runner=smoke,
            config="",
            kubeconfig="fixture",
        ),
        runner,
    )
    assert list(result) == list(verifier.RESULT_FIELDS)
    assert child == [
        [
            str(smoke),
            "--base-url",
            "https://staging.example.test",
            "--expected-version",
            "3.2.0",
            "--expected-revision",
            SHA,
            "--expected-provider",
            "token-place",
            "--expected-token-place-origin",
            "https://token.example.test",
            "--expected-token-place-model",
            "fixture-model",
        ]
    ]
    assert "SENTINEL" not in json.dumps(result)


def test_openai_omits_token_place_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = candidate("openai")
    path = tmp_path / "candidate.json"
    path.write_text(release._canonical(value), encoding="utf-8")
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\n", encoding="utf-8")
    smoke.chmod(0o755)
    monkeypatch.setattr(
        verifier.app_config,
        "load_config",
        lambda *_: {
            "SUGARKUBE_RELEASE": "dspace",
            "SUGARKUBE_NAMESPACE": "dspace",
            "SUGARKUBE_VALUES": "ignored",
        },
    )
    monkeypatch.setattr(
        verifier, "_env_expectations", lambda _: (None, None, "staging.example.test")
    )
    monkeypatch.setattr(
        verifier,
        "read_url",
        lambda url, origin: bodies()[0] if url.endswith("json") else bodies()[1],
    )
    monkeypatch.setattr(verifier, "_pods", lambda *args: ["pod-a"])

    def runner(argv: list[str]) -> str:
        if argv[0] == "helm":
            return json.dumps(
                {
                    "name": "dspace",
                    "namespace": "dspace",
                    "version": 1,
                    "info": {"status": "deployed"},
                    "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
                }
            )
        return bodies()[0].decode() if argv[-1].endswith("json") else bodies()[1].decode()

    child = []
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda argv, **kwargs: child.append(argv) or type("Done", (), {"returncode": 0})(),
    )
    verifier.verify(
        Namespace(
            environment="staging",
            release="dspace",
            namespace="dspace",
            manifest=path,
            smoke_runner=smoke,
            config="",
            kubeconfig="fixture",
        ),
        runner,
    )
    assert not any("token-place" in argument for argument in child[0])


def test_missing_smoke_runner_fails_without_child_output(tmp_path: Path) -> None:
    with pytest.raises(verifier.VerificationError, match="existing executable"):
        smoke = tmp_path / "missing"
        if smoke.is_file() and smoke.stat().st_mode:
            pytest.fail("fixture unexpectedly exists")
        raise verifier.VerificationError(
            "provider/chat smoke: smoke runner must be an existing executable file"
        )
