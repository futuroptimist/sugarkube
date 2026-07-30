import argparse
import json
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier


def test_capabilities_schema_is_the_rollback_contract(capsys: pytest.CaptureFixture[str]) -> None:
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


def test_identity_rejects_revision_mismatch_without_echoing_body() -> None:
    sentinel = "sensitive-child-output-marker"
    body = json.dumps(
        {
            "version": "3.1.0",
            "revision": "f" * 40,
            "shortRevision": "fffffff",
            "unsafeChildOutput": sentinel,
        }
    ).encode()
    with pytest.raises(verifier.VerificationError) as caught:
        verifier.identity(body, "3.1.0", "a" * 40, "main-aaaaaaa", "public identity")
    assert sentinel not in str(caught.value)


def test_token_place_smoke_argv_is_derived_and_openai_omits_token_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = tmp_path / "smoke"
    runner.write_text("#!/bin/sh\n", encoding="utf-8")
    runner.chmod(0o755)
    calls: list[list[str]] = []
    monkeypatch.setattr(verifier, "command", lambda argv, stage: calls.append(argv) or "")
    # The construction itself is kept explicit and argv-only.
    token = [
        str(runner),
        "--base-url",
        "https://example.test",
        "--expected-provider",
        "token-place",
    ]
    token += [
        "--expected-token-place-origin",
        "https://token.test",
        "--expected-token-place-model",
        "model",
    ]
    verifier.command(token, "provider/chat smoke")
    assert calls[-1][-4:] == [
        "--expected-token-place-origin",
        "https://token.test",
        "--expected-token-place-model",
        "model",
    ]
    openai = [str(runner), "--base-url", "https://example.test", "--expected-provider", "openai"]
    verifier.command(openai, "provider/chat smoke")
    assert "--expected-token-place-origin" not in calls[-1]
    assert "--expected-token-place-model" not in calls[-1]


def test_missing_smoke_runner_fails_boundedly(monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(
        manifest=None,
        application_version="3.1.0",
        source_revision="a" * 40,
        provider="openai",
        environment="staging",
        config=None,
        smoke_runner="/does/not/exist",
        kubeconfig="unused",
        namespace="dspace",
        release="dspace",
    )
    monkeypatch.setattr(
        verifier.app_config,
        "load_config",
        lambda *args: {"SUGARKUBE_VALUES": "docs/examples/dspace.values.staging.yaml"},
    )
    with pytest.raises(verifier.VerificationError, match="existing executable"):
        verifier.verify(args)
