"""Offline contract integration with real upstream code pinned by the CI checkout.

Set DSPACE_RUNNER_CHECKOUT to run locally. This does not replace browser verification
against the immutable image; it catches argv/proof/provider drift across repositories.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier
from test_dspace_runtime_verifier import _verify_setup

RUNNER_ROOT = os.environ.get("DSPACE_RUNNER_CHECKOUT")
pytestmark = pytest.mark.skipif(
    not RUNNER_ROOT, reason="requires the pinned DSPACE runner checkout"
)
HARNESS = Path(__file__).parent / "fixtures/dspace_hotfix/check-runner.mjs"


@pytest.mark.parametrize(
    "fault", [None, "health", "revision", "provider", "argv-version", "argv-digest"]
)
def test_actual_hotfix_runner_contract(monkeypatch, tmp_path, fault):
    assert RUNNER_ROOT and (Path(RUNNER_ROOT) / "scripts/hotfix-302-contract.mjs").is_file()
    real_run = subprocess.run
    args, _ = _verify_setup(
        monkeypatch,
        tmp_path,
        legacy=True,
        provider="openai",
        coordinates=verifier.HOTFIX_302_COORDINATES,
    )
    calls = []

    def contract_runner(argv, **kwargs):
        payload = {
            "argv": list(argv),
            "meta": {
                "gitSha": verifier.HOTFIX_302_COORDINATES["sourceRevision"],
                "generatedAt": "2026-10-31T23:34:25.629Z",
                "source": "env",
            },
            "health": {"status": "ready", "version": verifier.HOTFIX_VERSION_LABEL},
            "config": {
                "offlineWorker": {"enabled": True},
                "telemetry": {"enabled": False},
                "featureFlags": [],
            },
        }
        if fault == "health":
            payload["health"]["version"] = "3.0.2"
        elif fault == "revision":
            payload["meta"]["gitSha"] = "f" * 40
        elif fault == "provider":
            payload["config"]["chat"] = {"defaultProvider": "token-place"}
        elif fault == "argv-version":
            payload["argv"][argv.index("--expected-version") + 1] = "3.0.1"
        elif fault == "argv-digest":
            payload["argv"][argv.index("--expected-image-digest") + 1] = "sha256:" + "0" * 64
        # Execute real upstream JavaScript; never synthesize a successful exit or proof.
        result = real_run(
            ["node", "--experimental-strip-types", str(HARNESS), RUNNER_ROOT],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=30,
        )
        calls.append(result)
        return result

    monkeypatch.setattr(verifier.subprocess, "run", contract_runner)
    if fault:
        with pytest.raises(verifier.VerificationError, match="provider/chat smoke"):
            verifier.verify(args)
        assert calls[0].returncode == 2
    else:
        result = verifier.verify(args)
        verifier.release_manifest.validate_runtime_verification(
            result, json.loads(args.manifest.read_text()), "staging"
        )
        assert result["applicationVersion"] == "3.0.2"
        assert result["runtimeSourceRevision"] == verifier.HOTFIX_302_COORDINATES["sourceRevision"]
        assert calls[0].returncode == 0
        assert verifier.ARTIFACT_PROOF_PREFIX in calls[0].stdout
