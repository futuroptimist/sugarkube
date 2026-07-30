import argparse
import json
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


def manifest(environment: str = "staging", provider: str = "token-place") -> dict[str, object]:
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
        "environment": environment,
        "expectedDefaultChatProvider": provider,
        "approvedAt": "2026-07-29T12:00:00Z",
        "approvedBy": "release-manager",
    }


def test_capabilities_schema_is_exact(capsys: pytest.CaptureFixture[str]) -> None:
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
        "capabilities": list(verifier.CAPABILITIES),
    }


def test_values_expectations_omit_token_place_for_openai(tmp_path: Path, monkeypatch) -> None:
    values = tmp_path / "values.yaml"
    values.write_text("ingress:\n  host: example.test\nenv: []\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "REPO_ROOT", tmp_path)
    assert verifier.expectations({"SUGARKUBE_VALUES": str(values)}, "openai") == (
        "example.test",
        None,
        None,
    )


def test_chat_argv_is_exact_and_child_output_is_not_returned(tmp_path: Path, monkeypatch) -> None:
    record = tmp_path / "manifest.json"
    record.write_text(json.dumps(manifest()), encoding="utf-8")
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\n", encoding="utf-8")
    smoke.chmod(0o755)
    values = tmp_path / "values.yaml"
    values.write_text(
        "ingress:\n  host: staging.example\nenv:\n"
        "- name: DSPACE_TOKEN_PLACE_URL\n  value: https://token.example\n"
        "- name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n  value: approved-model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        verifier.app_config,
        "load_config",
        lambda *_args: {"SUGARKUBE_VALUES": str(values)},
    )
    build = json.dumps({"version": "3.2.0", "revision": SHA, "shortRevision": SHA[:7]})
    html = f'<meta name="dspace-build-revision" content="{SHA}">'.encode()
    monkeypatch.setattr(
        verifier, "fetch", lambda url, _category: build.encode() if url.endswith("json") else html
    )
    calls: list[list[str]] = []

    def runner(command: list[str]) -> str:
        calls.append(command)
        if "deployment" in command:
            return json.dumps(
                {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "name": "dspace",
                                        "image": "ghcr.io/democratizedspace/dspace:main-abcdef0",
                                        "env": [
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_URL",
                                                "value": "https://token.example",
                                            },
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_CHAT_MODEL",
                                                "value": "approved-model",
                                            },
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                }
            )
        if "pods" in command:
            return json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"name": "dspace-1"},
                            "spec": {
                                "containers": [
                                    {
                                        "name": "dspace",
                                        "image": "ghcr.io/democratizedspace/dspace:main-abcdef0",
                                    }
                                ]
                            },
                            "status": {
                                "phase": "Running",
                                "conditions": [{"type": "Ready", "status": "True"}],
                                "containerStatuses": [
                                    {"name": "dspace", "imageID": "image@" + DIGEST}
                                ],
                            },
                        }
                    ]
                }
            )
        if command[-1].endswith("build-info.json"):
            return build
        if command[0] == str(smoke):
            return "SENTINEL-SECRET"
        return html.decode()

    args = argparse.Namespace(
        manifest=record,
        environment="staging",
        release="dspace",
        namespace="dspace",
        application_version=None,
        source_revision=None,
        provider=None,
        compare_manifest=None,
        smoke_runner=smoke,
        config="",
        kubeconfig="kubeconfig",
    )
    result = verifier.verify(args, runner)
    assert result["journeys"][-1] == {"name": "/chat", "passed": True}
    assert calls[-1] == [
        str(smoke),
        "--base-url",
        "https://staging.example",
        "--expected-version",
        "3.2.0",
        "--expected-revision",
        SHA,
        "--expected-provider",
        "token-place",
        "--expected-token-place-origin",
        "https://token.example",
        "--expected-token-place-model",
        "approved-model",
    ]
    assert "SENTINEL" not in json.dumps(result)
