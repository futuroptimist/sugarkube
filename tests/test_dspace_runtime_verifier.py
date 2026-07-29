"""Hermetic contract tests for the DSPACE runtime verifier."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


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
    value = json.loads(capsys.readouterr().out)
    assert value == {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "capabilities": [
            "applicationVersion",
            "runtimeSourceRevision",
            "frontendSourceRevision",
            "defaultProvider",
            "publicJourneys",
        ],
    }


def test_values_chain_uses_last_reviewed_token_place_values(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "env:\n  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://old.invalid\n", encoding="utf-8"
    )
    overlay.write_text(
        "env:\n  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://staging.token.place\n"
        "  - name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n    value: reviewed-model\n"
        "  - name: UNRELATED_SETTING\n    value: ignored-value\n",
        encoding="utf-8",
    )
    assert verifier.environment_values([base, overlay]) == {
        "DSPACE_TOKEN_PLACE_URL": "https://staging.token.place",
        "DSPACE_TOKEN_PLACE_CHAT_MODEL": "reviewed-model",
    }


@pytest.mark.parametrize("provider", ["token-place", "openai"])
def test_smoke_is_exact_argv_and_child_output_is_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\n", encoding="utf-8")
    smoke.chmod(0o755)
    values = tmp_path / "values.yaml"
    values.write_text(
        "env:\n  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://token.place\n"
        "  - name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n    value: model-from-values\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = "SENTINEL_SECRET"
        stderr = "SENTINEL_SECRET"

    monkeypatch.setattr(
        verifier.subprocess, "run", lambda command, **_kwargs: calls.append(command) or Completed()
    )
    build = json.dumps({"version": "3.2.0", "revision": SHA, "shortRevision": SHA[:7]}).encode()
    html = f'<meta name="dspace-build-revision" content="{SHA}">'.encode()
    pod = {
        "metadata": {
            "name": "dspace-0",
            "ownerReferences": [
                {"kind": "ReplicaSet", "name": "dspace-rs", "controller": True}
            ],
        },
        "spec": {
            "containers": [
                {"name": "dspace", "image": "ghcr.io/democratizedspace/dspace:main-abcdef0"}
            ]
        },
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "dspace", "imageID": "repo@" + DIGEST}],
        },
    }

    def runner(command: list[str]) -> str:
        if command[0] == "helm":
            return json.dumps(
                {
                    "name": "dspace",
                    "namespace": "dspace",
                    "version": 7,
                    "info": {"status": "deployed"},
                    "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
                }
            )
        if "pods" in command:
            return json.dumps({"items": [pod]})
        if "replicasets,deployments" in command:
            return json.dumps(
                {
                    "items": [
                        {"kind": "Deployment", "metadata": {"name": "dspace"}},
                        {
                            "kind": "ReplicaSet",
                            "metadata": {
                                "name": "dspace-rs",
                                "ownerReferences": [
                                    {
                                        "kind": "Deployment",
                                        "name": "dspace",
                                        "controller": True,
                                    }
                                ],
                            },
                        },
                    ]
                }
            )
        if "deployment" in command:
            return json.dumps(
                {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "name": "dspace",
                                        "env": [
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_URL",
                                                "value": "https://token.place",
                                            },
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_CHAT_MODEL",
                                                "value": "model-from-values",
                                            },
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                }
            )
        return (
            json.dumps(json.loads(build))
            if command[-1].endswith("build-info.json")
            else html.decode()
        )

    args = Namespace(
        environment="staging",
        release="dspace",
        namespace="dspace",
        application_version="3.2.0",
        source_revision=SHA,
        provider=provider,
        image_tag="main-abcdef0",
        image_digest=DIGEST,
        host="example.test",
        chart_version="3.2.0",
        helm_revision=7,
        values=[values],
        smoke_runner=smoke,
        kubeconfig="fixture",
        pod_port=3000,
    )
    result = verifier.verify(
        args, runner, lambda url, _origin: build if url.endswith(".json") else html
    )
    assert result["journeys"][-1] == {"name": "/chat", "passed": True}
    smoke_call = calls[-1]
    assert smoke_call[0] == str(smoke)
    if provider == "token-place":
        assert smoke_call[-4:] == [
            "--expected-token-place-origin",
            "https://token.place",
            "--expected-token-place-model",
            "model-from-values",
        ]
    else:
        assert not any("token-place" in item for item in smoke_call)
    assert "SENTINEL_SECRET" not in json.dumps(result)


def test_identity_and_frontend_mismatches_are_bounded() -> None:
    with pytest.raises(verifier.VerificationError, match="version or revision mismatch"):
        verifier.identity(
            b'{"version":"wrong","revision":"x","shortRevision":"x"}',
            "3.2.0",
            SHA,
            "main-abcdef0",
            "public identity",
        )
    with pytest.raises(verifier.VerificationError, match="frontend revision marker mismatch"):
        verifier.marker(b"secret response without marker", SHA, "direct identity")
