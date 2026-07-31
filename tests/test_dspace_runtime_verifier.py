import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


def manifest(tmp_path: Path, provider: str = "token-place") -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "app": "dspace",
                "applicationVersion": "3.1.0",
                "sourceRevision": SHA,
                "imageTag": "main-abcdef0",
                "imageDigest": DIGEST,
                "chartVersion": "3.1.0",
                "chartDigest": "sha256:" + "2" * 64,
                "semanticTag": "v3.1.0",
                "recordType": "candidate",
                "environment": "staging",
                "expectedDefaultChatProvider": provider,
                "approvedAt": "2026-07-30T00:00:00Z",
                "approvedBy": "release-test",
            }
        )
    )
    return path


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
    assert list(value) == ["schemaVersion", "environment", "release", "namespace", "capabilities"]
    assert value["capabilities"] == verifier.CAPABILITIES


def test_values_expectations_use_ordered_overlay(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "env:\n- name: DSPACE_TOKEN_PLACE_URL\n  value: https://old.invalid\n- name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n  value: old\n"
    )
    overlay.write_text(
        "env:\n- name: DSPACE_TOKEN_PLACE_URL\n  value: https://token.example\n- name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n  value: current-model\n"
    )
    assert verifier.values_expectations([base, overlay]) == (
        "https://token.example",
        "current-model",
    )


@pytest.mark.parametrize("provider,has_token_args", [("token-place", True), ("openai", False)])
def test_verify_uses_safe_exact_smoke_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider: str, has_token_args: bool
) -> None:
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\nexit 0\n")
    smoke.chmod(0o700)
    pod = {
        "metadata": {"name": "dspace-1"},
        "spec": {
            "containers": [
                {
                    "name": "dspace",
                    "image": "ghcr.io/democratizedspace/dspace:main-abcdef0@sha256:1111111111111111111111111111111111111111111111111111111111111111",
                }
            ]
        },
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "dspace", "imageID": "containerd://x@" + DIGEST}],
        },
    }
    build = json.dumps(
        {
            "version": "3.1.0",
            "revision": SHA,
            "shortRevision": "abcdef0",
            "image": "ghcr.io/democratizedspace/dspace:main-abcdef0@sha256:1111111111111111111111111111111111111111111111111111111111111111",
        }
    )
    html = f'<meta name="dspace-build-revision" content="{SHA}">'

    def command(argv: list[str]) -> str:
        if argv and argv[0] == "helm":
            return json.dumps({"chart": "dspace-1.2.3", "version": 7})
        if "pods" in argv:
            return json.dumps({"items": [pod]})
        if "deployment" in argv:
            return json.dumps(
                {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "name": "dspace",
                                        "image": "ghcr.io/democratizedspace/dspace:main-abcdef0@sha256:1111111111111111111111111111111111111111111111111111111111111111",
                                        "env": [
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_URL",
                                                "value": "https://token.example",
                                            },
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_CHAT_MODEL",
                                                "value": "model-a",
                                            },
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                }
            )
        if argv[-1].endswith("build-info.json"):
            return build
        return html

    monkeypatch.setattr(verifier, "command", command)
    monkeypatch.setattr(
        verifier,
        "fetch",
        lambda url, origin: build.encode() if url.endswith(".json") else html.encode(),
    )
    monkeypatch.setattr(
        verifier.app_config, "load_config", lambda *args: {"SUGARKUBE_VALUES": "values.yaml"}
    )
    monkeypatch.setattr(verifier, "_resolve_host", lambda paths: "staging.example")
    monkeypatch.setattr(
        verifier, "values_expectations", lambda paths: ("https://token.example", "model-a")
    )
    seen = []

    class Completed:
        returncode = 0
        stdout = "SENTINEL_SECRET"
        stderr = "SENTINEL_SECRET"

    monkeypatch.setattr(
        verifier.subprocess, "run", lambda argv, **kwargs: seen.append(argv) or Completed()
    )
    args = Namespace(
        environment="staging",
        release="dspace",
        namespace="dspace",
        manifest=manifest(tmp_path, provider),
        application_version=None,
        source_revision=None,
        provider=None,
        config=None,
        host=None,
        smoke_runner=str(smoke),
        kubeconfig="kubeconfig",
    )
    result = verifier.verify(args)
    assert list(result) == list(verifier.RESULT_FIELDS)
    assert result["journeys"][-1] == {"name": "/chat", "passed": True}
    assert ("--expected-token-place-origin" in seen[-1]) is has_token_args
    assert "SENTINEL_SECRET" not in json.dumps(result)


def test_missing_or_nonexecutable_runner_fails_safely(tmp_path: Path) -> None:
    args = Namespace(
        environment="staging",
        release="dspace",
        namespace="dspace",
        manifest=manifest(tmp_path),
        application_version=None,
        source_revision=None,
        provider=None,
        config=None,
        host="staging.example",
        smoke_runner=str(tmp_path / "missing"),
        kubeconfig="k",
    )
    with pytest.raises(verifier.VerificationError, match="provider/chat smoke"):
        verifier.verify(args)


def test_cli_rejects_unknown_fields() -> None:
    with pytest.raises(verifier.VerificationError):
        verifier.parser().parse_args(
            [
                "capabilities",
                "--environment",
                "staging",
                "--release",
                "dspace",
                "--namespace",
                "dspace",
                "--unknown",
            ]
        )
