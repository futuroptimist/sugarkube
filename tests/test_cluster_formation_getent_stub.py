"""Ensure the cluster formation harness supplies a getent stub when absent."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cluster_formation_setup_enables_getent_stub(tmp_path: Path) -> None:
    """setup() should not skip when getent is missing by enabling the stub."""

    env = os.environ.copy()
    harness_path = REPO_ROOT / "tests" / "integration" / "cluster_formation_e2e.bats"
    env.update(
        {
            "PATH": "/usr/bin:/bin",  # intentionally exclude getent on some systems
            "BATS_TEST_FILENAME": str(harness_path),
            "BATS_TEST_TMPDIR": str(tmp_path),
            "BATS_CWD": str(REPO_ROOT),
            "AVAHI_AVAILABLE": "0",  # force stub activation
        }
    )

    cluster_harness = Path(env["BATS_TEST_FILENAME"]).read_text(encoding="utf-8")
    harness_prefix = cluster_harness.split("@test", maxsplit=1)[0]

    script = f"""
    set -euo pipefail
    skip() {{
      echo "skip invoked: $*" >&2
      exit 1
    }}
    {harness_prefix}
    setup
    command -v getent
    """

    result = subprocess.run(
        ["bash"],
        input=script,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert (
        result.returncode == 0
    ), f"Setup should succeed without skipping; stderr was:\n{result.stderr}"
    assert "getent" in result.stdout, "getent stub should be on PATH after setup()"
