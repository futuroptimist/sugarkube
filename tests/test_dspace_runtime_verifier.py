"""Hermetic contract tests for the DSPACE runtime verifier."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier


def test_capabilities_are_ordered_and_exact(capsys: pytest.CaptureFixture[str]) -> None:
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
        "capabilities": [
            "applicationVersion",
            "runtimeSourceRevision",
            "frontendSourceRevision",
            "defaultProvider",
            "publicJourneys",
        ],
    }


def test_values_expectations_follow_ordered_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "env:\n  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://old.invalid\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "env:\n"
        "  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://expected.invalid\n"
        "  - name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n    value: expected-model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(verifier, "REPO_ROOT", tmp_path)
    assert verifier.values_expectations(f"{base},{overlay}") == {
        "DSPACE_TOKEN_PLACE_URL": "https://expected.invalid",
        "DSPACE_TOKEN_PLACE_CHAT_MODEL": "expected-model",
    }


@pytest.mark.parametrize("mode", ("missing", "not-executable"))
def test_smoke_runner_must_be_executable(tmp_path: Path, mode: str) -> None:
    runner = tmp_path / "runner"
    if mode == "not-executable":
        runner.write_text("#!/bin/sh\n", encoding="utf-8")
    args = Namespace(smoke_runner=runner)
    with pytest.raises(verifier.VerificationError, match="existing executable"):
        verifier.verify(args)


def test_identity_rejects_version_revision_and_frontend_mismatch() -> None:
    expected = {"version": "3.2.0", "revision": "a" * 40, "tag": "main-aaaaaaa"}
    good = json.dumps({"version": "3.2.0", "revision": "a" * 40, "shortRevision": "aaaaaaa"})
    html = f'<meta name="dspace-build-revision" content="{"a" * 40}">'
    verifier.identity(good, html, expected, "public identity")
    with pytest.raises(verifier.VerificationError, match="application version"):
        verifier.identity(good.replace("3.2.0", "3.1.0"), html, expected, "public identity")
    with pytest.raises(verifier.VerificationError, match="frontend revision"):
        verifier.identity(good, html.replace("a" * 40, "b" * 40), expected, "public identity")


def test_cross_origin_redirect_is_rejected() -> None:
    handler = verifier.SameOriginRedirect()
    request = type("Request", (), {"full_url": "https://expected.invalid/build-info.json"})()
    with pytest.raises(verifier.VerificationError, match="changed origin"):
        handler.redirect_request(
            request, None, 302, "Found", {}, "https://attacker.invalid/build-info.json"
        )
