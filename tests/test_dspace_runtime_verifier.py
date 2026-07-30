"""Contract and secret-safe failure tests for the DSPACE runtime verifier."""

import json
import subprocess
from pathlib import Path

from scripts import dspace_runtime_verifier as verifier

SCRIPT = Path("scripts/dspace_runtime_verifier.py")


def test_capabilities_exact_schema_and_order() -> None:
    completed = subprocess.run(
        [
            str(SCRIPT),
            "capabilities",
            "--environment",
            "staging",
            "--release",
            "dspace",
            "--namespace",
            "dspace",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout) == {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "capabilities": verifier.CAPABILITIES,
    }


def test_unknown_argument_does_not_echo_value() -> None:
    secret = "SENTINEL-DO-NOT-PRINT"
    completed = subprocess.run(
        [str(SCRIPT), "capabilities", "--environment", "staging", "--unknown", secret],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert secret not in completed.stdout + completed.stderr
